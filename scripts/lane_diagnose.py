"""Offline lane-detection diagnostician.

Replays recorded tub images through the exact LaneFollower pipeline and
explains, frame by frame:
  * whether each color mask looks like a SOLID line, a DASHED line, or noise
  * at which stage detection failed (HSV color -> blob filters -> curve fit
    -> lane geometry)
  * a summary with the dominant failure stage and the config knob to fix it

Usage:
    python lane_diagnose.py --tub data_lane_follow_v2/tub_9_26-07-17
    python lane_diagnose.py --tub <tub> --out diag_out --save-every 20

Annotated frames land in --out (failures always saved), plus diagnosis.csv.
"""
import argparse
import csv
import glob
import os
import re

import cv2
import numpy as np
import donkeycar as dk
from simple_pid import PID

from lane_follower_part import LaneFollower

STAGE_FIXES = {
    "no_color_pixels": (
        "HSV thresholds match nothing. Re-check YELLOW/WHITE_THRESHOLD_* "
        "against these frames (lighting changed since calibration)."
    ),
    "blobs_rejected": (
        "Color pixels exist but every blob was filtered out. Loosen "
        "LANE_V2_MIN_BLOB_AREA / LANE_V2_MIN_BLOB_HEIGHT / "
        "LANE_V2_MAX_BLOB_ASPECT / LANE_V2_MAX_BLOB_WIDTH_FRAC."
    ),
    "fit_failed": (
        "Blobs pass but no curve fits them (too scattered or too short). "
        "Loosen LANE_V2_MIN_FIT_PIXELS / LANE_V2_MIN_FIT_Y_SPAN or raise "
        "LANE_V2_RANSAC_THRESHOLD_PX."
    ),
    "geometry_rejected": (
        "Boundaries were fitted but the lane-width/position sanity check "
        "rejected them. Tune LANE_V2_EXPECTED_LANE_WIDTH_PX / "
        "LANE_V2_LANE_WIDTH_TOLERANCE."
    ),
    "ok": "Detection healthy.",
}


def frame_paths(tub_dir):
    paths = glob.glob(os.path.join(tub_dir, "images", "*.jpg"))
    if not paths:
        paths = glob.glob(os.path.join(tub_dir, "*.jpg"))

    def index(path):
        match = re.match(r"(\d+)", os.path.basename(path))
        return int(match.group(1)) if match else 0

    return sorted(paths, key=index)


def structure_of(components, roi_h):
    """Classify a color mask's accepted blobs as solid / dashed / fragment."""
    if not components:
        return "none", 0.0
    rows = np.zeros(roi_h, dtype=bool)
    for component in components:
        _, y, _, h = component["box"]
        rows[max(0, y):min(roi_h, y + h)] = True
    coverage = float(rows.mean())
    blobs = len(components)
    if blobs == 1 and coverage >= 0.60:
        return "solid", coverage
    if blobs >= 2 and coverage >= 0.25:
        return "dashed", coverage
    if coverage >= 0.60:
        return "solid", coverage
    return "fragment", coverage


def color_stage(follower, mask, roi_h):
    """Rerun the per-color pipeline stages to find where detection dies."""
    pixels = int(cv2.countNonZero(mask))
    min_pixels = follower.min_blob_area * follower._area_scale
    if pixels < min_pixels:
        return "no_color_pixels", [], None
    labels, accepted, _ = follower._components(mask)
    if not accepted:
        return "blobs_rejected", [], None
    fit = follower._fit_boundary(labels, accepted, roi_h)
    if fit is None:
        return "fit_failed", accepted, None
    return "ok", accepted, fit


def diagnose_frame(follower, image):
    steering, throttle, _ = follower.run(image)
    d = follower._dbg
    state = d.get("state", "?")
    if "blue_mask" not in d:
        return dict(state=state, steering=steering, throttle=throttle)

    roi_h = d["roi_shape"][0]
    blue_stage, blue_comps, blue_fit = color_stage(follower, d["blue_mask"], roi_h)
    white_stage, white_comps, white_fit = color_stage(follower, d["white_mask"], roi_h)
    blue_structure, blue_cov = structure_of(blue_comps, roi_h)
    white_structure, white_cov = structure_of(white_comps, roi_h)

    if state in ("dual", "single_inferred"):
        overall = "ok"
    elif blue_fit is not None or white_fit is not None:
        overall = "geometry_rejected"
    else:
        # report the color that got furthest through the pipeline
        order = ("ok", "fit_failed", "blobs_rejected", "no_color_pixels")
        overall = min((blue_stage, white_stage), key=order.index)

    return dict(
        state=state, steering=steering, throttle=throttle,
        confidence=d.get("confidence", 0.0), overall=overall,
        blue_stage=blue_stage, blue_structure=blue_structure,
        blue_coverage=round(blue_cov, 2), blue_blobs=len(blue_comps),
        white_stage=white_stage, white_structure=white_structure,
        white_coverage=round(white_cov, 2), white_blobs=len(white_comps),
    )


def annotate(follower, image, info):
    out = follower.overlay_display(image)
    lines = (
        f"DIAG {info['overall']}",
        f"blue(dashed?): {info['blue_structure']} blobs={info['blue_blobs']} "
        f"cov={info['blue_coverage']} [{info['blue_stage']}]",
        f"white(solid?): {info['white_structure']} blobs={info['white_blobs']} "
        f"cov={info['white_coverage']} [{info['white_stage']}]",
    )
    y = out.shape[0] - 12 - 18 * len(lines)
    for line in lines:
        cv2.putText(out, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 255, 255), 1, cv2.LINE_AA)
        y += 18
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tub", required=True, help="tub dir with images/")
    parser.add_argument("--out", default="diag_out")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--save-every", type=int, default=25,
                        help="also save every Nth healthy frame")
    args = parser.parse_args()

    cfg = dk.load_config(myconfig="myconfig.py")
    follower = LaneFollower(PID(cfg.PID_P, cfg.PID_I, cfg.PID_D), cfg)
    follower.csv_enabled = False
    follower.debug_enabled = False

    paths = frame_paths(args.tub)
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        raise SystemExit(f"No images found in {args.tub}")
    os.makedirs(args.out, exist_ok=True)

    stage_counts = {}
    structure_counts = {"blue": {}, "white": {}}
    rows = []
    for i, path in enumerate(paths):
        bgr = cv2.imread(path)
        if bgr is None:
            continue
        image = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        info = diagnose_frame(follower, image)
        info["frame"] = os.path.basename(path)
        rows.append(info)
        overall = info.get("overall", "?")
        stage_counts[overall] = stage_counts.get(overall, 0) + 1
        for color in ("blue", "white"):
            key = info.get(f"{color}_structure", "?")
            structure_counts[color][key] = structure_counts[color].get(key, 0) + 1

        failed = overall != "ok"
        if failed or (args.save_every and i % args.save_every == 0):
            tag = "FAIL" if failed else "ok"
            out_img = annotate(follower, image, info)
            name = f"{i:05d}_{tag}_{overall}.jpg"
            cv2.imwrite(os.path.join(args.out, name),
                        cv2.cvtColor(out_img, cv2.COLOR_RGB2BGR))

    report_path = os.path.join(args.out, "diagnosis.csv")
    with open(report_path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    print(f"\n=== Lane diagnosis: {total} frames from {args.tub} ===")
    print("\nDetection outcome:")
    for stage, count in sorted(stage_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {stage:20s} {count:5d}  ({100.0 * count / total:.1f}%)")
    for color, label in (("blue", "dashed divider"), ("white", "solid edge")):
        print(f"\n{label} ({color} mask) looked like:")
        for kind, count in sorted(structure_counts[color].items(),
                                  key=lambda kv: -kv[1]):
            print(f"  {kind:10s} {count:5d}  ({100.0 * count / total:.1f}%)")

    worst = max(
        (s for s in stage_counts if s != "ok"),
        key=lambda s: stage_counts[s], default=None,
    )
    print("\nRecommendation:")
    if worst is None:
        print("  " + STAGE_FIXES["ok"])
    else:
        print(f"  Dominant failure: {worst} "
              f"({stage_counts[worst]} frames)")
        print("  " + STAGE_FIXES[worst])
    print(f"\nPer-frame details: {report_path}")
    print(f"Annotated frames:  {args.out}/")


if __name__ == "__main__":
    main()
