#!/usr/bin/env python3
"""

Scripts to drive on autopilot using computer vision

Usage:
    manage.py (drive) [--js] [--log=INFO] [--camera=(single|stereo)] [--myconfig=<filename>]


Options:
    -h --help          Show this screen.
    --js               Use physical joystick.
    --myconfig=filename     Specify myconfig file to use.
                            [default: myconfig_line_following_sungsan.py]
"""
import logging
from pathlib import Path
import sys
import time

_SCRIPT_DIR = Path(__file__).resolve().parent
_ORIGINAL_SYS_PATH = list(sys.path)

# `/home/pi/mycar` may contain a development checkout named `donkeycar`.
# Temporarily remove the script directory so this personal launcher uses the
# stable package installed in `/home/pi/env`, then restore it so the personal
# line-following controller can still be imported from the mycar directory.
try:
    sys.path[:] = [
        entry for entry in sys.path
        if Path(entry or ".").resolve() != _SCRIPT_DIR
    ]

    from docopt import docopt
    from simple_pid import PID

    import donkeycar as dk
    from donkeycar.parts.tub_v2 import TubWriter
    from donkeycar.parts.datastore import TubHandler
    from donkeycar.templates.complete import add_odometry, add_camera, \
        add_user_controller, add_drivetrain, add_simulator, add_imu, DriveMode, \
        UserPilotCondition, ToggleRecording
    from donkeycar.parts.logger import LoggerPart
    from donkeycar.parts.transform import Lambda
    from donkeycar.parts.explode import ExplodeDict
    from donkeycar.parts.controller import JoystickController
finally:
    sys.path[:] = _ORIGINAL_SYS_PATH

_DONKEYCAR_SOURCE = Path(dk.__file__).resolve()
_LOCAL_DONKEYCAR_DIR = _SCRIPT_DIR / "donkeycar"
if _LOCAL_DONKEYCAR_DIR == _DONKEYCAR_SOURCE.parent:
    raise RuntimeError(
        "Sungsan launcher loaded the local DonkeyCar development checkout "
        "instead of the stable virtual-environment package: {}".format(
            _DONKEYCAR_SOURCE
        )
    )

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
logger.info("Using isolated DonkeyCar package: %s", _DONKEYCAR_SOURCE)


class CameraFrameWatchdog:
    """Stop the vehicle if a threaded camera stops producing new frames."""

    def __init__(
            self, camera, vehicle, timeout_seconds=0.5,
            startup_timeout_seconds=5.0, time_fn=time.monotonic):
        self.camera = camera
        self.vehicle = vehicle
        self.timeout_seconds = max(0.05, float(timeout_seconds))
        self.startup_timeout_seconds = max(
            self.timeout_seconds, float(startup_timeout_seconds)
        )
        self.time_fn = time_fn
        now = self.time_fn()
        self.started_at = now
        self.last_change_at = now
        self.last_frame_count = getattr(camera, 'frame_count', None)
        self.received_frame = False
        self.triggered = False

    @staticmethod
    def _annotate(image, message):
        if image is None:
            return None
        try:
            import cv2

            annotated = image.copy()
            cv2.rectangle(
                annotated, (0, 0), (annotated.shape[1], 46),
                (0, 0, 180), -1
            )
            cv2.putText(
                annotated, message, (12, 31), cv2.FONT_HERSHEY_SIMPLEX,
                0.75, (255, 255, 255), 2, cv2.LINE_AA
            )
            return annotated
        except Exception:
            logger.exception("Could not annotate camera watchdog image")
            return image

    def _stop(self, image, reason):
        if not self.triggered:
            logger.error(
                "CAMERA WATCHDOG STOP: %s. Steering and throttle forced to "
                "zero; restart the drive command after checking OAK-D/USB.",
                reason,
            )
        self.triggered = True
        self.vehicle.on = False
        return 0.0, 0.0, self._annotate(
            image, "CAMERA STALE - MOTOR STOP"
        )

    def run(self, steering, throttle, image):
        now = self.time_fn()
        frame_count = getattr(self.camera, 'frame_count', None)
        camera_image = getattr(self.camera, 'color_image', None)

        if frame_count != self.last_frame_count:
            self.last_frame_count = frame_count
            self.last_change_at = now
            if camera_image is not None:
                if not self.received_frame:
                    logger.info(
                        "Camera watchdog armed at frame %s", frame_count
                    )
                self.received_frame = True

        if not self.received_frame:
            waiting_for = now - self.started_at
            if waiting_for >= self.startup_timeout_seconds:
                return self._stop(
                    image,
                    "no initial frame for {:.2f}s".format(waiting_for),
                )
            return 0.0, 0.0, self._annotate(
                image, "WAITING FOR CAMERA"
            )

        stale_for = now - self.last_change_at
        if stale_for >= self.timeout_seconds:
            return self._stop(
                image,
                "frame counter {} unchanged for {:.2f}s".format(
                    frame_count, stale_for
                ),
            )

        return steering, throttle, image


def drive(cfg, use_joystick=False, camera_type='single', meta=[]):
    '''
    Construct a working robotic vehicle from many parts.
    Each part runs as a job in the Vehicle loop, calling either
    it's run or run_threaded method depending on the constructor flag `threaded`.
    All parts are updated one after another at the framerate given in
    cfg.DRIVE_LOOP_HZ assuming each part finishes processing in a timely manner.
    Parts may have named outputs and inputs. The framework handles passing named outputs
    to parts requesting the same named input.
    '''
    
    #Initialize car
    V = dk.vehicle.Vehicle()

    #
    # if we are using the simulator, set it up
    #
    add_simulator(V, cfg)

    #
    # setup primary camera
    #
    camera_part_start = len(V.parts)
    add_camera(V, cfg, camera_type)
    camera_part = next(
        (
            entry['part'] for entry in V.parts[camera_part_start:]
            if hasattr(entry['part'], 'frame_count')
        ),
        None,
    )
    camera_watchdog_enabled = bool(getattr(
        cfg, 'CAMERA_FRAME_WATCHDOG_ENABLED', False
    ))
    if camera_watchdog_enabled and camera_part is None:
        raise RuntimeError(
            "Camera watchdog is enabled but the camera does not expose "
            "frame_count"
        )

    #
    # add the user input controller(s)
    # - this will add the web controller
    # - it will optionally add any configured 'joystick' controller
    #
    has_input_controller = hasattr(cfg, "CONTROLLER_TYPE") and cfg.CONTROLLER_TYPE != "mock"
    ctr = add_user_controller(V, cfg, use_joystick, input_image = 'ui/image_array')

    #
    # explode the web buttons into their own key/values in memory
    #
    V.add(ExplodeDict(V.mem, "web/"), inputs=['web/buttons'])

    #
    # track user vs autopilot condition
    #
    V.add(UserPilotCondition(show_pilot_image=getattr(cfg, 'OVERLAY_IMAGE', False)),
          inputs=['user/mode', "cam/image_array", "cv/image_array"],
          outputs=['run_user', "run_pilot", "ui/image_array"])

    #
    # PID controller to be used with cv_controller
    #
    pid = PID(Kp=cfg.PID_P, Ki=cfg.PID_I, Kd=cfg.PID_D)
    def dec_pid_d():
        pid.Kd -= cfg.PID_D_DELTA
        logging.info("pid: d- %f" % pid.Kd)

    def inc_pid_d():
        pid.Kd += cfg.PID_D_DELTA
        logging.info("pid: d+ %f" % pid.Kd)

    def dec_pid_p():
        pid.Kp -= cfg.PID_P_DELTA
        logging.info("pid: p- %f" % pid.Kp)

    def inc_pid_p():
        pid.Kp += cfg.PID_P_DELTA
        logging.info("pid: p+ %f" % pid.Kp)

    #
    # Computer Vision Controller
    #
    add_cv_controller(V, cfg, pid,
                      cfg.CV_CONTROLLER_MODULE,
                      cfg.CV_CONTROLLER_CLASS,
                      cfg.CV_CONTROLLER_INPUTS,
                      cfg.CV_CONTROLLER_OUTPUTS,
                      cfg.CV_CONTROLLER_CONDITION)

    recording_control = ToggleRecording(cfg.AUTO_RECORD_ON_THROTTLE, cfg.RECORD_DURING_AI)
    V.add(recording_control, inputs=['user/mode', "recording"], outputs=["recording"])


    #
    # Add buttons for handling various user actions
    # The button names are in configuration.
    # They may refer to game controller (joystick) buttons OR web ui buttons
    #
    # There are 5 programmable webui buttons, "web/w1" to "web/w5"
    # adding a button handler for a webui button
    # is just adding a part with a run_condition set to
    # the button's name, so it runs when button is pressed.
    #
    have_joystick = ctr is not None and isinstance(ctr, JoystickController)

    # button to toggle recording
    if cfg.TOGGLE_RECORDING_BTN:
        print(f"Toggle recording button is {cfg.TOGGLE_RECORDING_BTN}")
        if cfg.TOGGLE_RECORDING_BTN.startswith("web/w"):
            V.add(Lambda(lambda: recording_control.toggle_recording()), run_condition=cfg.TOGGLE_RECORDING_BTN)
        elif have_joystick:
            ctr.set_button_down_trigger(cfg.TOGGLE_RECORDING_BTN, recording_control.toggle_recording)

    # Buttons to tune PID constants
    if cfg.DEC_PID_P_BTN and cfg.PID_P_DELTA:
        print(f"Decrement PID P button is {cfg.DEC_PID_P_BTN}")
        if cfg.DEC_PID_P_BTN.startswith("web/w"):
            V.add(Lambda(lambda: dec_pid_p()), run_condition=cfg.DEC_PID_P_BTN)
        elif have_joystick:
            ctr.set_button_down_trigger(cfg.DEC_PID_P_BTN, dec_pid_p)
    if cfg.INC_PID_P_BTN and cfg.PID_P_DELTA:
        print(f"Increment PID P button is {cfg.INC_PID_P_BTN}")
        if cfg.INC_PID_P_BTN.startswith("web/w"):
            V.add(Lambda(lambda: inc_pid_p()), run_condition=cfg.INC_PID_P_BTN)
        elif have_joystick:
            ctr.set_button_down_trigger(cfg.INC_PID_P_BTN, inc_pid_p)
    if cfg.DEC_PID_D_BTN and cfg.PID_D_DELTA:
        print(f"Decrement PID D button is {cfg.DEC_PID_D_BTN}")
        if cfg.DEC_PID_D_BTN.startswith("web/w"):
            V.add(Lambda(lambda: dec_pid_d()), run_condition=cfg.DEC_PID_D_BTN)
        elif have_joystick:
            ctr.set_button_down_trigger(cfg.DEC_PID_D_BTN, dec_pid_d)
    if cfg.INC_PID_D_BTN and cfg.PID_D_DELTA:
        print(f"Increment PID D button is {cfg.INC_PID_D_BTN}")
        if cfg.INC_PID_D_BTN.startswith("web/w"):
            V.add(Lambda(lambda: inc_pid_d()), run_condition=cfg.INC_PID_D_BTN)
        elif have_joystick:
            ctr.set_button_down_trigger(cfg.INC_PID_D_BTN, inc_pid_d)

    #
    # Decide what inputs should change the car's steering and throttle
    # based on the choice of user or autopilot drive mode
    #
    V.add(DriveMode(cfg.AI_THROTTLE_MULT),
          inputs=['user/mode', 'user/steering', 'user/throttle',
                  'pilot/steering', 'pilot/throttle'],
          outputs=['steering', 'throttle'])

    # The stock threaded OAK-D part returns its last image if its DepthAI
    # queue blocks. Never let that stale image keep an old motor command alive.
    if camera_watchdog_enabled:
        V.add(
            CameraFrameWatchdog(
                camera_part,
                V,
                timeout_seconds=getattr(
                    cfg, 'CAMERA_FRAME_WATCHDOG_TIMEOUT_SECONDS', 0.5
                ),
                startup_timeout_seconds=getattr(
                    cfg, 'CAMERA_FRAME_WATCHDOG_STARTUP_TIMEOUT_SECONDS', 5.0
                ),
            ),
            inputs=['steering', 'throttle', 'cv/image_array'],
            outputs=['steering', 'throttle', 'cv/image_array'],
        )


    #
    # Setup drivetrain
    #
    add_drivetrain(V, cfg)


    #
    # OLED display setup
    #
    if cfg.USE_SSD1306_128_32:
        from donkeycar.parts.oled import OLEDPart
        auto_record_on_throttle = cfg.USE_JOYSTICK_AS_DEFAULT and cfg.AUTO_RECORD_ON_THROTTLE
        oled_part = OLEDPart(cfg.SSD1306_128_32_I2C_ROTATION, cfg.SSD1306_RESOLUTION, auto_record_on_throttle)
        V.add(oled_part, inputs=['recording', 'tub/num_records', 'user/mode'], outputs=[], threaded=True)


    #
    # add tub to save data
    #
    inputs=['cam/image_array',
            'steering', 'throttle']

    types=['image_array',
           'float', 'float']

    #
    # Create data storage part
    #
    tub_path = TubHandler(path=cfg.DATA_PATH).create_tub_path() if \
        cfg.AUTO_CREATE_NEW_TUB else cfg.DATA_PATH
    meta += getattr(cfg, 'METADATA', [])
    tub_writer = TubWriter(tub_path, inputs=inputs, types=types, metadata=meta)
    V.add(tub_writer, inputs=inputs, outputs=["tub/num_records"], run_condition='recording')

    if cfg.DONKEY_GYM:
        print("You can now go to http://localhost:%d to drive your car." % cfg.WEB_CONTROL_PORT)
    else:
        print("You can now go to <your hostname.local>:%d to drive your car." % cfg.WEB_CONTROL_PORT)
    if has_input_controller:
        print("You can now move your controller to drive your car.")
        if isinstance(ctr, JoystickController):
            ctr.set_tub(tub_writer.tub)
            ctr.print_controls()

    #
    # run the vehicle
    #
    V.start(rate_hz=cfg.DRIVE_LOOP_HZ, 
            max_loop_count=cfg.MAX_LOOPS)


#
# Computer Vision Controller
#
def add_cv_controller(
        V, cfg, pid,
        module_name="donkeycar.parts.line_follower",
        class_name="LineFollower",
        inputs=['cam/image_array'],
        outputs=['pilot/steering', 'pilot/throttle', 'cv/image_array'],
        run_condition="run_pilot"):

        # __import__ the module
        module = __import__(module_name)

        # walk module path to get to module with class
        for attr in module_name.split('.')[1:]:
            module = getattr(module, attr)

        my_class = getattr(module, class_name)
        logger.info(
            "Using CV controller: %s.%s (%s)",
            module_name,
            class_name,
            getattr(module, "__file__", "unknown source"),
        )

        # add instance of class to vehicle
        V.add(my_class(pid, cfg),
              inputs=inputs,
              outputs=outputs,
              run_condition=run_condition)


if __name__ == '__main__':
    args = docopt(__doc__)
    cfg = dk.load_config(myconfig=args['--myconfig'])

    log_level = args['--log'] or "INFO"
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % log_level)
    logging.basicConfig(level=numeric_level)

    if args['drive']:
        drive(cfg, use_joystick=args['--js'], camera_type=args['--camera'])
