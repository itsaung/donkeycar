#!/usr/bin/env python3
"""
Drive on autopilot using LaneFollower v2 lane geometry estimation.

Usage:
    lane_follow.py (drive) [--js] [--log=INFO] [--camera=(single|stereo)] [--myconfig=<filename>]

Options:
    -h --help          Show this screen.
    --js               Use physical joystick.
    --myconfig=filename     Specify myconfig file to use.
                            [default: myconfig.py]
"""
import logging
import os

from docopt import docopt
from simple_pid import PID

import donkeycar as dk
from donkeycar.parts.tub_v2 import TubWriter
from donkeycar.parts.datastore import TubHandler
from donkeycar.templates.complete import add_camera, \
    add_user_controller, add_drivetrain, add_simulator, DriveMode, \
    UserPilotCondition, ToggleRecording
from donkeycar.parts.transform import Lambda
from donkeycar.parts.explode import ExplodeDict
from donkeycar.parts.controller import JoystickController

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class ForceMode:
    """Write mode after joystick/web so they cannot silently keep User mode."""

    def __init__(self, mode='local'):
        self.mode = mode

    def run(self):
        return self.mode


class DriveDebugLogger:
    """Log mode + final motor commands (proves whether VESC should be moving)."""

    def __init__(self, every_n=10, log_path=None):
        self.every_n = max(1, int(every_n))
        self.i = 0
        self.log_path = log_path

    def run(self, mode, user_th, pilot_th, steering, throttle):
        self.i += 1
        if (self.i % self.every_n) != 0:
            return
        msg = (
            "DRIVE mode=%r user_th=%s pilot_th=%s -> steering=%.3f throttle=%.3f "
            "(vesc_duty≈throttle*VESC_MAX_SPEED_PERCENT)"
            % (mode, user_th, pilot_th, float(steering or 0), float(throttle or 0))
        )
        logger.info(msg)
        if self.log_path:
            try:
                with open(self.log_path, 'a', encoding='utf-8') as f:
                    f.write(msg + '\n')
            except OSError:
                pass


def drive(cfg, use_joystick=False, camera_type='single', meta=[]):
    '''
    Construct a working robotic vehicle from many parts.
    Uses CV_CONTROLLER_MODULE/CLASS from config (lane_follower_part.LaneFollower).
    '''
    V = dk.vehicle.Vehicle()

    add_simulator(V, cfg)
    add_camera(V, cfg, camera_type)

    calib_live = bool(getattr(cfg, 'LANE_CALIB_LIVE', False))
    # While calibrating, prefer manual User-mode driving (joystick/web).
    force_local = bool(getattr(cfg, 'LANE_FOLLOW_FORCE_LOCAL', True)) and not calib_live

    has_input_controller = hasattr(cfg, "CONTROLLER_TYPE") and cfg.CONTROLLER_TYPE != "mock"
    saved_js_default = cfg.USE_JOYSTICK_AS_DEFAULT
    want_js = bool(use_joystick) or bool(getattr(cfg, 'LANE_FOLLOW_USE_JOYSTICK', False)) or calib_live
    cfg.USE_JOYSTICK_AS_DEFAULT = want_js
    ctr = add_user_controller(V, cfg, want_js, input_image='ui/image_array')
    cfg.USE_JOYSTICK_AS_DEFAULT = saved_js_default
    if want_js:
        print("Joystick enabled (manual drive / calibrate)")
    else:
        print("Joystick disabled for lane_follow (avoids mode reset to User)")

    V.add(ExplodeDict(V.mem, "web/"), inputs=['web/buttons'])

    if force_local:
        V.add(ForceMode('local'), outputs=['user/mode'])
        print("LANE_FOLLOW_FORCE_LOCAL=True -> mode forced to 'local' (autopilot)")
    elif calib_live:
        print("LANE_CALIB_LIVE=True -> FORCE_LOCAL off; use User mode to drive, Local to test autopilot")

    V.add(UserPilotCondition(show_pilot_image=getattr(cfg, 'OVERLAY_IMAGE', False)),
          inputs=['user/mode', "cam/image_array", "cv/image_array"],
          outputs=['run_user', "run_pilot", "ui/image_array"])

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

    lane_follower = add_cv_controller(
        V, cfg, pid,
        cfg.CV_CONTROLLER_MODULE,
        cfg.CV_CONTROLLER_CLASS,
        cfg.CV_CONTROLLER_INPUTS,
        cfg.CV_CONTROLLER_OUTPUTS,
        cfg.CV_CONTROLLER_CONDITION,
    )

    if calib_live:
        from lane_calib_live import LiveLaneCalibServer
        calib = LiveLaneCalibServer(cfg, lane_follower=lane_follower)
        V.add(calib, inputs=['cam/image_array'])

    recording_control = ToggleRecording(cfg.AUTO_RECORD_ON_THROTTLE, cfg.RECORD_DURING_AI)
    V.add(recording_control, inputs=['user/mode', "recording"], outputs=["recording"])

    have_joystick = ctr is not None and isinstance(ctr, JoystickController)

    if cfg.TOGGLE_RECORDING_BTN:
        print(f"Toggle recording button is {cfg.TOGGLE_RECORDING_BTN}")
        if cfg.TOGGLE_RECORDING_BTN.startswith("web/w"):
            V.add(Lambda(lambda: recording_control.toggle_recording()), run_condition=cfg.TOGGLE_RECORDING_BTN)
        elif have_joystick:
            ctr.set_button_down_trigger(cfg.TOGGLE_RECORDING_BTN, recording_control.toggle_recording)

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

    V.add(DriveMode(cfg.AI_THROTTLE_MULT),
          inputs=['user/mode', 'user/steering', 'user/throttle',
                  'pilot/steering', 'pilot/throttle'],
          outputs=['steering', 'throttle'])

    V.add(
        DriveDebugLogger(
            every_n=getattr(cfg, 'LANE_FOLLOW_LOG_EVERY_N', 5),
            log_path=getattr(cfg, 'LANE_FOLLOW_LOG_PATH', None),
        ),
        inputs=['user/mode', 'user/throttle', 'pilot/throttle', 'steering', 'throttle'],
    )

    add_drivetrain(V, cfg)

    if cfg.USE_SSD1306_128_32:
        from donkeycar.parts.oled import OLEDPart
        auto_record_on_throttle = cfg.USE_JOYSTICK_AS_DEFAULT and cfg.AUTO_RECORD_ON_THROTTLE
        oled_part = OLEDPart(cfg.SSD1306_128_32_I2C_ROTATION, cfg.SSD1306_RESOLUTION, auto_record_on_throttle)
        V.add(oled_part, inputs=['recording', 'tub/num_records', 'user/mode'], outputs=[], threaded=True)

    inputs = ['cam/image_array', 'steering', 'throttle']
    types = ['image_array', 'float', 'float']

    lane_data_path = os.path.expanduser(
        getattr(cfg, 'LANE_FOLLOW_DATA_PATH', cfg.DATA_PATH)
    )
    os.makedirs(lane_data_path, exist_ok=True)
    tub_path = TubHandler(path=lane_data_path).create_tub_path() if \
        cfg.AUTO_CREATE_NEW_TUB else lane_data_path
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

    print(f"Lane follow controller: {cfg.CV_CONTROLLER_MODULE}.{cfg.CV_CONTROLLER_CLASS}")
    print(
        "LaneFollower v2: ROI=%.2f lookahead=%.2f expected_width=%.1fpx"
        % (
            getattr(cfg, 'LANE_V2_ROI_TOP', 0.45),
            getattr(cfg, 'LANE_V2_LOOKAHEAD', 0.68),
            getattr(cfg, 'LANE_V2_EXPECTED_LANE_WIDTH_PX', 100),
        )
    )
    if getattr(cfg, 'LANE_FOLLOW_DEBUG', True):
        print(f"Lane follow debug log: {getattr(cfg, 'LANE_FOLLOW_LOG_PATH', '~/mycar/logs/lane_follow.log')}")
        print(f"Lane follow CSV: {getattr(cfg, 'LANE_V2_CSV_LOG_PATH', '~/mycar/logs/lane_follow_v2.csv')}")
    print("")
    if force_local:
        print("*** Mode FORCED to Local (autopilot) ***")
    else:
        print("*** User mode = manual drive | Local mode = test autopilot ***")
    if calib_live:
        print(f"*** Color calib UI: http://ucsdrobocar-DSC-T2.local:{getattr(cfg, 'LANE_CALIB_PORT', 8890)}/ ***")
    print("")

    V.start(rate_hz=cfg.DRIVE_LOOP_HZ,
            max_loop_count=cfg.MAX_LOOPS)


def add_cv_controller(
        V, cfg, pid,
        module_name="lane_follower_part",
        class_name="LaneFollower",
        inputs=['cam/image_array'],
        outputs=['pilot/steering', 'pilot/throttle', 'cv/image_array'],
        run_condition=None):

    module = __import__(module_name)
    for attr in module_name.split('.')[1:]:
        module = getattr(module, attr)

    my_class = getattr(module, class_name)
    part = my_class(pid, cfg)
    kwargs = dict(inputs=inputs, outputs=outputs)
    if run_condition:
        kwargs['run_condition'] = run_condition
    V.add(part, **kwargs)
    return part


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
