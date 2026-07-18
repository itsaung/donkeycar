"""
Live color calibrator that shares camera frames with lane_follow.py.

Donkey part: run(cam_img) stores the latest frame.
Background HTTP server on LANE_CALIB_PORT lets you click samples while driving.
"Apply" pushes HSV ranges into the live LaneFollower instance.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

from calibrate_lane_colors import (
    CALIB_DIR,
    SampleBank,
    format_report,
    tint_mask,
    white_mask,
    yellow_mask,
)

logger = logging.getLogger(__name__)

WEB_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Live Lane Color Calib</title>
  <style>
    body { font-family: sans-serif; margin: 16px; background: #111; color: #eee; }
    img { max-width: 100%; border: 2px solid #444; cursor: crosshair; }
    button, select { margin: 4px; padding: 8px 12px; font-size: 14px; }
    pre { background: #222; padding: 12px; overflow: auto; white-space: pre-wrap; }
    .ok { color: #7f7; }
  </style>
</head>
<body>
  <h2>Live Lane Color Calib</h2>
  <p>Drive with Donkey web UI / joystick (User mode). Click tape here to sample.
     <b>Apply live</b> updates the running lane follower immediately.</p>
  <div>
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
    <button onclick="applyLive()">Apply live</button>
    <button onclick="save()">Save report</button>
    <button onclick="refresh()">Refresh</button>
  </div>
  <p class="ok" id="msg"></p>
  <p>Yellow=amber tint, white=cyan (yellow excluded from white).</p>
  <img id="frame" src="/frame.jpg" onclick="clickImg(event)"/>
  <h3>Status</h3>
  <pre id="status">loading...</pre>
  <h3>Suggested myconfig</h3>
  <pre id="report"></pre>
<script>
async function refresh() {
  document.getElementById('frame').src = '/frame.jpg?' + Date.now();
  const j = await (await fetch('/status')).json();
  document.getElementById('status').textContent = JSON.stringify(j, null, 2);
  document.getElementById('report').textContent = j.report || '';
  if (j.mask_mode) document.getElementById('mask').value = j.mask_mode;
}
async function onModeChange() {
  const mode = document.getElementById('mode').value;
  document.getElementById('mask').value = mode;
  await fetch('/mask?mode=' + mode, {method:'POST'});
  refresh();
}
async function clickImg(ev) {
  const img = ev.target;
  const rect = img.getBoundingClientRect();
  const x = Math.round((ev.clientX - rect.left) * (img.naturalWidth / rect.width));
  const y = Math.round((ev.clientY - rect.top) * (img.naturalHeight / rect.height));
  const mode = document.getElementById('mode').value;
  await fetch('/click', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({x,y,mode})
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
async function applyLive() {
  const j = await (await fetch('/apply', {method:'POST'})).json();
  document.getElementById('msg').textContent = j.message || JSON.stringify(j);
  refresh();
}
async function save() {
  const j = await (await fetch('/save', {method:'POST'})).json();
  document.getElementById('msg').textContent = 'Saved ' + j.report_path;
  alert('Saved:\\n' + j.report_path);
  refresh();
}
document.getElementById('mask').onchange = async (e) => {
  await fetch('/mask?mode=' + e.target.value, {method:'POST'});
  refresh();
};
setInterval(refresh, 1500);
refresh();
</script>
</body>
</html>
"""


class LiveLaneCalibServer:
    """Donkey part + background web UI for color sampling while driving."""

    def __init__(self, cfg, lane_follower=None, port=None):
        self.cfg = cfg
        self.lane_follower = lane_follower
        self.port = int(port or getattr(cfg, 'LANE_CALIB_PORT', 8890))
        self.yellow = SampleBank('YELLOW/dashed')
        self.white = SampleBank('WHITE/solid')
        self.mask_mode = 'yellow'
        self._lock = threading.Lock()
        self._rgb = None
        self._server = None
        self._thread = None
        self.running = True
        self._start_server()

    def set_lane_follower(self, lf):
        self.lane_follower = lf

    def _start_server(self):
        outer = self

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
                if path in ('/', '/index.html'):
                    self._send(200, WEB_HTML, 'text/html; charset=utf-8')
                    return
                if path == '/status':
                    self._send(200, json.dumps(outer.status()), 'application/json')
                    return
                if path == '/frame.jpg':
                    jpeg = outer.frame_jpeg()
                    if jpeg is None:
                        self._send(503, 'no frame yet — wait for camera')
                        return
                    self._send(200, jpeg, 'image/jpeg')
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
                    outer.click(int(payload['x']), int(payload['y']), payload.get('mode', 'yellow'))
                    self._send(200, json.dumps(outer.status()), 'application/json')
                    return
                if path == '/undo':
                    outer.undo(qs.get('mode', ['yellow'])[0])
                    self._send(200, json.dumps(outer.status()), 'application/json')
                    return
                if path == '/clear':
                    outer.clear(qs.get('mode', ['yellow'])[0])
                    self._send(200, json.dumps(outer.status()), 'application/json')
                    return
                if path == '/mask':
                    outer.mask_mode = qs.get('mode', ['yellow'])[0]
                    self._send(200, json.dumps(outer.status()), 'application/json')
                    return
                if path == '/apply':
                    self._send(200, json.dumps(outer.apply_live()), 'application/json')
                    return
                if path == '/save':
                    self._send(200, json.dumps(outer.save()), 'application/json')
                    return
                self._send(404, 'not found')

        self._server = ThreadingHTTPServer(('0.0.0.0', self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("Live lane color calib UI on port %d", self.port)
        print(f"*** LIVE COLOR CALIB: http://ucsdrobocar-DSC-T2.local:{self.port}/ ***")
        print("*** Drive on :8887 (User mode). Sample colors on :%d. Click Apply live. ***" % self.port)

    def run(self, cam_img):
        if cam_img is not None:
            with self._lock:
                self._rgb = cam_img
        return

    def shutdown(self):
        self.running = False
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass

    def _get_rgb(self):
        with self._lock:
            return None if self._rgb is None else self._rgb.copy()

    def status(self):
        return {
            'yellow_n': len(self.yellow.points_hsv),
            'white_n': len(self.white.points_hsv),
            'yellow_hsv': self.yellow.yellow_hsv_range(),
            'white_hsv': self.white.white_hsv_range(),
            'mask_mode': self.mask_mode,
            'follower_attached': self.lane_follower is not None,
            'follower_yellow': None if self.lane_follower is None else (
                tuple(self.lane_follower.yellow_lo.tolist()),
                tuple(self.lane_follower.yellow_hi.tolist()),
            ),
            'follower_white': None if self.lane_follower is None else (
                tuple(self.lane_follower.white_lo.tolist()),
                tuple(self.lane_follower.white_hi.tolist()),
            ),
            'report': format_report(self.yellow, self.white),
        }

    def frame_jpeg(self):
        rgb = self._get_rgb()
        if rgb is None:
            return None
        vis = rgb.copy()
        mm = self.mask_mode
        if mm == 'yellow':
            vis = tint_mask(vis, yellow_mask(rgb, self.yellow), (255, 220, 0))
        elif mm == 'white':
            vis = tint_mask(vis, white_mask(rgb, self.white, self.yellow), (0, 200, 255))
        elif mm == 'both':
            vis = tint_mask(vis, yellow_mask(rgb, self.yellow), (255, 220, 0), 0.5)
            vis = tint_mask(vis, white_mask(rgb, self.white, self.yellow), (0, 200, 255), 0.5)
        ok, buf = cv2.imencode('.jpg', cv2.cvtColor(vis, cv2.COLOR_RGB2BGR),
                               [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return buf.tobytes() if ok else None

    def click(self, x, y, mode):
        rgb = self._get_rgb()
        if rgb is None:
            return
        bank = self.yellow if mode == 'yellow' else self.white
        bank.add_patch(rgb, x, y)
        self.mask_mode = mode
        logger.info("[%s] + HSV=%s @ (%d,%d)", bank.name, bank.points_hsv[-1], x, y)

    def undo(self, mode):
        bank = self.yellow if mode == 'yellow' else self.white
        bank.undo()

    def clear(self, mode):
        bank = self.yellow if mode == 'yellow' else self.white
        bank.clear()

    def apply_live(self):
        y_rng = self.yellow.yellow_hsv_range()
        w_rng = self.white.white_hsv_range()
        if self.lane_follower is None:
            return {'ok': False, 'message': 'No LaneFollower attached'}
        if y_rng is None and w_rng is None:
            return {'ok': False, 'message': 'No samples yet — click yellow and/or white tape'}
        self.lane_follower.apply_hsv_ranges(y_rng, w_rng)
        msg = 'Applied live -> '
        if y_rng:
            msg += f'yellow {y_rng[0]}..{y_rng[1]} '
        if w_rng:
            msg += f'white {w_rng[0]}..{w_rng[1]}'
        logger.info(msg)
        return {'ok': True, 'message': msg, 'yellow': y_rng, 'white': w_rng}

    def save(self):
        os.makedirs(CALIB_DIR, exist_ok=True)
        ts = time.strftime('%Y%m%d_%H%M%S')
        frame_path = os.path.join(CALIB_DIR, f'frame_{ts}.jpg')
        report_path = os.path.join(CALIB_DIR, f'calib_{ts}.txt')
        rgb = self._get_rgb()
        if rgb is not None:
            cv2.imwrite(frame_path, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        report = format_report(self.yellow, self.white)
        # Prefer color mode in saved snippet for this workflow
        report = report.replace(
            'LANE_DETECT_MODE = "threshold"',
            'LANE_DETECT_MODE = "color"',
        )
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        # Also auto-apply if possible
        apply = self.apply_live()
        return {
            'frame_path': frame_path,
            'report_path': report_path,
            'report': report,
            'apply': apply,
        }
