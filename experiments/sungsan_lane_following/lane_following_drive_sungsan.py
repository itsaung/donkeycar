#!/usr/bin/env python3
"""
Drive on autopilot in either lane (yellow dashed + white solid).

Usage:
    lane_following_drive_sungsan.py (drive) [--js] [--log=INFO] [--camera=(single|stereo)] [--myconfig=<filename>] [--lane=<side>]

Options:
    -h --help          Show this screen.
    --js               Use physical joystick.
    --myconfig=filename     Specify myconfig file to use.
                            [default: myconfig_lane_following_sungsan.py]
    --lane=side         Select left or right lane. Overrides LANE_SIDE.
"""
import logging

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


def drive(cfg, use_joystick=False, camera_type='single', meta=None):
    '''
    Construct a working robotic vehicle from many parts.
    Uses CV_CONTROLLER_MODULE/CLASS from config (lane_follower_part.LaneFollower).
    '''
    V = dk.vehicle.Vehicle()
    meta = list(meta or [])

    add_simulator(V, cfg)
    add_camera(V, cfg, camera_type)

    has_input_controller = hasattr(cfg, "CONTROLLER_TYPE") and cfg.CONTROLLER_TYPE != "mock"
    ctr = add_user_controller(V, cfg, use_joystick, input_image='ui/image_array')

    V.add(ExplodeDict(V.mem, "web/"), inputs=['web/buttons'])

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

    add_cv_controller(
        V, cfg, pid,
        cfg.CV_CONTROLLER_MODULE,
        cfg.CV_CONTROLLER_CLASS,
        cfg.CV_CONTROLLER_INPUTS,
        cfg.CV_CONTROLLER_OUTPUTS,
        cfg.CV_CONTROLLER_CONDITION,
    )

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

    add_drivetrain(V, cfg)

    if cfg.USE_SSD1306_128_32:
        from donkeycar.parts.oled import OLEDPart
        auto_record_on_throttle = cfg.USE_JOYSTICK_AS_DEFAULT and cfg.AUTO_RECORD_ON_THROTTLE
        oled_part = OLEDPart(cfg.SSD1306_128_32_I2C_ROTATION, cfg.SSD1306_RESOLUTION, auto_record_on_throttle)
        V.add(oled_part, inputs=['recording', 'tub/num_records', 'user/mode'], outputs=[], threaded=True)

    inputs = ['cam/image_array', 'steering', 'throttle']
    types = ['image_array', 'float', 'float']

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

    print(f"Sungsan lane-follow controller: "
          f"{cfg.CV_CONTROLLER_MODULE}.{cfg.CV_CONTROLLER_CLASS} "
          f"(LANE_SIDE={getattr(cfg, 'LANE_SIDE', 'left')})")

    V.start(rate_hz=cfg.DRIVE_LOOP_HZ,
            max_loop_count=cfg.MAX_LOOPS)


def add_cv_controller(
        V, cfg, pid,
        module_name="lane_follower_part",
        class_name="LaneFollower",
        inputs=['cam/image_array'],
        outputs=['pilot/steering', 'pilot/throttle', 'cv/image_array'],
        run_condition="run_pilot"):

    module = __import__(module_name)
    for attr in module_name.split('.')[1:]:
        module = getattr(module, attr)

    my_class = getattr(module, class_name)
    V.add(my_class(pid, cfg),
          inputs=inputs,
          outputs=outputs,
          run_condition=run_condition)


if __name__ == '__main__':
    args = docopt(__doc__)
    cfg = dk.load_config(myconfig=args['--myconfig'])

    if args['--lane']:
        lane_side = args['--lane'].lower()
        if lane_side not in {'left', 'right'}:
            raise ValueError("--lane must be 'left' or 'right'")
        cfg.LANE_SIDE = lane_side

    log_level = args['--log'] or "INFO"
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % log_level)
    logging.basicConfig(level=numeric_level)

    if args['drive']:
        drive(cfg, use_joystick=args['--js'], camera_type=args['--camera'])
