#!/usr/bin/env python3
"""
Agent API controller — REST + WebSocket access for external agents.

Safety:
- Starts inactive; human web/joystick controls pass through unchanged.
- While active, agent steering/throttle overwrite user channels.
- If no control command arrives within the timeout, throttle is zeroed
  and the agent is deactivated.
"""

import asyncio
import base64
import json
import logging
import time
from socket import gethostname

import tornado.escape
import tornado.websocket
from tornado.ioloop import IOLoop, PeriodicCallback
from tornado.web import Application, RequestHandler

from ... import utils

logger = logging.getLogger(__name__)


def _as_list(vec):
    if vec is None:
        return None
    try:
        return [float(x) for x in vec]
    except (TypeError, ValueError):
        return None


class AgentApiController(Application):
    """
    Threaded Vehicle part that exposes robot controls and sensors over HTTP/WS.

    Vehicle wiring (typical)::

        V.add(agent,
              inputs=['cam/image_array', 'user/steering', 'user/throttle',
                      'user/mode', 'recording', 'imu/accel', 'imu/gyro',
                      'enc/speed'],
              outputs=['user/steering', 'user/throttle', 'user/mode',
                       'recording'],
              threaded=True)
    """

    def __init__(self, port=8891, mode='user', command_timeout_secs=0.5,
                 token='', stream_hz=10):
        self.port = int(port)
        self.command_timeout_secs = float(command_timeout_secs)
        self.token = token or ''
        self.stream_hz = max(1, int(stream_hz))

        self.agent_active = False
        self.angle = 0.0
        self.throttle = 0.0
        self.mode = mode
        self.recording = False
        self.last_command_time = None

        self.img_arr = None
        self.imu_accel = None
        self.imu_gyro = None
        self.enc_speed = None
        self.num_records = 0

        # Last human values seen while inactive (for state reporting).
        self.human_angle = 0.0
        self.human_throttle = 0.0

        self.loop = None
        self.wsclients = []
        self._stream_callback = None

        handlers = [
            (r"/api/v1/health", HealthHandler),
            (r"/api/v1/state", StateHandler),
            (r"/api/v1/control", ControlHandler),
            (r"/api/v1/active", ActiveHandler),
            (r"/api/v1/camera\.jpg", CameraHandler),
            (r"/api/v1/stream", StreamWebSocket),
        ]
        super().__init__(handlers, debug=False)
        logger.info(
            "Agent API listening on http://%s.local:%s/api/v1/ "
            "(inactive until claimed)",
            gethostname(), self.port)

    def authorized(self, handler):
        if not self.token:
            return True
        auth = handler.request.headers.get('Authorization', '')
        if auth == f'Bearer {self.token}':
            return True
        # Also accept ?token= for simple clients / WS query params.
        return handler.get_argument('token', default=None) == self.token

    def set_active(self, active):
        active = bool(active)
        if active and not self.agent_active:
            self.last_command_time = time.time()
            logger.info("Agent API: agent ACTIVE")
        elif not active and self.agent_active:
            self.throttle = 0.0
            logger.info("Agent API: agent INACTIVE")
        self.agent_active = active
        if not active:
            self.last_command_time = None

    def apply_control(self, data):
        """Apply a control payload; activates the agent."""
        if 'steering' in data and data['steering'] is not None:
            self.angle = float(data['steering'])
        elif 'angle' in data and data['angle'] is not None:
            # Alias for LocalWebController compatibility.
            self.angle = float(data['angle'])
        if 'throttle' in data and data['throttle'] is not None:
            self.throttle = float(data['throttle'])
        if data.get('mode') is not None:
            self.mode = str(data['mode'])
        if data.get('recording') is not None:
            self.recording = bool(data['recording'])
        self.last_command_time = time.time()
        if not self.agent_active:
            self.agent_active = True
            logger.info("Agent API: agent ACTIVE (via control)")

    def effective_outputs(self, user_steering, user_throttle, user_mode,
                          recording):
        """
        Pass through human controls when inactive; apply agent when active.
        Enforce command timeout.
        """
        if user_steering is not None:
            self.human_angle = float(user_steering)
        if user_throttle is not None:
            self.human_throttle = float(user_throttle)
        if user_mode is not None:
            # Track human mode only while inactive so agent mode sticks.
            if not self.agent_active:
                self.mode = user_mode
        if recording is not None and not self.agent_active:
            self.recording = bool(recording)

        if self.agent_active:
            if self.last_command_time is None or (
                    time.time() - self.last_command_time
                    > self.command_timeout_secs):
                logger.warning(
                    "Agent API: command timeout (%.2fs) — "
                    "zero throttle, deactivate",
                    self.command_timeout_secs)
                self.throttle = 0.0
                self.agent_active = False
                self.last_command_time = None
                return (self.human_angle, 0.0, self.mode, self.recording)

            return (self.angle, self.throttle, self.mode, self.recording)

        # Inactive: pass through human inputs.
        steering = (float(user_steering) if user_steering is not None
                    else self.human_angle)
        throttle = (float(user_throttle) if user_throttle is not None
                    else self.human_throttle)
        mode = user_mode if user_mode is not None else self.mode
        rec = bool(recording) if recording is not None else self.recording
        return steering, throttle, mode, rec

    def build_state(self):
        steering = self.angle if self.agent_active else self.human_angle
        throttle = self.throttle if self.agent_active else self.human_throttle
        return {
            'agent_active': self.agent_active,
            'steering': steering,
            'throttle': throttle,
            'mode': self.mode,
            'recording': self.recording,
            'imu': {
                'accel': _as_list(self.imu_accel),
                'gyro': _as_list(self.imu_gyro),
            },
            'enc_speed': (float(self.enc_speed)
                          if self.enc_speed is not None else None),
            'num_records': self.num_records,
            'timestamp': time.time(),
        }

    def jpeg_bytes(self):
        if self.img_arr is None:
            return None
        return utils.arr_to_binary(self.img_arr)

    def update(self):
        """Start the Tornado webserver (runs in a daemon thread)."""
        asyncio.set_event_loop(asyncio.new_event_loop())
        self.listen(self.port)
        self.loop = IOLoop.current()
        interval_ms = int(1000 / self.stream_hz)
        self._stream_callback = PeriodicCallback(
            self._push_stream, interval_ms)
        self._stream_callback.start()
        self.loop.start()

    def _push_stream(self):
        if not self.wsclients:
            return
        payload = self.build_state()
        jpeg = self.jpeg_bytes()
        if jpeg is not None:
            payload['camera_jpeg_base64'] = base64.b64encode(jpeg).decode(
                'ascii')
        else:
            payload['camera_jpeg_base64'] = None
        msg = json.dumps(payload)
        dead = []
        for ws in self.wsclients:
            try:
                ws.write_message(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self.wsclients:
                self.wsclients.remove(ws)

    def run_threaded(self, img_arr=None, user_steering=None, user_throttle=None,
                     user_mode=None, recording=None, imu_accel=None,
                     imu_gyro=None, enc_speed=None, num_records=0):
        self.img_arr = img_arr
        self.imu_accel = imu_accel
        self.imu_gyro = imu_gyro
        self.enc_speed = enc_speed
        if num_records is not None:
            self.num_records = num_records
        return self.effective_outputs(
            user_steering, user_throttle, user_mode, recording)

    def run(self, img_arr=None, user_steering=None, user_throttle=None,
            user_mode=None, recording=None, imu_accel=None, imu_gyro=None,
            enc_speed=None, num_records=0):
        return self.run_threaded(
            img_arr, user_steering, user_throttle, user_mode, recording,
            imu_accel, imu_gyro, enc_speed, num_records)

    def shutdown(self):
        self.agent_active = False
        self.throttle = 0.0
        if self._stream_callback is not None:
            try:
                self._stream_callback.stop()
            except Exception:
                pass
        if self.loop is not None:
            try:
                self.loop.add_callback(self.loop.stop)
            except Exception:
                pass


class _AuthMixin:
    def prepare(self):
        if not self.application.authorized(self):
            self.set_status(401)
            self.set_header('Content-Type', 'application/json')
            self.finish(json.dumps({'error': 'unauthorized'}))


class HealthHandler(_AuthMixin, RequestHandler):
    def get(self):
        self.set_header('Content-Type', 'application/json')
        self.write(json.dumps({
            'ok': True,
            'agent_active': self.application.agent_active,
            'service': 'donkeycar-agent-api',
        }))


class StateHandler(_AuthMixin, RequestHandler):
    def get(self):
        self.set_header('Content-Type', 'application/json')
        self.write(json.dumps(self.application.build_state()))


class ControlHandler(_AuthMixin, RequestHandler):
    def post(self):
        try:
            data = tornado.escape.json_decode(self.request.body or b'{}')
        except Exception:
            self.set_status(400)
            self.write(json.dumps({'error': 'invalid json'}))
            return
        self.application.apply_control(data)
        self.set_header('Content-Type', 'application/json')
        self.write(json.dumps(self.application.build_state()))


class ActiveHandler(_AuthMixin, RequestHandler):
    def post(self):
        try:
            data = tornado.escape.json_decode(self.request.body or b'{}')
        except Exception:
            self.set_status(400)
            self.write(json.dumps({'error': 'invalid json'}))
            return
        if 'active' not in data:
            self.set_status(400)
            self.write(json.dumps({'error': 'missing active'}))
            return
        self.application.set_active(data['active'])
        self.set_header('Content-Type', 'application/json')
        self.write(json.dumps(self.application.build_state()))


class CameraHandler(_AuthMixin, RequestHandler):
    def get(self):
        jpeg = self.application.jpeg_bytes()
        if jpeg is None:
            self.set_status(404)
            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps({'error': 'no camera frame'}))
            return
        self.set_header('Content-Type', 'image/jpeg')
        self.set_header('Cache-Control', 'no-store')
        self.write(jpeg)


class StreamWebSocket(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        return True

    def open(self):
        if not self.application.authorized(self):
            self.close(code=4401, reason='unauthorized')
            return
        logger.info("Agent API: stream client connected")
        self.application.wsclients.append(self)

    def on_message(self, message):
        # Allow control messages over the same WS for low-latency loops.
        try:
            data = json.loads(message)
        except Exception:
            return
        if data.get('type') == 'control' or 'steering' in data or 'throttle' in data:
            self.application.apply_control(data)
        elif data.get('type') == 'active' and 'active' in data:
            self.application.set_active(data['active'])

    def on_close(self):
        logger.info("Agent API: stream client disconnected")
        if self in self.application.wsclients:
            self.application.wsclients.remove(self)
