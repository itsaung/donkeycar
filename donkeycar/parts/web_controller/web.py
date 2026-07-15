#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Jun 24 20:10:44 2017
@author: wroscoe
remotes.py
The client and web server needed to control a car remotely.
"""


import os
import json
import logging
import time
import asyncio

import requests
from tornado.ioloop import IOLoop
from tornado.web import Application, RedirectHandler, StaticFileHandler, \
    RequestHandler
from tornado.httpserver import HTTPServer
import tornado.gen
import tornado.websocket
from socket import gethostname

from ... import utils

logger = logging.getLogger(__name__)


class RemoteWebServer():
    '''
    A controller that repeatedly polls a remote webserver and expects
    the response to be angle, throttle and drive mode.
    '''

    def __init__(self, remote_url, connection_timeout=.25):

        self.control_url = remote_url
        self.time = 0.
        self.angle = 0.
        self.throttle = 0.
        self.mode = 'user'
        self.mode_latch = None
        self.recording = False
        # use one session for all requests
        self.session = requests.Session()

    def update(self):
        '''
        Loop to run in separate thread the updates angle, throttle and
        drive mode.
        '''

        while True:
            # get latest value from server
            self.angle, self.throttle, self.mode, self.recording = self.run()

    def run_threaded(self):
        '''
        Return the last state given from the remote server.
        '''
        return self.angle, self.throttle, self.mode, self.recording

    def run(self):
        '''
        Posts current car sensor data to webserver and returns
        angle and throttle recommendations.
        '''

        data = {}
        response = None
        while response is None:
            try:
                response = self.session.post(self.control_url,
                                             files={'json': json.dumps(data)},
                                             timeout=0.25)

            except requests.exceptions.ReadTimeout as err:
                print("\n Request took too long. Retrying")
                # Lower throttle to prevent runaways.
                return self.angle, self.throttle * .8, None

            except requests.ConnectionError as err:
                # try to reconnect every 3 seconds
                print("\n Vehicle could not connect to server. Make sure you've " +
                    "started your server and you're referencing the right port.")
                time.sleep(3)

        data = json.loads(response.text)
        angle = float(data['angle'])
        throttle = float(data['throttle'])
        drive_mode = str(data['drive_mode'])
        recording = bool(data['recording'])

        return angle, throttle, drive_mode, recording

    def shutdown(self):
        pass


class LocalWebController(tornado.web.Application):

    def __init__(self, port=8887, mode='user'):
        """
        Create and publish variables needed on many of
        the web handlers.
        """
        logger.info('Starting Donkey Server...')

        this_dir = os.path.dirname(os.path.realpath(__file__))
        self.static_file_path = os.path.join(this_dir, 'templates', 'static')
        self.angle = 0.0
        self.throttle = 0.0
        self.mode = mode
        self.mode_latch = None
        self.recording = False
        self.recording_latch = None
        self.buttons = {}  # latched button values for processing

        self.port = port

        self.num_records = 0
        self.wsclients = []
        self.loop = None
        self.tub = None  # set via set_tub() after TubWriter is created


        handlers = [
            (r"/", RedirectHandler, dict(url="/drive")),
            (r"/drive", DriveAPI),
            (r"/wsDrive", WebSocketDriveAPI),
            (r"/wsCalibrate", WebSocketCalibrateAPI),
            (r"/calibrate", CalibrateHandler),
            (r"/video", VideoAPI),
            (r"/wsTest", WsTest),
            (r"/api/tub/recent", TubRecentAPI),
            (r"/api/tub/image/([0-9]+)", TubImageAPI),
            (r"/api/tub/delete", TubDeleteAPI),

            (r"/static/(.*)", StaticFileHandler,
             {"path": self.static_file_path}),
        ]

        settings = {'debug': True}
        super().__init__(handlers, **settings)
        logger.info(f"You can now go to {gethostname()}.local:{port} to "
                    f"drive your car.")

    def set_tub(self, tub):
        """Attach the active recording tub for in-drive review/delete."""
        self.tub = tub
        logger.info(f"Web controller tub attached: {getattr(tub, 'base_path', tub)}")

    def _image_key(self):
        """Return the tub field name that stores camera images."""
        if self.tub is None:
            return 'cam/image_array'
        inputs = list(self.tub.manifest.inputs or self.tub.inputs or [])
        types = list(self.tub.manifest.types or self.tub.types or [])
        for key, typ in zip(inputs, types):
            if typ == 'image_array':
                return key
        return 'cam/image_array'

    @staticmethod
    def _record_angle(rec):
        for key in ('user/angle', 'steering', 'pilot/angle'):
            if key in rec and rec[key] is not None:
                return float(rec[key])
        return 0.0

    @staticmethod
    def _record_throttle(rec):
        for key in ('user/throttle', 'throttle', 'pilot/throttle'):
            if key in rec and rec[key] is not None:
                return float(rec[key])
        return 0.0

    def get_recent_records(self, n=100):
        """
        Return the last n non-deleted records as lightweight dicts for the UI.
        Reads only as many trailing catalog files as needed.
        """
        if self.tub is None:
            return [], 0, None

        n = max(1, min(int(n), 500))
        image_key = self._image_key()
        manifest = self.tub.manifest
        alive = sorted(
            set(range(manifest.current_index)) - manifest.deleted_indexes
        )
        total = len(alive)
        if not alive:
            return [], 0, getattr(self.tub, 'base_path', None)

        wanted_indexes = alive[-n:]
        min_wanted = wanted_indexes[0]
        wanted_set = set(wanted_indexes)
        max_len = max(1, int(manifest.max_len))
        catalog_paths = list(manifest.catalog_paths)
        # Only open catalogs that can contain wanted indexes
        start_catalog = min_wanted // max_len
        by_idx = {}

        from donkeycar.parts.datastore_v2 import Catalog

        for catalog_i in range(start_catalog, len(catalog_paths)):
            catalog_path = os.path.join(manifest.base_path,
                                        catalog_paths[catalog_i])
            catalog = Catalog(catalog_path, read_only=True)
            try:
                catalog.seekable.seek_line_start(1)
                # Absolute index of first record in this catalog
                abs_index = catalog_i * max_len
                while True:
                    contents = catalog.seekable.readline()
                    if contents is None or len(contents) == 0:
                        break
                    if abs_index in manifest.deleted_indexes:
                        abs_index += 1
                        continue
                    if abs_index < min_wanted:
                        abs_index += 1
                        continue
                    if abs_index > wanted_indexes[-1]:
                        break
                    try:
                        rec = json.loads(contents)
                    except Exception:
                        abs_index += 1
                        continue
                    # Prefer catalog _index if present
                    idx = rec.get('_index', abs_index)
                    if idx in wanted_set:
                        by_idx[idx] = {
                            'index': idx,
                            'angle': self._record_angle(rec),
                            'throttle': self._record_throttle(rec),
                            'image_file': rec.get(image_key),
                            'timestamp_ms': rec.get('_timestamp_ms'),
                        }
                    abs_index += 1
            finally:
                try:
                    catalog.close()
                except Exception:
                    pass

        recent = [by_idx[i] for i in wanted_indexes if i in by_idx]
        return recent, total, getattr(self.tub, 'base_path', None)

    def delete_record_indexes(self, indexes):
        """Soft-delete the given record indexes from the attached tub."""
        if self.tub is None:
            raise RuntimeError('No tub attached to web controller')
        indexes = sorted({int(i) for i in indexes})
        if not indexes:
            return 0
        # Never delete the index currently being written (current_index is next)
        max_safe = self.tub.manifest.current_index - 1
        indexes = [i for i in indexes if 0 <= i <= max_safe]
        if not indexes:
            return 0
        self.tub.delete_records(indexes)
        logger.info(f"Deleted {len(indexes)} tub records via web UI")
        return len(indexes)

    def update(self):
        """ Start the tornado webserver. """
        asyncio.set_event_loop(asyncio.new_event_loop())
        self.listen(self.port)
        self.loop = IOLoop.instance()
        self.loop.start()

    def update_wsclients(self, data):
        if data:
            for wsclient in self.wsclients:
                try:
                    data_str = json.dumps(data)
                    logger.debug(f"Updating web client: {data_str}")
                    wsclient.write_message(data_str)
                except Exception as e:
                    logger.warning("Error writing websocket message",
                                   exc_info=e)
                    pass

    def run_threaded(self, img_arr=None, num_records=0, mode=None, recording=None):
        """
        :param img_arr: current camera image or None
        :param num_records: current number of data records
        :param mode: default user/mode
        :param recording: default recording mode
        """
        self.img_arr = img_arr
        self.num_records = num_records

        #
        # enforce defaults if they are not none.
        #
        changes = {}
        if mode is not None and self.mode != mode:
            self.mode = mode
            changes["driveMode"] = self.mode
        if self.mode_latch is not None:
            self.mode = self.mode_latch
            self.mode_latch = None
            changes["driveMode"] = self.mode
        if recording is not None and self.recording != recording:
            self.recording = recording
            changes["recording"] = self.recording
        if self.recording_latch is not None:
            self.recording = self.recording_latch;
            self.recording_latch = None;
            changes["recording"] = self.recording;

        # Send record count to websocket clients
        if (self.num_records is not None and self.recording is True):
            if self.num_records % 10 == 0:
                changes['num_records'] = self.num_records

        #
        # get latched button presses then clear button presses
        # Next iteration will clear press in memory
        #
        buttons = self.buttons
        self.buttons = {}
        for button, pressed in buttons.items():
            if pressed:
                self.buttons[button] = False

        # if there were changes, then send to web client
        if changes and self.loop is not None:
            logger.debug(str(changes))
            self.loop.add_callback(lambda: self.update_wsclients(changes))

        return self.angle, self.throttle, self.mode, self.recording, buttons

    def run(self, img_arr=None, num_records=0, mode=None, recording=None):
        return self.run_threaded(img_arr, num_records, mode, recording)

    def shutdown(self):
        pass


class TubRecentAPI(RequestHandler):
    """Return the last N recorded frames for the review drawer."""

    def get(self):
        try:
            n = int(self.get_argument('n', '100'))
        except ValueError:
            n = 100
        records, total, tub_path = self.application.get_recent_records(n)
        self.set_header('Content-Type', 'application/json')
        self.write(json.dumps({
            'ok': True,
            'tub_path': tub_path,
            'total': total,
            'count': len(records),
            'n': n,
            'recording': bool(self.application.recording),
            'records': records,
        }))


class TubImageAPI(RequestHandler):
    """Serve a single tub image by record index."""

    def get(self, index):
        from donkeycar.parts.tub_v2 import Tub

        tub = self.application.tub
        if tub is None:
            self.set_status(404)
            self.write('No tub attached')
            return
        try:
            index = int(index)
        except ValueError:
            self.set_status(400)
            self.write('Invalid index')
            return

        if index in tub.manifest.deleted_indexes:
            self.set_status(404)
            self.write('Record deleted')
            return

        image_key = self.application._image_key()
        # Try jpg then png using Tub naming convention
        image_path = None
        for ext in ('.jpg', '.png'):
            name = Tub._image_file_name(index, image_key, extension=ext)
            candidate = os.path.join(tub.images_base_path, name)
            if os.path.isfile(candidate):
                image_path = candidate
                break

        if image_path is None:
            self.set_status(404)
            self.write('Image file missing')
            return

        if image_path.lower().endswith('.png'):
            self.set_header('Content-Type', 'image/png')
        else:
            self.set_header('Content-Type', 'image/jpeg')
        self.set_header('Cache-Control', 'no-cache')
        with open(image_path, 'rb') as f:
            self.write(f.read())


class TubDeleteAPI(RequestHandler):
    """Soft-delete selected record indexes from the active tub."""

    def post(self):
        try:
            data = tornado.escape.json_decode(self.request.body or b'{}')
        except Exception:
            self.set_status(400)
            self.write(json.dumps({'ok': False, 'error': 'Invalid JSON'}))
            return

        indexes = data.get('indexes') or []
        if not isinstance(indexes, list):
            self.set_status(400)
            self.write(json.dumps({'ok': False, 'error': 'indexes must be a list'}))
            return

        # Stop recording while deleting to avoid racing the writer
        if self.application.recording:
            self.application.recording = False
            self.application.recording_latch = False
            if self.application.loop is not None:
                self.application.loop.add_callback(
                    lambda: self.application.update_wsclients(
                        {'recording': False}))

        try:
            deleted = self.application.delete_record_indexes(indexes)
        except RuntimeError as e:
            self.set_status(400)
            self.write(json.dumps({'ok': False, 'error': str(e)}))
            return
        except Exception as e:
            logger.exception('Tub delete failed')
            self.set_status(500)
            self.write(json.dumps({'ok': False, 'error': str(e)}))
            return

        tub = self.application.tub
        total = len(tub) if tub is not None else 0
        tub_path = getattr(tub, 'base_path', None) if tub is not None else None
        self.set_header('Content-Type', 'application/json')
        self.write(json.dumps({
            'ok': True,
            'deleted': deleted,
            'total': total,
            'tub_path': tub_path,
        }))


class DriveAPI(RequestHandler):

    def get(self):
        data = {}
        self.render("templates/vehicle.html", **data)

    def post(self):
        '''
        Receive post requests as user changes the angle
        and throttle of the vehicle on a the index webpage
        '''
        data = tornado.escape.json_decode(self.request.body)

        if data.get('angle') is not None:
            self.application.angle = data['angle']
        if data.get('throttle') is not None:
            self.application.throttle = data['throttle']
        if data.get('drive_mode') is not None:
            self.application.mode = data['drive_mode']
        if data.get('recording') is not None:
            self.application.recording = data['recording']
        if data.get('buttons') is not None:
            latch_buttons(self.application.buttons, data['buttons'])


class WsTest(RequestHandler):
    def get(self):
        data = {}
        self.render("templates/wsTest.html", **data)


class CalibrateHandler(RequestHandler):
    """ Serves the calibration web page"""
    async def get(self):
        await self.render("templates/calibrate.html")


def latch_buttons(buttons, pushes):
    """
    Latch button pushes
    buttons: the latched values
    pushes: the update value
    """
    if pushes is not None:
        #
        # we got button pushes.
        # - we latch the pushed buttons so we can process the push
        # - after it is processed we clear it
        #
        for button in pushes:
            # if pushed, then latch it
            if pushes[button]:
                buttons[button] = True


class WebSocketDriveAPI(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        return True

    def open(self):
        logger.info("New client connected")
        self.application.wsclients.append(self)

    def on_message(self, message):
        data = json.loads(message)
        self.application.angle = data.get('angle', self.application.angle)
        self.application.throttle = data.get('throttle', self.application.throttle)
        if data.get('drive_mode') is not None:
            self.application.mode = data['drive_mode']
            self.application.mode_latch = self.application.mode
        if data.get('recording') is not None:
            self.application.recording = data['recording']
            self.application.recording_latch = self.application.recording
        if data.get('buttons') is not None:
            latch_buttons(self.application.buttons, data['buttons'])

    def on_close(self):
        logger.info("Client disconnected")
        self.application.wsclients.remove(self)


class WebSocketCalibrateAPI(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        return True

    def open(self):
        logger.info("New client connected")

    def on_message(self, message):
        logger.info(f"wsCalibrate {message}")
        data = json.loads(message)
        if 'throttle' in data:
            print(data['throttle'])
            self.application.throttle = data['throttle']

        if 'angle' in data:
            print(data['angle'])
            self.application.angle = data['angle']

        if 'config' in data:
            config = data['config']
            if self.application.drive_train_type == "PWM_STEERING_THROTTLE" \
                or self.application.drive_train_type == "I2C_SERVO":
                if 'STEERING_LEFT_PWM' in config:
                    self.application.drive_train['steering'].left_pulse = config['STEERING_LEFT_PWM']

                if 'STEERING_RIGHT_PWM' in config:
                    self.application.drive_train['steering'].right_pulse = config['STEERING_RIGHT_PWM']

                if 'THROTTLE_FORWARD_PWM' in config:
                    self.application.drive_train['throttle'].max_pulse = config['THROTTLE_FORWARD_PWM']

                if 'THROTTLE_STOPPED_PWM' in config:
                    self.application.drive_train['throttle'].zero_pulse = config['THROTTLE_STOPPED_PWM']

                if 'THROTTLE_REVERSE_PWM' in config:
                    self.application.drive_train['throttle'].min_pulse = config['THROTTLE_REVERSE_PWM']

            elif self.application.drive_train_type == "MM1":
                if ('MM1_STEERING_MID' in config) and (config['MM1_STEERING_MID'] != 0):
                        self.application.drive_train.STEERING_MID = config['MM1_STEERING_MID']
                if ('MM1_MAX_FORWARD' in config) and (config['MM1_MAX_FORWARD'] != 0):
                        self.application.drive_train.MAX_FORWARD = config['MM1_MAX_FORWARD']
                if ('MM1_MAX_REVERSE' in config) and (config['MM1_MAX_REVERSE'] != 0):
                    self.application.drive_train.MAX_REVERSE = config['MM1_MAX_REVERSE']

    def on_close(self):
        logger.info("Client disconnected")


class VideoAPI(RequestHandler):
    '''
    Serves a MJPEG of the images posted from the vehicle.
    '''

    async def get(self):
        placeholder_image = utils.load_image_sized(
                        os.path.join(self.application.static_file_path,
                                     "img_placeholder.jpg"), 160, 120, 3)

        self.set_header("Content-type",
                        "multipart/x-mixed-replace;boundary=--boundarydonotcross")

        served_image_timestamp = time.time()
        my_boundary = "--boundarydonotcross\n"
        while True:

            interval = .005
            if served_image_timestamp + interval < time.time():
                #
                # if we have an image, then use it.
                # otherwise show placeholder
                #
                if hasattr(self.application, 'img_arr') and self.application.img_arr is not None:
                    img = utils.arr_to_binary(self.application.img_arr)
                else:
                    img = utils.arr_to_binary(placeholder_image)

                self.write(my_boundary)
                self.write("Content-type: image/jpeg\r\n")
                self.write("Content-length: %s\r\n\r\n" % len(img))
                self.write(img)
                served_image_timestamp = time.time()
                try:
                    await self.flush()
                except tornado.iostream.StreamClosedError:
                    pass
            else:
                await tornado.gen.sleep(interval)


class BaseHandler(RequestHandler):
    """ Serves the FPV web page"""
    async def get(self):
        data = {}
        await self.render("templates/base_fpv.html", **data)


class WebFpv(Application):
    """
    Class for running an FPV web server that only shows the camera in real-time.
    The web page contains the camera view and auto-adjusts to the web browser
    window size. Conjecture: this picture up-scaling is performed by the
    client OS using graphics acceleration. Hence a web browser on the PC is
    faster than a pure python application based on open cv or similar.
    """

    def __init__(self, port=8890):
        self.port = port
        this_dir = os.path.dirname(os.path.realpath(__file__))
        self.static_file_path = os.path.join(this_dir, 'templates', 'static')

        """Construct and serve the tornado application."""
        handlers = [
            (r"/", BaseHandler),
            (r"/video", VideoAPI),
            (r"/static/(.*)", StaticFileHandler,
             {"path": self.static_file_path})
        ]

        settings = {'debug': True}
        self.img_arr = None
        super().__init__(handlers, **settings)
        logger.info(f"Started Web FPV server. You can now go to "
                    f"{gethostname()}.local:{self.port} to view the car camera")

    def update(self):
        """ Start the tornado webserver. """
        asyncio.set_event_loop(asyncio.new_event_loop())
        self.listen(self.port)
        IOLoop.instance().start()

    def run_threaded(self, img_arr=None):
        self.img_arr = img_arr

    def run(self, img_arr=None):
        self.img_arr = img_arr

    def shutdown(self):
        pass


