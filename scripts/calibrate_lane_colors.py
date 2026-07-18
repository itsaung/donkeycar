#!/usr/bin/env python3
"""
Sample real colors from the car camera (OAK-D) to tune lane detection.

Usage:
  source ~/env/bin/activate && cd ~/mycar
  python calibrate_lane_colors.py              # live OAK-D
  python calibrate_lane_colors.py --image path.jpg
  python calibrate_lane_colors.py --snapshot   # grab one frame, save, exit

Controls (OpenCV window):
  1          - sample mode: YELLOW / dashed divider
  2          - sample mode: WHITE / solid edge
  left-click - add HSV sample at cursor (5x5 patch average)
  u          - undo last sample in current mode
  c          - clear samples for current mode
  m          - toggle mask preview (yellow | white | both | off)
  s          - save calibration + suggested myconfig snippet
  q / ESC    - quit

Output:
  ~/mycar/logs/lane_color_calib/
    frame_YYYYMMDD_HHMMSS.jpg
    calib_YYYYMMDD_HHMMSS.txt   (HSV stats + paste-ready myconfig)
"""
from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass, field

import cv2
import numpy as np


CALIB_DIR = os.path.expanduser('~/mycar/logs/lane_color_calib')


@dataclass
class SampleBank:
    name: str
    points_hsv: list = field(default_factory=list)  # list of (H,S,V)
    points_rgb: list = field(default_factory=list)
    points_gray: list = field(default_factory=list)

    def add_patch(self, rgb: np.ndarray, x: int, y: int, radius: int = 2):
        h, w = rgb.shape[:2]
        x0, x1 = max(0, x - radius), min(w, x + radius + 1)
        y0, y1 = max(0, y - radius), min(h, y + radius + 1)
        patch = rgb[y0:y1, x0:x1]
        if patch.size == 0:
            return
        mean_rgb = patch.reshape(-1, 3).mean(axis=0)
        hsv = cv2.cvtColor(np.uint8([[mean_rgb]]), cv2.COLOR_RGB2HSV)[0, 0]
        gray = cv2.cvtColor(np.uint8([[mean_rgb]]), cv2.COLOR_RGB2GRAY)[0, 0]
        self.points_hsv.append(tuple(int(v) for v in hsv))
        self.points_rgb.append(tuple(int(v) for v in mean_rgb))
        self.points_gray.append(int(gray))

    def undo(self):
        if self.points_hsv:
            self.points_hsv.pop()
            self.points_rgb.pop()
            self.points_gray.pop()

    def clear(self):
        self.points_hsv.clear()
        self.points_rgb.clear()
        self.points_gray.clear()

    def hsv_range(self, pad_h=8, pad_s=30, pad_v=30, max_s=None, min_v=None):
        """Build an HSV inRange box around samples.

        max_s: optional cap on high-S (use for WHITE so yellow chroma is excluded)
        min_v: optional floor on low-V
        """
        if not self.points_hsv:
            return None
        arr = np.asarray(self.points_hsv, dtype=np.int32)
        lo = arr.min(axis=0) - np.array([pad_h, pad_s, pad_v])
        hi = arr.max(axis=0) + np.array([pad_h, pad_s, pad_v])
        lo = np.clip(lo, [0, 0, 0], [179, 255, 255])
        hi = np.clip(hi, [0, 0, 0], [179, 255, 255])
        if max_s is not None:
            hi[1] = min(int(hi[1]), int(max_s))
        if min_v is not None:
            lo[2] = max(int(lo[2]), int(min_v))
        hi = np.maximum(hi, lo)
        return tuple(int(x) for x in lo), tuple(int(x) for x in hi)

    def yellow_hsv_range(self):
        # Allow more saturation; yellow/amber/teal shifts from camera WB
        return self.hsv_range(pad_h=10, pad_s=40, pad_v=35)

    def white_hsv_range(self):
        # White = low saturation + high value. Cap S tightly so yellow dashes
        # (higher chroma) are not included in the white mask.
        if not self.points_hsv:
            return None
        arr = np.asarray(self.points_hsv, dtype=np.int32)
        s_hi = int(arr[:, 1].max())
        v_lo = int(arr[:, 2].min())
        # Cap S just above sampled white sat; never open the door to yellow
        max_s = min(80, s_hi + 20)
        min_v = max(140, v_lo - 25)
        return self.hsv_range(pad_h=20, pad_s=10, pad_v=25, max_s=max_s, min_v=min_v)

    def gray_stats(self):
        if not self.points_gray:
            return None
        g = np.asarray(self.points_gray)
        return int(g.min()), int(g.mean()), int(g.max())


class CameraSource:
    def __init__(self, image_path: str | None = None):
        self.image_path = image_path
        self._still = None
        self.oak = None
        if image_path:
            bgr = cv2.imread(image_path)
            if bgr is None:
                raise FileNotFoundError(image_path)
            self._still = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            print(f"Loaded image {image_path} shape={self._still.shape}")
        else:
            from donkeycar.parts.oak_d import OakD
            # Use native-ish resolution for accurate color sampling
            self.oak = OakD(width=640, height=480, enable_rgb=True, enable_depth=False)
            print("Waiting for OAK-D frames...")
            for _ in range(50):
                frame = self.grab()
                if frame is not None:
                    print(f"OAK-D ready shape={frame.shape}")
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("No frames from OAK-D")

    def grab(self):
        if self._still is not None:
            return self._still.copy()
        # OakD.run() polls a fresh frame; returns (rgb_image, depth_image)
        out = self.oak.run()
        if out is None:
            return None
        if isinstance(out, (tuple, list)):
            img = out[0]
        else:
            img = out
        return None if img is None else img

    def close(self):
        if self.oak is not None and hasattr(self.oak, 'shutdown'):
            try:
                self.oak.shutdown()
            except Exception:
                pass


def capture_snapshot(cam: CameraSource, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime('%Y%m%d_%H%M%S')
    path = os.path.join(out_dir, f'frame_{ts}.jpg')
    for _ in range(30):
        rgb = cam.grab()
        if rgb is not None:
            break
        time.sleep(0.05)
    if rgb is None:
        raise RuntimeError('Could not grab frame for snapshot')
    cv2.imwrite(path, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    print(f'Saved snapshot: {path}')
    return path


def format_report(yellow: SampleBank, white: SampleBank) -> str:
    lines = []
    lines.append('# Lane color calibration (from calibrate_lane_colors.py)')
    lines.append(f'# generated {time.strftime("%Y-%m-%d %H:%M:%S")}')
    lines.append('')

    for bank, rng_fn in (
        (yellow, yellow.yellow_hsv_range),
        (white, white.white_hsv_range),
    ):
        lines.append(f'# --- {bank.name} samples: {len(bank.points_hsv)} ---')
        for i, (hsv, rgb, g) in enumerate(zip(bank.points_hsv, bank.points_rgb, bank.points_gray)):
            lines.append(f'#  {i}: HSV={hsv} RGB={rgb} gray={g}')
        rng = rng_fn()
        gstat = bank.gray_stats()
        if rng:
            lines.append(f'#  suggested HSV low..high = {rng[0]} .. {rng[1]}')
        if gstat:
            lines.append(f'#  gray min/mean/max = {gstat[0]}/{gstat[1]}/{gstat[2]}')
        lines.append('')

    y_rng = yellow.yellow_hsv_range()
    w_rng = white.white_hsv_range()
    g_white = white.points_gray
    lines.append('# Paste into myconfig.py:')
    if y_rng:
        lines.append(f'YELLOW_THRESHOLD_LOW = {y_rng[0]}')
        lines.append(f'YELLOW_THRESHOLD_HIGH = {y_rng[1]}')
        lines.append('YELLOW2_THRESHOLD_LOW = (0, 0, 0)')
        lines.append('YELLOW2_THRESHOLD_HIGH = (0, 0, 0)')
    if w_rng:
        lines.append(f'WHITE_THRESHOLD_LOW = {w_rng[0]}')
        lines.append(f'WHITE_THRESHOLD_HIGH = {w_rng[1]}')
    if g_white:
        suggested = max(40, int(min(g_white) - 15))
        lines.append(f'LANE_BINARY_THRESH = {suggested}  # grayscale COM (use white tape brightness)')
    lines.append('LANE_DETECT_MODE = "threshold"')
    return '\n'.join(lines) + '\n'


def yellow_mask(rgb, yellow: SampleBank):
    rng = yellow.yellow_hsv_range()
    if not rng:
        return np.zeros(rgb.shape[:2], dtype=np.uint8)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    return cv2.inRange(hsv, np.array(rng[0]), np.array(rng[1]))


def white_mask(rgb, white: SampleBank, yellow: SampleBank | None = None):
    """White mask with yellow subtracted so dashed line does not light up."""
    rng = white.white_hsv_range()
    if not rng:
        return np.zeros(rgb.shape[:2], dtype=np.uint8)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array(rng[0]), np.array(rng[1]))
    if yellow is not None and yellow.points_hsv:
        ymask = yellow_mask(rgb, yellow)
        mask = cv2.bitwise_and(mask, cv2.bitwise_not(ymask))
    return mask


def make_mask(rgb, yellow: SampleBank, white: SampleBank, mode: str):
    if mode == 'yellow':
        return yellow_mask(rgb, yellow)
    if mode == 'white':
        return white_mask(rgb, white, yellow)
    if mode == 'both':
        return cv2.bitwise_or(yellow_mask(rgb, yellow), white_mask(rgb, white, yellow))
    return np.zeros(rgb.shape[:2], dtype=np.uint8)


def tint_mask(vis_rgb, mask, color_rgb, strength=0.55):
    """Overlay mask with a chosen RGB tint (not always green)."""
    out = vis_rgb.astype(np.float32)
    m = (mask > 0).astype(np.float32)
    for c in range(3):
        out[:, :, c] = np.clip(
            out[:, :, c] * (1 - strength * m) + color_rgb[c] * strength * m, 0, 255
        )
    return out.astype(np.uint8)


def run_interactive(cam: CameraSource):
    os.makedirs(CALIB_DIR, exist_ok=True)
    yellow = SampleBank('YELLOW/dashed')
    white = SampleBank('WHITE/solid')
    mode_name = 'yellow'
    mask_mode = 'both'  # yellow | white | both | off
    mask_cycle = ['both', 'yellow', 'white', 'off']

    win = 'Lane Color Calibrator'
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 960, 720)

    state = {'x': 0, 'y': 0}

    def on_mouse(event, x, y, flags, param):
        state['x'], state['y'] = x, y
        if event == cv2.EVENT_LBUTTONDOWN:
            bank = yellow if mode_name == 'yellow' else white
            # click coords are on displayed image — we draw on a copy of rgb
            bank.add_patch(param['rgb'], x, y)
            print(f"[{bank.name}] + HSV={bank.points_hsv[-1]} RGB={bank.points_rgb[-1]} gray={bank.points_gray[-1]}")

    cv2.setMouseCallback(win, on_mouse)

    print("""
Controls:
  1 = sample YELLOW/dashed   2 = sample WHITE/solid
  left-click = add sample    u = undo   c = clear mode
  m = cycle mask preview     s = save   q = quit
""")

    last_rgb = None
    while True:
        rgb = cam.grab()
        if rgb is None:
            if last_rgb is None:
                time.sleep(0.05)
                continue
            rgb = last_rgb
        else:
            last_rgb = rgb

        # Mouse callback needs current frame for correct sampling
        on_mouse_param = {'rgb': rgb}
        cv2.setMouseCallback(win, on_mouse, on_mouse_param)

        vis = rgb.copy()
        if mask_mode == 'yellow':
            vis = tint_mask(vis, yellow_mask(rgb, yellow), (255, 220, 0))
        elif mask_mode == 'white':
            vis = tint_mask(vis, white_mask(rgb, white, yellow), (0, 200, 255))
        elif mask_mode == 'both':
            vis = tint_mask(vis, yellow_mask(rgb, yellow), (255, 220, 0), 0.5)
            vis = tint_mask(vis, white_mask(rgb, white, yellow), (0, 200, 255), 0.5)

        # crosshair + HUD
        x, y = state['x'], state['y']
        cv2.drawMarker(vis, (x, y), (0, 255, 255), markerType=cv2.MARKER_CROSS, markerSize=12, thickness=1)
        hud = [
            f"MODE: {mode_name.upper()}  mask:{mask_mode}",
            f"yellow samples:{len(yellow.points_hsv)}  white samples:{len(white.points_gray)}",
        ]
        y_rng = yellow.yellow_hsv_range()
        w_rng = white.white_hsv_range()
        if y_rng:
            hud.append(f"Y HSV {y_rng[0]}..{y_rng[1]}")
        if w_rng:
            hud.append(f"W HSV {w_rng[0]}..{w_rng[1]}")
        yy = 18
        for line in hud:
            cv2.putText(vis, line, (8, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2, cv2.LINE_AA)
            cv2.putText(vis, line, (8, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            yy += 18

        bgr = cv2.cvtColor(vis, cv2.COLOR_RGB2BGR)
        cv2.imshow(win, bgr)
        key = cv2.waitKey(30) & 0xFF

        if key in (ord('q'), 27):
            break
        elif key == ord('1'):
            mode_name = 'yellow'
            mask_mode = 'yellow'
            print('Sample mode: YELLOW/dashed (mask preview -> yellow)')
        elif key == ord('2'):
            mode_name = 'white'
            mask_mode = 'white'
            print('Sample mode: WHITE/solid (mask preview -> white only; yellow excluded)')
        elif key == ord('u'):
            bank = yellow if mode_name == 'yellow' else white
            bank.undo()
            print(f'Undo {bank.name}, now {len(bank.points_hsv)} samples')
        elif key == ord('c'):
            bank = yellow if mode_name == 'yellow' else white
            bank.clear()
            print(f'Cleared {bank.name}')
        elif key == ord('m'):
            i = mask_cycle.index(mask_mode)
            mask_mode = mask_cycle[(i + 1) % len(mask_cycle)]
            print(f'Mask preview: {mask_mode}')
        elif key == ord('s'):
            ts = time.strftime('%Y%m%d_%H%M%S')
            frame_path = os.path.join(CALIB_DIR, f'frame_{ts}.jpg')
            report_path = os.path.join(CALIB_DIR, f'calib_{ts}.txt')
            cv2.imwrite(frame_path, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            report = format_report(yellow, white)
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report)
            print('\n===== SAVED =====')
            print(frame_path)
            print(report_path)
            print(report)

    cv2.destroyAllWindows()
    # always write a final report if any samples exist
    if yellow.points_hsv or white.points_hsv:
        ts = time.strftime('%Y%m%d_%H%M%S')
        report_path = os.path.join(CALIB_DIR, f'calib_{ts}_final.txt')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(format_report(yellow, white))
        print(f'Final report: {report_path}')


WEB_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Lane Color Calibrator</title>
  <style>
    body { font-family: sans-serif; margin: 16px; background: #111; color: #eee; }
    img { max-width: 100%; border: 2px solid #444; cursor: crosshair; }
    button, select { margin: 4px; padding: 8px 12px; font-size: 14px; }
    pre { background: #222; padding: 12px; overflow: auto; white-space: pre-wrap; }
    .row { margin-bottom: 10px; }
  </style>
</head>
<body>
  <h2>Lane Color Calibrator</h2>
  <div class="row">
    Sample:
    <select id="mode" onchange="onModeChange()">
      <option value="yellow">YELLOW / dashed</option>
      <option value="white">WHITE / solid</option>
    </select>
    Mask:
    <select id="mask">
      <option value="yellow">yellow only</option>
      <option value="white">white only</option>
      <option value="both">both</option>
      <option value="off">off</option>
    </select>
    <button onclick="undo()">Undo</button>
    <button onclick="clearMode()">Clear mode</button>
    <button onclick="save()">Save report</button>
    <button onclick="refresh()">Refresh frame</button>
  </div>
  <p>Yellow overlay = amber tint. White overlay = cyan tint (yellow dashes are excluded from white).</p>
  <p>Click several spots on the dashed line (YELLOW), then switch to WHITE and click only the solid white line.</p>
  <img id="frame" src="/frame.jpg" onclick="clickImg(event)"/>
  <h3>Status</h3>
  <pre id="status">loading...</pre>
  <h3>Suggested myconfig</h3>
  <pre id="report"></pre>
<script>
async function refresh() {
  document.getElementById('frame').src = '/frame.jpg?' + Date.now();
  const r = await fetch('/status');
  const j = await r.json();
  document.getElementById('status').textContent = JSON.stringify(j, null, 2);
  document.getElementById('report').textContent = j.report || '';
  if (j.mask_mode) document.getElementById('mask').value = j.mask_mode;
}
async function onModeChange() {
  const mode = document.getElementById('mode').value;
  // Auto-switch mask preview to the active sample type
  document.getElementById('mask').value = mode;
  await fetch('/mask?mode=' + mode, {method:'POST'});
  refresh();
}
async function clickImg(ev) {
  const img = ev.target;
  const rect = img.getBoundingClientRect();
  const scaleX = img.naturalWidth / rect.width;
  const scaleY = img.naturalHeight / rect.height;
  const x = Math.round((ev.clientX - rect.left) * scaleX);
  const y = Math.round((ev.clientY - rect.top) * scaleY);
  const mode = document.getElementById('mode').value;
  await fetch('/click', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({x, y, mode})
  });
  refresh();
}
async function undo() {
  await fetch('/undo?mode=' + document.getElementById('mode').value, {method:'POST'});
  refresh();
}
async function clearMode() {
  await fetch('/clear?mode=' + document.getElementById('mode').value, {method:'POST'});
  refresh();
}
async function save() {
  const r = await fetch('/save', {method:'POST'});
  const j = await r.json();
  alert('Saved:\\n' + j.report_path + '\\n' + j.frame_path);
  refresh();
}
document.getElementById('mask').onchange = async (e) => {
  await fetch('/mask?mode=' + e.target.value, {method:'POST'});
  refresh();
};
setInterval(refresh, 2000);
refresh();
</script>
</body>
</html>
"""


def run_web(cam: CameraSource, host='0.0.0.0', port=8890):
    """Browser-based calibrator (works over SSH / no local display)."""
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    os.makedirs(CALIB_DIR, exist_ok=True)
    yellow = SampleBank('YELLOW/dashed')
    white = SampleBank('WHITE/solid')
    state = {'rgb': None, 'mask_mode': 'yellow'}

    def current_rgb():
        rgb = cam.grab()
        if rgb is not None:
            state['rgb'] = rgb
        return state['rgb']

    def status_dict():
        return {
            'yellow_n': len(yellow.points_hsv),
            'white_n': len(white.points_hsv),
            'yellow_hsv': yellow.yellow_hsv_range(),
            'white_hsv': white.white_hsv_range(),
            'yellow_gray': yellow.gray_stats(),
            'white_gray': white.gray_stats(),
            'mask_mode': state['mask_mode'],
            'note': 'white mask excludes yellow samples; yellow=amber tint, white=cyan tint',
            'report': format_report(yellow, white),
        }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _send(self, code, body, content_type='text/plain; charset=utf-8'):
            data = body if isinstance(body, bytes) else body.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == '/' or path == '/index.html':
                self._send(200, WEB_HTML, 'text/html; charset=utf-8')
                return
            if path == '/status':
                self._send(200, json.dumps(status_dict()), 'application/json')
                return
            if path == '/frame.jpg':
                rgb = current_rgb()
                if rgb is None:
                    self._send(503, 'no frame')
                    return
                vis = rgb.copy()
                mm = state['mask_mode']
                if mm == 'yellow':
                    vis = tint_mask(vis, yellow_mask(rgb, yellow), (255, 220, 0))
                elif mm == 'white':
                    # cyan tint; yellow dashes subtracted from white mask
                    vis = tint_mask(vis, white_mask(rgb, white, yellow), (0, 200, 255))
                elif mm == 'both':
                    vis = tint_mask(vis, yellow_mask(rgb, yellow), (255, 220, 0), 0.5)
                    vis = tint_mask(vis, white_mask(rgb, white, yellow), (0, 200, 255), 0.5)
                ok, buf = cv2.imencode('.jpg', cv2.cvtColor(vis, cv2.COLOR_RGB2BGR))
                self._send(200, buf.tobytes(), 'image/jpeg')
                return
            self._send(404, 'not found')

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length) if length else b'{}'
            if path == '/click':
                payload = json.loads(raw.decode('utf-8') or '{}')
                x, y = int(payload['x']), int(payload['y'])
                mode = payload.get('mode', 'yellow')
                rgb = current_rgb()
                if rgb is None:
                    self._send(503, json.dumps({'error': 'no frame'}), 'application/json')
                    return
                bank = yellow if mode == 'yellow' else white
                bank.add_patch(rgb, x, y)
                # Keep mask preview matched to what you're sampling
                state['mask_mode'] = mode
                print(f"[{bank.name}] + HSV={bank.points_hsv[-1]} RGB={bank.points_rgb[-1]} gray={bank.points_gray[-1]} @ ({x},{y})")
                self._send(200, json.dumps(status_dict()), 'application/json')
                return
            if path == '/undo':
                mode = qs.get('mode', ['yellow'])[0]
                bank = yellow if mode == 'yellow' else white
                bank.undo()
                self._send(200, json.dumps(status_dict()), 'application/json')
                return
            if path == '/clear':
                mode = qs.get('mode', ['yellow'])[0]
                bank = yellow if mode == 'yellow' else white
                bank.clear()
                self._send(200, json.dumps(status_dict()), 'application/json')
                return
            if path == '/mask':
                state['mask_mode'] = qs.get('mode', ['both'])[0]
                self._send(200, json.dumps(status_dict()), 'application/json')
                return
            if path == '/save':
                rgb = current_rgb()
                ts = time.strftime('%Y%m%d_%H%M%S')
                frame_path = os.path.join(CALIB_DIR, f'frame_{ts}.jpg')
                report_path = os.path.join(CALIB_DIR, f'calib_{ts}.txt')
                if rgb is not None:
                    cv2.imwrite(frame_path, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                report = format_report(yellow, white)
                with open(report_path, 'w', encoding='utf-8') as f:
                    f.write(report)
                print('Saved', report_path)
                print(report)
                self._send(200, json.dumps({
                    'frame_path': frame_path,
                    'report_path': report_path,
                    'report': report,
                }), 'application/json')
                return
            self._send(404, 'not found')

    # warm a frame
    current_rgb()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"\nOpen in browser: http://ucsdrobocar-DSC-T2.local:{port}/")
    print(f"Or: http://<pi-ip>:{port}/")
    print("Click yellow dashes (mode YELLOW), then switch to WHITE and click the solid line.")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        server.server_close()
        if yellow.points_hsv or white.points_hsv:
            ts = time.strftime('%Y%m%d_%H%M%S')
            report_path = os.path.join(CALIB_DIR, f'calib_{ts}_final.txt')
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(format_report(yellow, white))
            print('Final report:', report_path)


def main():
    parser = argparse.ArgumentParser(description='Calibrate lane colors from OAK-D / image')
    parser.add_argument('--image', help='Use a still image instead of live camera')
    parser.add_argument('--snapshot', action='store_true', help='Grab one frame and exit')
    parser.add_argument('--web', action='store_true', default=True,
                        help='Browser UI (default; works without local display)')
    parser.add_argument('--gui', action='store_true',
                        help='OpenCV desktop window instead of browser')
    parser.add_argument('--port', type=int, default=8890, help='Web UI port (default 8890)')
    args = parser.parse_args()

    cam = CameraSource(image_path=args.image)
    try:
        if args.snapshot:
            capture_snapshot(cam, CALIB_DIR)
            return
        if args.gui:
            run_interactive(cam)
        else:
            run_web(cam, port=args.port)
    finally:
        cam.close()


if __name__ == '__main__':
    main()
