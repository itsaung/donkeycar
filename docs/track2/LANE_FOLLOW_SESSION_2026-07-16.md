# Lane Following Session Notes — 2026-07-16

Record of work on the UCSD robocar (Pi: `ucsdrobocar-DSC-T2`) for OpenCV lane following with OAK-D camera and VESC drivetrain.

---

## Goals

1. Run / adapt Donkeycar line following for this car.
2. Build **true lane centering** between:
   - dashed center divider (yellow in real life; often **teal/cyan** on the OAK camera)
   - solid white outer line
3. Support **left lane** (white left + yellow right) and **right lane** (yellow left + white right).
4. Fix “car doesn’t move” issues and add debugging.
5. Calibrate real camera colors and optionally drive + calibrate in one process.

---

## Hardware / stack

| Item | Setting |
|------|---------|
| Car path | `~/mycar` |
| Python env | `~/env` (Donkeycar v5.3.0) |
| Camera | OAK-D (`CAMERA_TYPE = "OAKD"`) |
| Drivetrain | VESC (`DRIVE_TRAIN_TYPE = "VESC"`) |
| Drive UI | port **8887** |
| Live color calib UI | port **8890** |
| Joystick | Logitech F710 (`/dev/input/js0`) |

---

## Files created / modified

### New files

| File | Purpose |
|------|---------|
| [`~/mycar/line_follower.py`](line_follower.py) | Copy of Donkey `cv_control` template (earlier single-color CV drive). **Left untouched** when building lane follow. |
| [`~/mycar/lane_follower_part.py`](lane_follower_part.py) | CV controller part: color HSV dual-line midpoint (default) or grayscale COM. |
| [`~/mycar/lane_follow.py`](lane_follow.py) | Drive entrypoint for lane following + optional live calib. |
| [`~/mycar/calibrate_lane_colors.py`](calibrate_lane_colors.py) | Standalone OAK color sampler (web or GUI). |
| [`~/mycar/lane_calib_live.py`](lane_calib_live.py) | Live calib web server that shares frames with `lane_follow.py`. |

### Config

| File | Changes |
|------|---------|
| [`~/mycar/myconfig.py`](myconfig.py) | Lane-follow block: `CV_CONTROLLER_*`, HSV thresholds, throttle/PID, debug, force-local / joystick / live-calib flags, `AUTO_CREATE_NEW_TUB = True`. |

### Not modified (by design)

- Stock Donkey [`donkeycar/parts/line_follower.py`](../env/lib/python3.11/site-packages/donkeycar/parts/line_follower.py) (inspiration only).
- [`manage.py`](manage.py) neural-net drive path.

---

## How to run

```bash
source ~/env/bin/activate
cd ~/mycar
python lane_follow.py drive
```

| UI | URL |
|----|-----|
| Drive | http://ucsdrobocar-DSC-T2.local:8887 |
| Live color calib (if `LANE_CALIB_LIVE = True`) | http://ucsdrobocar-DSC-T2.local:8890 |

Logs: `~/mycar/logs/lane_follow.log`  
Calib saves: `~/mycar/logs/lane_color_calib/`

Standalone calibrator (camera exclusive — stop drive first):

```bash
python calibrate_lane_colors.py --web
```

---

## Chronology of problems & fixes

### 1. Typo / wrong entrypoint
- Asked for `line_followwe.py` → used Donkey `line_follower` via `cv_control`-style app.

### 2. VESC missing
- Error: serial path not found.
- Fix: plug in VESC USB (`/dev/serial/by-id/usb-STMicroelectronics_...`).

### 3. Tub schema mismatch
- CV app writes `steering`/`throttle`; old tub had `user/angle`/`user/throttle`/`user/mode`.
- Fix: `AUTO_CREATE_NEW_TUB = True`.

### 4. Car doesn’t move (mode / joystick)
- **Cause:** Joystick kept rewriting mode to `user`, so pilot throttle never reached VESC. Also `LANE_FOLLOW` only ran under `run_pilot` at first.
- **Fixes:**
  - Controller always runs (logs/overlay even in User).
  - `LANE_FOLLOW_FORCE_LOCAL` (when not calibrating).
  - Disable joystick unless needed / enable for calib.
  - Raised `THROTTLE_MIN`/`MAX` (VESC duty = throttle × `VESC_MAX_SPEED_PERCENT` ≈ 0.2).
  - `DriveDebugLogger` logs `mode` + final throttle.

### 5. Color vs grayscale experiments
- Single yellow HSV failed (camera shifts yellow → teal).
- Dual-line color follower → grain/asphalt noise.
- Grayscale + Canny/threshold + COM tried; not great on this night track.
- Aggressive blob filters made it worse → **reverted**.
- Settled on **calibrated HSV color mode** + live sampling.

### 6. Color calibration findings (from live OAK samples)
- Dashed “yellow” on camera: **H ≈ 87–95 (teal/cyan)**, not classic yellow.
- Some “white” clicks were dark pavement (gray ≈ 85) — must discard.
- Cleaned ranges applied in `myconfig.py` (see below).

---

## Current algorithm (`LANE_DETECT_MODE = "color"`)

```text
camera RGB frame
  → horizontal scan band (SCAN_Y, SCAN_HEIGHT; scaled if image ≠ IMAGE_H)
  → HSV inRange for teal/yellow divider + white edge
  → white = white AND NOT yellow
  → light morph open/close
  → peak x for yellow; left/right white peaks
  → LANE_SIDE picks edges:
       left  → left=whiteL, right=yellow
       right → left=yellow, right=whiteR
  → lane_center = midpoint (or single-edge fallback)
  → PID vs TARGET_PIXEL (image center)
  → throttle step when off-center
```

Overlay: amber = yellow/teal, cyan = white, green = center, dashed white = target.

---

## Important `myconfig.py` knobs (as of end of day)

```python
CV_CONTROLLER_MODULE = "lane_follower_part"
CV_CONTROLLER_CLASS = "LaneFollower"
LANE_SIDE = "left"
LANE_DETECT_MODE = "color"

# Cleaned OAK calibration (teal dashes + bright white)
YELLOW_THRESHOLD_LOW = (80, 50, 100)
YELLOW_THRESHOLD_HIGH = (105, 220, 210)
WHITE_THRESHOLD_LOW = (50, 0, 150)
WHITE_THRESHOLD_HIGH = (110, 40, 220)

SCAN_Y = 70
SCAN_HEIGHT = 28

THROTTLE_MIN = 0.25
THROTTLE_MAX = 0.45
PID_P = -0.01
PID_D = -0.0001

LANE_FOLLOW_DEBUG = True
LANE_FOLLOW_LOG_PATH = "/home/pi/mycar/logs/lane_follow.log"

# Pure autopilot: True. Drive+calib: live calib forces this off.
LANE_FOLLOW_FORCE_LOCAL = True
LANE_FOLLOW_USE_JOYSTICK = False

LANE_CALIB_LIVE = True
LANE_CALIB_PORT = 8890

AUTO_CREATE_NEW_TUB = True
```

---

## Recommended workflow (troubleshoot detection first)

1. Start `python lane_follow.py drive`.
2. Open **8887** → **User** mode → drive slowly to a clear left-lane view.
3. Open **8890** → sample yellow dashes, then solid white (avoid asphalt).
4. **Apply live** → check Donkey overlay (amber/cyan/green).
5. **Save** report under `logs/lane_color_calib/`.
6. Switch to **Local** for a short autopilot test.
7. Only then tune `PID_P` / throttle.

When finished calibrating, set `LANE_CALIB_LIVE = False` for cleaner autopilot-only runs (and optionally `LANE_FOLLOW_FORCE_LOCAL = True`).

---

## Troubleshooting checklist

| Symptom | Likely cause |
|---------|----------------|
| No motion, log shows `mode='user'` | Need Local mode (or force-local); joystick may reset mode |
| Pilot throttle ~0.25 but no roll | Check VESC cable; duty = throttle × 0.2 may still be low |
| Tub `AssertionError` on inputs | `AUTO_CREATE_NEW_TUB = True` or new data folder |
| Camera “No DepthAI device” | Camera in use by another process; unplug/replug |
| Amber/cyan on asphalt grain | Retighten HSV; re-sample only tape; adjust `SCAN_Y` |
| `no_center` / `no edges` in log | HSV miss or scan band wrong height |
| `dual_center` but bad steering | Fix mask first; then PID |

Watch log:

```bash
tail -f ~/mycar/logs/lane_follow.log
```

Look for `dual_center` with sensible `L=` / `R=` values and `DRIVE mode='local' ... throttle=0.25+`.

---

## Ideas tried / deferred

- **Blob area filters** to kill grain — too aggressive; removed.
- **Pure grayscale COM** — weak vs night glare / multiple bright edges.
- Auto `LANE_SIDE` switching — not implemented.
- Bird’s-eye / polynomial lane fit — out of scope for today.
- Editing stock `line_follower.py` — avoided; local files only.

---

## Next steps (suggested)

1. Finish multi-spot live HSV sampling (bright / shadow / near buildings).
2. Paste final HSV into `myconfig.py` permanently; turn `LANE_CALIB_LIVE = False`.
3. Tune `SCAN_Y` so the band cuts through both lines.
4. Short Local runs; adjust `PID_P` then `PID_D`.
5. Optionally add “save mask PNG every N frames” for offline mask review.

---

## Quick command cheat sheet

```bash
# Activate + drive (with live calib if enabled in myconfig)
source ~/env/bin/activate && cd ~/mycar && python lane_follow.py drive

# Standalone color calib only
python calibrate_lane_colors.py --web

# Snapshot one frame
python calibrate_lane_colors.py --snapshot

# Follow decision + drive logs
tail -f ~/mycar/logs/lane_follow.log
```

---

*Generated for session records — 2026-07-16.*
