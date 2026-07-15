# LOK

Local tool to load DonkeyCar tubs, preview real pipeline transforms/augs,
curate frames, and draw masks — exporting **config + sidecars only**.
The opened tub is never written (no soft-delete, no JPEG overwrites).

## Apply to myconfig.py (one click)

Every tab's export panel has an **Apply to myconfig.py** button: enter your
`myconfig.py` path once (remembered per browser) and the backend patches it
in place — no copy-paste needed. It is safe by design:

- **Line-based patching**, never a full rewrite: only matching keys are
  touched, so throttle/steering calibration and everything else survives.
- Handles `KEY=1`, `KEY = 1`, and commented templates (`# KEY = 1` gets
  un-commented in place). If a key has multiple active assignments, the
  **last** one is patched (the one Python honors). Missing keys are appended
  under `# --- LOK: added settings ---`.
- Values keep their Python types (`ROI_CROP_TOP = 40`, not `"40"`); trailing
  comments on simple lines are preserved.
- Multi-line exports (curation's `TRAIN_FILTER` glue) live in a sentinel
  block that is replaced wholesale each apply, so it never duplicates.
- A `myconfig.py.bak` backup is written first, and the write is atomic
  (temp file + rename), so a crash mid-write cannot corrupt the config.

## Tabs

| Tab | Uses | Export |
|-----|------|--------|
| Augment | `ImageAugmentation` / `AUGMENTATIONS` | `AUG_*` + train `p` comment |
| Crop / ROI | `ImageTransformations` CROP/TRAPEZE | `TRANSFORMATIONS` + `ROI_*` |
| Curate | keep/exclude grid | `TRAIN_FILTER` + external JSON |
| Mask | draw block-out regions | `REGION_MASK` + `MASK_METADATA_PATH` |
| Debug / Edges | preview original → preprocess → edges | `CV_DEBUG_TRANSFORMATIONS` + Canny/blur settings |

Use the header **Target** selector to choose the export profile:

- **CV Control** writes `CV_PREPROCESS`, `CV_DEBUG_TRANSFORMATIONS`,
  `CANNY_*`, `BLUR_*`, and `CV_SHOW_DEBUG_PIPELINE`.
- **Training / Complete** keeps the existing `TRANSFORMATIONS` /
  `POST_TRANSFORMATIONS` export.

LOK remembers the `myconfig.py` path and imports supported CV/ROI settings
when it opens. The **Import** button reloads them on demand. Import parses
literal assignments without executing the config file.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
```

## Run

```bash
./scripts/run_backend.sh    # :8765
./scripts/run_frontend.sh   # :5173
```

Sample tub:

```bash
mkdir -p /tmp/dc_tub_inspect
tar -xzf ../../donkeycar/tests/tub/tub.tar.gz -C /tmp/dc_tub_inspect
# Open /tmp/dc_tub_inspect/tub
```

Default sidecars (outside tub): `/tmp/lok_excludes.json`, `/tmp/lok_masks.json`.

## Tub replay

The **Replay** tab compares recorded steering/throttle with a trained pilot
without driving again. Configure the dropdowns before starting LOK:

- `config/replay_models.json`: model ID/label, artifact path, DonkeyCar model
  type, and the matching `config.py` / `myconfig.py`.
- `config/tubs.json`: tub ID/label/path and a `train` or `holdout` tag.

Replay uses the same `apply_pipeline()` path as LOK previews, with
augmentations disabled, and caches predictions under `cache/`. The cache key
changes when the tub manifest, model artifact, or config files change.

Replay also has a **CV controller** mode. It runs the currently opened tub
through the controller configured by `CV_CONTROLLER_MODULE` /
`CV_CONTROLLER_CLASS` in `myconfig.py` (for example `LineFollower`) and plots
recorded versus controller steering on the same error timeline. CV replay is
run directly and is not stored in the trained-model prediction cache.

The API can be checked directly:

```bash
curl http://127.0.0.1:8765/api/replay/options
curl "http://127.0.0.1:8765/api/replay/<tub-id>?model=<model-id>"
```

Run the focused backend tests with:

```bash
PYTHONPATH="backend:../.." .venv/bin/python -m pytest backend/tests/test_replay.py -q
```
