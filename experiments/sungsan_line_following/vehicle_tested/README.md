# Vehicle-Tested Line Following — Final Working Snapshot

This directory contains the isolated line-following files that completed the
physical Team 2 DonkeyCar track successfully on July 24, 2026.

It is intentionally separate from all `lane_following_*` work. Lane-following
development must not modify these files.

## Files

- `config.py` — frozen base car configuration
- `line_following_drive_sungsan.py` — isolated vehicle launcher
- `line_following_controller_sungsan.py` — yellow dashed-line CV controller
- `myconfig_line_following_sungsan.py` — final vehicle-tested overrides
- `RUN_LINE_FOLLOWING.sh` — launcher for the frozen Raspberry Pi snapshot
- `SHA256.txt` — checksums for the exact working files

## Raspberry Pi location and run command

The frozen Raspberry Pi copy is stored at:

```text
/home/sungsan/mycar/line_following_working
```

Run it with:

```bash
ssh sungsan@ucsdrobocar-DSC-T2.local
cd /home/sungsan/mycar/line_following_working
./RUN_LINE_FOLLOWING.sh
```

The script changes into the frozen directory before starting, ensuring that
its own `config.py`, controller, and personal configuration are used.

## Final behavior

- OAK-D input resolution fixed at `426x260`
- follows the yellow dashed center line
- tracks and reacquires far-right tape on sharp curves
- rejects broad yellow-brown pavement under artificial light
- rejects candidates with implausible color, width, shape, or motion
- requires consistent frames before starting after a complete loss
- immediately clears stale steering and throttle when no valid line exists
- applies a short launch boost, then maintains enough curve throttle to keep
  the physical drivetrain moving

## Important separation rule

Keep this directory unchanged. New lane-following code must use names such as:

```text
lane_following_drive_sungsan.py
lane_following_controller_sungsan.py
myconfig_lane_following_sungsan.py
```

Do not rename, overwrite, import, or edit the frozen `line_following_*` files
while developing lane following.
