#!/usr/bin/env python3
"""Replay recorded OAK-D frames through the isolated lane controller."""

import argparse
import glob
import json
import os
import runpy
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image
from simple_pid import PID

from lane_following_controller_sungsan import LaneFollower


def numeric_index(path):
    try:
        return int(os.path.basename(path).split("_", 1)[0])
    except ValueError:
        return 0


def load_config(path, lane):
    values = {
        key: value
        for key, value in runpy.run_path(path).items()
        if key.isupper()
    }
    values["LANE_SIDE"] = lane
    values["OVERLAY_IMAGE"] = False
    return SimpleNamespace(**values)


def load_frame(path, stored_oak_frame):
    if stored_oak_frame:
        # Tub JPEGs from this OAK-D setup were written from the live BGR array.
        # PIL preserves the stored channel values, reconstructing that live array.
        return np.asarray(Image.open(path).convert("RGB"))
    frame = cv2.imread(path)
    if frame is None:
        raise ValueError(f"could not read image: {path}")
    return frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image_dir")
    parser.add_argument("--lane", choices=("left", "right"), required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument(
        "--standard-jpeg",
        action="store_true",
        help="Use for normal photos; omit for this car's stored OAK-D Tub frames.",
    )
    parser.add_argument("--min-valid-rate", type=float, default=0.80)
    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    cfg = load_config(
        str(here / "myconfig_lane_following_sungsan.py"), args.lane
    )
    follower = LaneFollower(PID(cfg.PID_P, cfg.PID_I, cfg.PID_D), cfg)

    files = sorted(
        glob.glob(os.path.join(args.image_dir, "*_cam_image_array_*.jpg")),
        key=numeric_index,
    )
    files = files[args.start:args.start + args.count]
    if not files:
        raise SystemExit("no matching OAK-D frames found")

    valid = paired = safe_stops = 0
    for path in files:
        frame = load_frame(path, not args.standard_jpeg)
        _, throttle, _ = follower.run(frame)
        debug = follower._debug
        valid += debug["center"] is not None
        paired += any(item.paired for item in debug["observations"])
        safe_stops += throttle == 0.0

    result = {
        "lane": args.lane,
        "frames": len(files),
        "valid_frames": valid,
        "valid_rate": round(valid / len(files), 4),
        "paired_boundary_frames": paired,
        "safe_stop_frames": safe_stops,
    }
    print(json.dumps(result, indent=2))
    if result["valid_rate"] < args.min_valid_rate:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
