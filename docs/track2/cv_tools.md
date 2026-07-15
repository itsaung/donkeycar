# Track 2 Phase 0: CV Tools (Canny, Crop, Masks)

This guide explains DonkeyCar’s computer-vision building blocks used before lane following and two-way road navigation. Tools live in `donkeycar/parts/cv.py` and are composed via `donkeycar/parts/image_transformations.py`.

## Why these tools matter

| Tool | Job |
|------|-----|
| **CROP** | Hide sky / hood / dashboard with a rectangular border mask |
| **TRAPEZE** / **TRAPEZE_EDGE** | Keep a road-shaped region (bird’s-eye-ish ROI) |
| **CANNY** | Turn the image into edges — lane lines become bright contours |
| **BLUR** | Smooth noise before Canny so edges are cleaner |

`LineFollower` (yellow tape) still needs **color**. Put only RGB-safe masks (`CROP`, `TRAPEZE`, `TRAPEZE_EDGE`) in preprocess. Use **Canny in the debug pipeline** (and later in `LaneFollower`), not as input to `LineFollower`.

## Pipeline in `cv_control`

```
cam/image_array
    → CV_PREPROCESS (optional CROP / TRAPEZE) → cv/preprocessed
    → LineFollower → pilot/steering, pilot/throttle, cv/image_array (overlay)
    → CV_DEBUG_TRANSFORMATIONS (gray → blur → Canny) → cv/debug_image
    → CvUiImage → cv/display_image → web UI
```

## Config knobs (`myconfig.py` / `cfg_cv_control.py`)

```python
# RGB-safe masks before LineFollower (recommended for Track 2)
CV_PREPROCESS = ['CROP']                 # or ['TRAPEZE_EDGE']

# Live edge preview in the web UI
CV_DEBUG_TRANSFORMATIONS = ['RGB2GRAY', 'BLUR', 'CANNY']
CV_SHOW_DEBUG_PIPELINE = True            # set False once tuned

ROI_CROP_TOP = 45
ROI_CROP_BOTTOM = 0
ROI_CROP_LEFT = 0
ROI_CROP_RIGHT = 0

ROI_TRAPEZE_UL = 20
ROI_TRAPEZE_UR = 140
ROI_TRAPEZE_LL = 0
ROI_TRAPEZE_LR = 160
ROI_TRAPEZE_MIN_Y = 60
ROI_TRAPEZE_MAX_Y = 120

CANNY_LOW_THRESHOLD = 60
CANNY_HIGH_THRESHOLD = 110
CANNY_APERTURE = 3

BLUR_KERNEL = 5
BLUR_GAUSSIAN = True
```

### CROP vs TRAPEZE (ASCII)

**CROP** — zero out rectangular borders:

```
#####################
#xxxxxxxxxxxxxxxxxxx#  ← top
#xx               xx#
#xx   keep this   xx#
#xx               xx#
#xxxxxxxxxxxxxxxxxxx#  ← bottom
#####################
```

**TRAPEZE / TRAPEZE_EDGE** — keep a road wedge:

```
#######################
#xxxxxxxxxxxxxxxxxxxxx#
#xxxx ul     ur xxxxxx#  ← min_y
#xxx             xxxxx#
#xx               xxxx#
#x                 xxx#
#ll                lr #  ← max_y
#######################
```

`TRAPEZE_EDGE` measures left/right insets from the image edges (scales better when resolution changes). `TRAPEZE` uses absolute X coordinates.

## Offline lab (no car required)

1. Save a camera frame from the web UI (or any JPG/PNG of your course).
2. Run:

```bash
python tools/cv_pipeline_lab.py --image frame.jpg --out /tmp/cv_lab \
  --preprocess CROP,TRAPEZE_EDGE --debug RGB2GRAY,BLUR,CANNY
```

3. Inspect `/tmp/cv_lab/`:
   - `00_original.jpg`
   - step images for each transform
   - `compare_original_vs_debug.jpg` — original vs final edges
4. Adjust `--canny-low`, `--canny-high`, `--crop-top`, etc., until lane edges look clean.
5. Copy the winning values into `myconfig.py`.

## Live preview on the car

1. Set `CV_SHOW_DEBUG_PIPELINE = True` and start `manage.py drive` (cv_control template).
2. Switch to autopilot mode so the pilot image is shown (`OVERLAY_IMAGE = True`).
3. Confirm edges/masks look right in the browser.
4. Set `CV_SHOW_DEBUG_PIPELINE = False` for normal LineFollower overlay.
5. Keep `CV_PREPROCESS = ['CROP']` or `['TRAPEZE_EDGE']` while driving.

## Tuning order (what to turn first)

1. **CROP top** — remove sky / distant clutter  
2. **TRAPEZE** points — keep asphalt, drop left/right walls if needed  
3. **BLUR kernel** — if Canny is speckled, increase slightly  
4. **CANNY low/high** — lower = more edges (noisier); higher = fewer (may miss lines)

## How this feeds the rest of Track 2

| Phase | Uses these tools how |
|-------|----------------------|
| 0 (this doc) | See and tune masks + Canny |
| 1 Line follow | `CV_PREPROCESS` + existing `LineFollower` |
| 2 Lane follow | Preprocess + Canny (or edges) → left/right line → PID on center |
| 3 Two-way road | Lane center + oncoming detection / throttle cut |

## Agent API note

With `HAVE_AGENT_API = True`, Claude can pull `robot_camera` / `robot_state` while you iterate on CV knobs. The Agent API does not replace this CV stack — it helps the coding agent *see* what the car sees.

## Key source files

- `donkeycar/parts/cv.py` — `ImgCanny`, `ImgCropMask`, `ImgTrapezoidalMask`, `ImgTrapezoidalEdgeMask`
- `donkeycar/parts/image_transformations.py` — name → part factory
- `donkeycar/parts/cv_debug.py` — live debug + UI picker
- `donkeycar/templates/cv_control.py` — drive-loop wiring
- `donkeycar/templates/cfg_cv_control.py` — defaults
- `tools/cv_pipeline_lab.py` — offline tuner
