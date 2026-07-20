import json
import logging
import os
import queue
import threading
import time

import cv2
import numpy as np


logger = logging.getLogger(__name__)


class LineFollower:
    """OpenCV controller that follows a single coloured line.

    The scan geometry and PID coordinates are expressed in the configured
    ``IMAGE_W``/``IMAGE_H`` reference resolution. They are scaled when the
    camera supplies a different runtime resolution (for example, an OAK-D
    frame at 702x520 while the car config uses 160x120).
    """

    def __init__(self, pid, cfg):
        self.overlay_image = cfg.OVERLAY_IMAGE
        self.scan_y = cfg.SCAN_Y
        self.scan_height = cfg.SCAN_HEIGHT
        self.scan_extra_rows = int(getattr(cfg, 'SCAN_EXTRA_ROWS', 0))
        self.ref_image_w = getattr(cfg, 'IMAGE_W', None)
        self.ref_image_h = getattr(cfg, 'IMAGE_H', None)
        self.input_color_order = str(getattr(
            cfg, 'CV_INPUT_COLOR_ORDER', 'RGB'
        )).upper()
        if self.input_color_order not in ('RGB', 'BGR'):
            raise ValueError(
                'CV_INPUT_COLOR_ORDER must be RGB or BGR, got {}'.format(
                    self.input_color_order
                )
            )

        self.color_ranges = [(
            np.asarray(cfg.COLOR_THRESHOLD_LOW, dtype=np.uint8),
            np.asarray(cfg.COLOR_THRESHOLD_HIGH, dtype=np.uint8),
        )]
        secondary_low = getattr(
            cfg, 'COLOR_THRESHOLD_LOW_2',
            getattr(cfg, 'YELLOW2_THRESHOLD_LOW', None),
        )
        secondary_high = getattr(
            cfg, 'COLOR_THRESHOLD_HIGH_2',
            getattr(cfg, 'YELLOW2_THRESHOLD_HIGH', None),
        )
        if secondary_low is not None and secondary_high is not None:
            self.color_ranges.append((
                np.asarray(secondary_low, dtype=np.uint8),
                np.asarray(secondary_high, dtype=np.uint8),
            ))
        self.color_dominance_mode = str(getattr(
            cfg, 'COLOR_DOMINANCE_MODE', 'NONE'
        )).upper()
        self.color_min_dominance = int(getattr(
            cfg, 'COLOR_MIN_DOMINANCE', 0
        ))
        self.color_max_channel_diff = int(getattr(
            cfg, 'COLOR_MAX_CHANNEL_DIFF', 255
        ))

        self.target_pixel_cfg = cfg.TARGET_PIXEL
        self.target_pixel = None
        self.target_threshold = cfg.TARGET_THRESHOLD
        self.confidence_threshold = cfg.CONFIDENCE_THRESHOLD
        self.max_line_width = int(getattr(cfg, 'MAX_LINE_WIDTH_PX', 25))
        self.min_line_aspect = float(getattr(
            cfg, 'MIN_LINE_ASPECT_RATIO', 0.55
        ))
        self.min_line_area = float(getattr(cfg, 'MIN_LINE_AREA_PX', 6.0))
        self.min_tape_quality = float(getattr(
            cfg, 'MIN_TAPE_QUALITY', 0.0
        ))
        self.tape_width_reference = max(1.0, float(getattr(
            cfg, 'TAPE_WIDTH_REFERENCE_PX', 9.0
        )))
        self.tape_area_reference = max(1.0, float(getattr(
            cfg, 'TAPE_AREA_REFERENCE_PX', 18.0
        )))
        self.tape_saturation_reference = max(1.0, float(getattr(
            cfg, 'TAPE_SATURATION_REFERENCE', 90.0
        )))
        self.tape_value_reference = max(1.0, float(getattr(
            cfg, 'TAPE_VALUE_REFERENCE', 220.0
        )))
        self.mask_kernel = max(
            1, int(getattr(cfg, 'MASK_MORPH_KERNEL_PX', 1))
        )
        self.max_line_jump = float(getattr(
            cfg, 'MAX_LINE_JUMP_PX', 25.0
        ))
        self.acquire_max_distance = float(getattr(
            cfg, 'ACQUIRE_MAX_DISTANCE_PX', self.max_line_jump
        ))
        self.min_tracked_size_ratio = float(np.clip(
            getattr(cfg, 'MIN_TRACKED_SIZE_RATIO', 0.0), 0.0, 1.0
        ))
        self.velocity_alpha = float(np.clip(
            getattr(cfg, 'LINE_VELOCITY_SMOOTHING', 0.5), 0.0, 1.0
        ))
        self.prediction_frames = max(0.0, float(getattr(
            cfg, 'LINE_PREDICTION_FRAMES', 0.0
        )))
        self.max_predicted_shift = max(0.0, float(getattr(
            cfg, 'MAX_PREDICTED_SHIFT_PX', self.max_line_jump
        )))
        self.velocity_decay = float(np.clip(
            getattr(cfg, 'LINE_VELOCITY_DECAY', 0.8), 0.0, 1.0
        ))
        self.side_reversal_margin = max(0.0, float(getattr(
            cfg, 'SIDE_REVERSAL_MARGIN_PX', 0.0
        )))
        self.path_min_components = max(1, int(getattr(
            cfg, 'PATH_MIN_COMPONENTS', 1
        )))
        self.path_x_tolerance = max(0.0, float(getattr(
            cfg, 'PATH_X_TOLERANCE_PX', 8.0
        )))
        self.path_max_slope = max(0.0, float(getattr(
            cfg, 'PATH_MAX_SLOPE', 1.5
        )))
        self.path_min_vertical_gap = max(0.0, float(getattr(
            cfg, 'PATH_MIN_VERTICAL_GAP_PX', 4.0
        )))
        self.path_fit_residual = max(0.0, float(getattr(
            cfg, 'PATH_FIT_RESIDUAL_PX', self.path_x_tolerance
        )))
        self.path_support_weight = max(0.0, float(getattr(
            cfg, 'PATH_SUPPORT_WEIGHT', 1.5
        )))
        self.path_alignment_weight = max(0.0, float(getattr(
            cfg, 'PATH_ALIGNMENT_WEIGHT', 0.75
        )))
        self.reacquire_min_path_alignment = float(np.clip(getattr(
            cfg, 'REACQUIRE_MIN_PATH_ALIGNMENT', 0.0
        ), 0.0, 1.0))
        self.jump_min_path_alignment = float(np.clip(getattr(
            cfg, 'JUMP_MIN_PATH_ALIGNMENT', 0.0
        ), 0.0, 1.0))
        self.path_alignment_jump_threshold = max(0.0, float(getattr(
            cfg, 'PATH_ALIGNMENT_JUMP_THRESHOLD_PX', 8.0
        )))
        self.edge_reacquire_distance = max(0.0, float(getattr(
            cfg, 'EDGE_REACQUIRE_DISTANCE_PX', 0.0
        )))
        self.edge_reacquire_min_components = max(1, int(getattr(
            cfg, 'EDGE_REACQUIRE_MIN_COMPONENTS', 1
        )))
        self.reacquire_min_saturation = max(0.0, float(getattr(
            cfg, 'REACQUIRE_MIN_SATURATION', 0.0
        )))
        self.isolated_track_distance = max(0.0, float(getattr(
            cfg, 'ISOLATED_TRACK_DISTANCE_PX', 12.0
        )))
        self.reacquire_after = max(
            1, int(getattr(cfg, 'REACQUIRE_LINE_AFTER_FRAMES', 5))
        )
        self.reacquire_confirm_frames = max(1, int(getattr(
            cfg, 'REACQUIRE_CONFIRM_FRAMES', 1
        )))
        self.reacquire_confirm_distance = max(0.0, float(getattr(
            cfg, 'REACQUIRE_CONFIRM_DISTANCE_PX', 18.0
        )))
        self.line_position_alpha = float(np.clip(
            getattr(cfg, 'LINE_POSITION_SMOOTHING', 0.65), 0.0, 1.0
        ))

        self.illumination_guard_enabled = bool(getattr(
            cfg, 'ILLUMINATION_GUARD_ENABLED', False
        ))
        self.illumination_change_threshold = max(0.0, float(getattr(
            cfg, 'ILLUMINATION_CHANGE_THRESHOLD', 35.0
        )))
        self.illumination_stable_threshold = max(0.0, float(getattr(
            cfg, 'ILLUMINATION_STABLE_THRESHOLD', 8.0
        )))
        self.illumination_hold_frames = max(1, int(getattr(
            cfg, 'ILLUMINATION_HOLD_FRAMES', 4
        )))

        self.steering = 0.0
        self.throttle_initial = float(cfg.THROTTLE_INITIAL)
        self.throttle = self.throttle_initial
        self.delta_th = cfg.THROTTLE_STEP
        self.throttle_max = cfg.THROTTLE_MAX
        self.throttle_min = cfg.THROTTLE_MIN
        self.throttle_straight = float(getattr(
            cfg, 'THROTTLE_STRAIGHT', self.throttle_max
        ))
        self.throttle_curve = float(getattr(
            cfg, 'THROTTLE_CURVE', self.throttle_min
        ))
        self.throttle_accel_step = max(0.0, float(getattr(
            cfg, 'THROTTLE_ACCEL_STEP', self.delta_th
        )))
        self.throttle_decel_step = max(0.0, float(getattr(
            cfg, 'THROTTLE_DECEL_STEP', self.delta_th
        )))
        self.curve_steering_start = max(0.0, float(getattr(
            cfg, 'CURVE_STEERING_START', 0.1
        )))
        self.curve_steering_full = max(
            self.curve_steering_start + 1e-6,
            float(getattr(cfg, 'CURVE_STEERING_FULL', 0.3)),
        )
        self.curve_path_slope_start = max(0.0, float(getattr(
            cfg, 'CURVE_PATH_SLOPE_START', 1.0
        )))
        self.curve_path_slope_full = max(
            self.curve_path_slope_start + 1e-6,
            float(getattr(cfg, 'CURVE_PATH_SLOPE_FULL', 2.5)),
        )
        self.low_confidence_threshold = max(0.0, float(getattr(
            cfg, 'LOW_CONFIDENCE_THRESHOLD', self.confidence_threshold
        )))
        self.low_confidence_throttle = float(getattr(
            cfg, 'LOW_CONFIDENCE_THROTTLE', self.throttle_curve
        ))
        self.no_line_stop_frames = max(
            1, int(getattr(cfg, 'NO_LINE_STOP_FRAMES', 5))
        )
        self.no_line_throttle_step = float(getattr(
            cfg, 'NO_LINE_THROTTLE_STEP', self.delta_th
        ))
        self.no_line_count = 0
        self.previous_line_x = None
        self.previous_component_width_ref = None
        self.previous_component_area_ref = None
        self.line_velocity = 0.0
        self.selected_scan_y = None
        self.selected_path_support = None
        self.selected_path_slope = None
        self.curve_strength = 0.0
        self.desired_throttle = self.throttle
        self.pending_reacquire_x = None
        self.pending_reacquire_count = 0
        self.scene_brightness = None
        self.previous_scene_brightness = None
        self.illumination_delta = 0.0
        self.illumination_hold_remaining = 0

        self.pid_st = pid
        self._geometry = None

        self.debug_capture_enabled = bool(getattr(
            cfg, 'CV_DEBUG_CAPTURE', False
        ))
        self.capture_every_n_frames = max(
            1, int(getattr(cfg, 'CV_DEBUG_CAPTURE_EVERY_N_FRAMES', 40))
        )
        self.capture_save_overlay = bool(getattr(
            cfg, 'CV_DEBUG_CAPTURE_SAVE_OVERLAY', True
        ))
        self.capture_jpeg_quality = int(np.clip(
            getattr(cfg, 'CV_DEBUG_CAPTURE_JPEG_QUALITY', 85), 1, 100
        ))
        self.capture_queue_size = max(
            1, int(getattr(cfg, 'CV_DEBUG_CAPTURE_QUEUE_SIZE', 16))
        )
        self.capture_max_frames = max(
            1, int(getattr(cfg, 'CV_DEBUG_CAPTURE_MAX_FRAMES', 500))
        )
        self.capture_root = str(getattr(
            cfg,
            'CV_DEBUG_CAPTURE_DIR',
            os.path.join(str(getattr(cfg, 'DATA_PATH', '.')),
                         'debug_captures'),
        ))
        self.capture_session_dir = None
        self.capture_queue = None
        self.capture_stop = None
        self.capture_thread = None
        self.capture_frame_index = 0
        self.capture_saved_count = 0
        self.capture_last_detected = None
        self.capture_dropped = 0
        if self.debug_capture_enabled:
            self._start_debug_capture()

    def _start_debug_capture(self):
        try:
            os.makedirs(self.capture_root, exist_ok=True)
            session_name = 'session_{}'.format(
                time.strftime('%Y%m%d_%H%M%S')
            )
            session_dir = os.path.join(self.capture_root, session_name)
            suffix = 2
            while os.path.exists(session_dir):
                session_dir = os.path.join(
                    self.capture_root, '{}_{}'.format(session_name, suffix)
                )
                suffix += 1
            os.makedirs(session_dir)
            self.capture_session_dir = session_dir

            session_info = {
                'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'input_color_order': self.input_color_order,
                'capture_every_n_frames': self.capture_every_n_frames,
                'capture_max_frames': self.capture_max_frames,
                'save_overlay': self.capture_save_overlay,
                'jpeg_quality': self.capture_jpeg_quality,
                'reference_image_size': [self.ref_image_w, self.ref_image_h],
                'scan_y': self.scan_y,
                'scan_height': self.scan_height,
                'scan_extra_rows': self.scan_extra_rows,
                'color_ranges': [
                    [low.tolist(), high.tolist()]
                    for low, high in self.color_ranges
                ],
                'path_min_components': self.path_min_components,
                'path_max_slope': self.path_max_slope,
                'throttle_straight': self.throttle_straight,
                'throttle_curve': self.throttle_curve,
                'illumination_guard_enabled':
                    self.illumination_guard_enabled,
            }
            with open(
                    os.path.join(session_dir, 'session.json'),
                    'w', encoding='utf-8') as session_file:
                json.dump(session_info, session_file, indent=2)

            self.capture_queue = queue.Queue(
                maxsize=self.capture_queue_size
            )
            self.capture_stop = threading.Event()
            self.capture_thread = threading.Thread(
                target=self._debug_capture_worker,
                name='line-follower-debug-capture',
                daemon=True,
            )
            self.capture_thread.start()
            logger.info(
                'CV debug capture enabled: %s (every %d frames, max %d)',
                session_dir,
                self.capture_every_n_frames,
                self.capture_max_frames,
            )
        except Exception:
            logger.exception('Unable to start CV debug capture')
            self.debug_capture_enabled = False

    def _debug_capture_worker(self):
        metadata_path = os.path.join(
            self.capture_session_dir, 'frames.jsonl'
        )
        with open(metadata_path, 'a', encoding='utf-8', buffering=1) \
                as metadata_file:
            while (not self.capture_stop.is_set() or
                   not self.capture_queue.empty()):
                try:
                    item = self.capture_queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    write_args = [
                        cv2.IMWRITE_JPEG_QUALITY,
                        self.capture_jpeg_quality,
                    ]
                    raw_path = os.path.join(
                        self.capture_session_dir, item['raw_file']
                    )
                    if not cv2.imwrite(
                            raw_path, item['raw_bgr'], write_args):
                        raise RuntimeError(
                            'Unable to write {}'.format(raw_path)
                        )
                    if item['overlay_bgr'] is not None:
                        overlay_path = os.path.join(
                            self.capture_session_dir,
                            item['overlay_file'],
                        )
                        if not cv2.imwrite(
                                overlay_path,
                                item['overlay_bgr'],
                                write_args):
                            raise RuntimeError(
                                'Unable to write {}'.format(overlay_path)
                            )
                    metadata_file.write(
                        json.dumps(item['metadata']) + '\n'
                    )
                except Exception:
                    logger.exception('Unable to save CV debug frame')
                finally:
                    self.capture_queue.task_done()

    def _camera_frame_to_bgr(self, cam_img):
        if self.input_color_order == 'BGR':
            return np.copy(cam_img)
        return cv2.cvtColor(cam_img, cv2.COLOR_RGB2BGR)

    def _maybe_capture_debug_frame(
            self, cam_img, out_img, line_x, confidence):
        if not self.debug_capture_enabled or self.capture_queue is None:
            return

        self.capture_frame_index += 1
        if self.capture_saved_count >= self.capture_max_frames:
            return
        detected = confidence >= self.confidence_threshold
        state_changed = (
            self.capture_last_detected is None or
            detected != self.capture_last_detected
        )
        periodic = self.capture_frame_index % self.capture_every_n_frames == 0
        illumination_event = (
            self.illumination_delta >= self.illumination_change_threshold
        )
        self.capture_last_detected = detected
        if not periodic and not state_changed and not illumination_event:
            return

        reasons = []
        if periodic:
            reasons.append('periodic')
        if state_changed:
            reasons.append('line_state_changed')
        if illumination_event:
            reasons.append('illumination_changed')
        timestamp = time.time()
        stem = 'frame_{:07d}_{:013d}'.format(
            self.capture_frame_index, int(timestamp * 1000)
        )
        raw_file = '{}_raw.jpg'.format(stem)
        overlay_file = '{}_overlay.jpg'.format(stem) \
            if self.capture_save_overlay else None
        if self.capture_save_overlay:
            if self.overlay_image:
                overlay_bgr = cv2.cvtColor(out_img, cv2.COLOR_RGB2BGR)
            else:
                overlay_bgr = self._camera_frame_to_bgr(out_img)
        else:
            overlay_bgr = None

        item = {
            'raw_file': raw_file,
            'raw_bgr': self._camera_frame_to_bgr(cam_img),
            'overlay_file': overlay_file,
            'overlay_bgr': overlay_bgr,
            'metadata': {
                'frame_index': self.capture_frame_index,
                'timestamp': timestamp,
                'raw_file': raw_file,
                'overlay_file': overlay_file,
                'reason': reasons,
                'line_detected': detected,
                'line_x': int(line_x),
                'target_x': int(self.target_pixel),
                'confidence': float(confidence),
                'steering': float(self.steering),
                'throttle': float(self.throttle),
                'lost_frames': int(self.no_line_count),
                'selected_scan_y': self.selected_scan_y,
                'path_support': self.selected_path_support,
                'path_slope': self.selected_path_slope,
                'curve_strength': self.curve_strength,
                'desired_throttle': self.desired_throttle,
                'scene_brightness': self.scene_brightness,
                'illumination_delta': self.illumination_delta,
                'illumination_hold_remaining':
                    self.illumination_hold_remaining,
            },
        }
        try:
            self.capture_queue.put_nowait(item)
            self.capture_saved_count += 1
        except queue.Full:
            self.capture_dropped += 1
            if self.capture_dropped == 1 or self.capture_dropped % 50 == 0:
                logger.warning(
                    'CV debug capture queue full; dropped %d frame(s)',
                    self.capture_dropped,
                )

    def shutdown(self):
        if self.capture_thread is None:
            return
        self.capture_stop.set()
        self.capture_thread.join(timeout=5.0)
        if self.capture_thread.is_alive():
            logger.warning('CV debug capture did not finish within 5 seconds')

    def _scaled_geometry(self, height, width):
        y0 = int(self.scan_y)
        band_h = int(self.scan_height)
        if self.ref_image_h and self.ref_image_h != height:
            scale_y = float(height) / float(self.ref_image_h)
            y0 = int(round(y0 * scale_y))
            band_h = max(1, int(round(band_h * scale_y)))

        y0 = int(np.clip(y0, 0, max(0, height - 1)))
        band_h = int(np.clip(band_h, 1, max(1, height - y0)))

        if self.target_pixel_cfg is None:
            target = width // 2
        elif self.ref_image_w and self.ref_image_w != width:
            target = int(round(
                float(self.target_pixel_cfg) * width / float(self.ref_image_w)
            ))
        else:
            target = int(self.target_pixel_cfg)
        target = int(np.clip(target, 0, max(0, width - 1)))
        return y0, band_h, target

    def _runtime_scales(self, height, width):
        scale_x = float(width) / float(self.ref_image_w) \
            if self.ref_image_w else 1.0
        scale_y = float(height) / float(self.ref_image_h) \
            if self.ref_image_h else 1.0
        return scale_x, scale_y

    @staticmethod
    def _odd_kernel_size(reference_size, scale):
        if reference_size <= 1:
            return 1
        size = max(3, int(round((reference_size - 1) * scale)) + 1)
        return size if size % 2 else size + 1

    def _build_mask(self, band_img, frame_height, frame_width):
        if self.input_color_order == 'BGR':
            hsv = cv2.cvtColor(band_img, cv2.COLOR_BGR2HSV)
            blue, green, red = cv2.split(band_img)
        else:
            hsv = cv2.cvtColor(band_img, cv2.COLOR_RGB2HSV)
            red, green, blue = cv2.split(band_img)
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for low, high in self.color_ranges:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, low, high))

        if self.color_dominance_mode == 'YELLOW':
            red_i = red.astype(np.int16)
            green_i = green.astype(np.int16)
            blue_i = blue.astype(np.int16)
            dominance = np.minimum(red_i, green_i) - blue_i
            channel_diff = np.abs(red_i - green_i)
            yellow_pixels = np.logical_and(
                dominance >= self.color_min_dominance,
                channel_diff <= self.color_max_channel_diff,
            )
            mask = cv2.bitwise_and(
                mask, np.asarray(yellow_pixels, dtype=np.uint8) * 255
            )

        scale_x, scale_y = self._runtime_scales(
            frame_height, frame_width
        )
        kernel_size = self._odd_kernel_size(
            self.mask_kernel, min(scale_x, scale_y)
        )
        if kernel_size > 1:
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
            )
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        return mask

    def _scan_positions(self, height, y0, band_h):
        positions = [y0]
        if self.scan_extra_rows > 0:
            step = max(1, band_h // 2)
            for index in range(1, self.scan_extra_rows + 1):
                # Prefer the nearer/lower part of the road before looking up.
                positions.extend((y0 + index * step, y0 - index * step))
        return list(dict.fromkeys(
            int(np.clip(y, 0, max(0, height - band_h)))
            for y in positions
        ))

    def _component_candidates(
            self, mask, band_img, scan_y, frame_height, frame_width):
        max_width = self._max_runtime_line_width(frame_width)
        scale_x, scale_y = self._runtime_scales(
            frame_height, frame_width
        )
        min_area = max(
            1, int(round(self.min_line_area * scale_x * scale_y))
        )
        component_count, labels, stats, centroids = \
            cv2.connectedComponentsWithStats(mask, connectivity=8)
        if self.input_color_order == 'BGR':
            hsv = cv2.cvtColor(band_img, cv2.COLOR_BGR2HSV)
        else:
            hsv = cv2.cvtColor(band_img, cv2.COLOR_RGB2HSV)
        candidates = []
        for label in range(1, component_count):
            x, component_y, component_w, component_h, area = stats[label]
            if area < min_area or component_w > max_width:
                continue
            aspect = float(component_h) / float(max(1, component_w))
            if aspect < self.min_line_aspect:
                continue

            component_columns = np.count_nonzero(
                labels[:, x:x + component_w] == label, axis=0
            )
            peak_count = int(component_columns.max()) \
                if component_columns.size else 0
            confidence_height = self._geometry[1] \
                if self._geometry is not None else mask.shape[0]
            confidence = float(peak_count) / float(
                max(1, confidence_height)
            )
            if confidence < self.confidence_threshold:
                continue

            component_pixels = labels == label
            mean_saturation = float(np.mean(hsv[:, :, 1][component_pixels]))
            mean_value = float(np.mean(hsv[:, :, 2][component_pixels]))
            width_ref = float(component_w) / float(max(scale_x, 1e-6))
            area_ref = float(area) / float(max(scale_x * scale_y, 1e-6))
            width_score = min(1.0, width_ref / self.tape_width_reference)
            area_score = min(1.0, area_ref / self.tape_area_reference)
            saturation_score = min(
                1.0, mean_saturation / self.tape_saturation_reference
            )
            value_score = min(
                1.0, mean_value / self.tape_value_reference
            )
            tape_quality = (
                0.45 * width_score +
                0.40 * area_score +
                0.10 * saturation_score +
                0.05 * value_score
            )
            if tape_quality < self.min_tape_quality:
                continue

            candidates.append({
                'x': int(round(float(centroids[label][0]))),
                'scan_y': scan_y,
                'area': int(area),
                'height': int(component_h),
                'width_ref': width_ref,
                'area_ref': area_ref,
                'tape_quality': tape_quality,
                'mean_saturation': mean_saturation,
                'mean_value': mean_value,
                'center_y': float(scan_y + centroids[label][1]),
                'bottom_y': int(scan_y + component_y + component_h),
                'confidence': confidence,
                'path_support': 1,
                'path_alignment': 1.0,
                'path_slope': 0.0,
                'label': label,
                'labels': labels,
            })
        return candidates

    def _annotate_path_support(self, candidates, frame_height, frame_width):
        """Count geometrically compatible tape pieces for each candidate.

        Real dashed tape normally produces several components that continue
        along one curve. A leaf or a painted patch elsewhere on the road is
        usually isolated. All limits are expressed in the reference camera
        resolution so the same rule works at OAK-D runtime resolution.
        """
        scale_x, scale_y = self._runtime_scales(
            frame_height, frame_width
        )
        scale_x = max(scale_x, 1e-6)
        scale_y = max(scale_y, 1e-6)
        points = [(
            candidate['x'] / scale_x,
            candidate['center_y'] / scale_y,
        ) for candidate in candidates]
        for index, candidate in enumerate(candidates):
            anchor_x, anchor_y = points[index]
            slopes = [0.0]
            for other_index, (other_x, other_y) in enumerate(points):
                if other_index == index:
                    continue
                dy_ref = other_y - anchor_y
                if abs(dy_ref) < self.path_min_vertical_gap:
                    continue
                slope = (other_x - anchor_x) / dy_ref
                if abs(slope) <= self.path_max_slope:
                    slopes.append(slope)

            best = (1, 0.0, 1.0)
            best_slope = 0.0
            for slope in slopes:
                residuals = []
                for point_x, point_y in points:
                    predicted_x = anchor_x + slope * (point_y - anchor_y)
                    residual = abs(point_x - predicted_x)
                    if residual <= self.path_fit_residual:
                        residuals.append(residual)
                support = len(residuals)
                mean_residual = float(np.mean(residuals)) \
                    if residuals else self.path_fit_residual
                alignment = max(
                    0.0,
                    1.0 - abs(slope) / max(self.path_max_slope, 1e-6),
                )
                ranked = (support, -mean_residual, alignment)
                if ranked > best:
                    best = ranked
                    best_slope = slope
            candidate['path_support'] = best[0]
            candidate['path_alignment'] = best[2]
            candidate['path_slope'] = best_slope

    def _choose_candidate(self, candidates, frame_height, frame_width):
        if not candidates:
            return None

        scale_x, _scale_y = self._runtime_scales(
            frame_height, frame_width
        )
        jump_limit = max(1.0, self.max_line_jump * scale_x)
        acquire_limit = max(
            1.0, self.acquire_max_distance * scale_x
        )
        tracking = (
            self.previous_line_x is not None and
            self.no_line_count < self.reacquire_after
        )
        expected_x = self.target_pixel
        if tracking:
            predicted_shift = float(np.clip(
                self.line_velocity * self.prediction_frames,
                -self.max_predicted_shift * scale_x,
                self.max_predicted_shift * scale_x,
            ))
            expected_x = self.previous_line_x + predicted_shift

        best = None
        for candidate in candidates:
            distance = abs(float(candidate['x']) - float(expected_x))
            if tracking and distance > jump_limit:
                continue
            if not tracking and distance > acquire_limit:
                continue
            if (not tracking and
                    candidate['mean_saturation'] <
                    self.reacquire_min_saturation):
                continue
            edge_distance_ref = abs(
                float(candidate['x']) - float(self.target_pixel)
            ) / max(scale_x, 1e-6)
            if (not tracking and self.edge_reacquire_distance > 0.0 and
                    edge_distance_ref > self.edge_reacquire_distance and
                    candidate['path_support'] <
                    self.edge_reacquire_min_components):
                continue

            if (not tracking and
                    candidate['path_alignment'] <
                    self.reacquire_min_path_alignment):
                continue
            alignment_jump = self.path_alignment_jump_threshold * scale_x
            if (tracking and distance > alignment_jump and
                    candidate['path_alignment'] <
                    self.jump_min_path_alignment):
                continue

            if candidate['path_support'] < self.path_min_components:
                isolated_limit = self.isolated_track_distance * scale_x
                if not tracking or distance > isolated_limit:
                    continue

            if tracking and self.side_reversal_margin > 0.0:
                reversal_margin = self.side_reversal_margin * scale_x
                previous_offset = self.previous_line_x - self.target_pixel
                candidate_offset = candidate['x'] - self.target_pixel
                crossed_sides = previous_offset * candidate_offset < 0.0
                if (crossed_sides and
                        abs(previous_offset) > reversal_margin and
                        abs(candidate_offset) > reversal_margin):
                    continue

            if (tracking and self.min_tracked_size_ratio > 0.0 and
                    self.previous_component_width_ref is not None and
                    self.previous_component_area_ref is not None):
                width_too_small = candidate['width_ref'] < (
                    self.previous_component_width_ref *
                    self.min_tracked_size_ratio
                )
                area_too_small = candidate['area_ref'] < (
                    self.previous_component_area_ref *
                    self.min_tracked_size_ratio
                )
                if width_too_small and area_too_small:
                    continue

            distance_limit = jump_limit if tracking else acquire_limit
            proximity = max(0.0, 1.0 - distance / distance_limit)
            height_score = min(
                1.0,
                float(candidate['height']) / float(max(1, self._geometry[1]))
            )
            road_depth = float(candidate['bottom_y']) / float(
                max(1, frame_height)
            )
            if self.path_min_components <= 1:
                path_score = 1.0
            else:
                path_score = min(
                    1.0,
                    float(candidate['path_support'] - 1) /
                    float(self.path_min_components - 1),
                )
            score = (
                1.25 * proximity +
                1.0 * candidate['confidence'] +
                0.5 * height_score +
                1.5 * candidate['tape_quality'] +
                1.25 * road_depth +
                self.path_support_weight * path_score +
                self.path_alignment_weight * candidate['path_alignment']
            )
            ranked = (score, candidate['area'], candidate)
            if best is None or ranked[:2] > best[:2]:
                best = ranked
        return None if best is None else best[2]

    def get_i_color(self, cam_img):
        """Return detected x position, confidence (0..1), and colour mask."""
        height, width = cam_img.shape[:2]
        y0, band_h, target = self._scaled_geometry(height, width)
        self._geometry = (y0, band_h)
        self.target_pixel = target

        scan_positions = self._scan_positions(height, y0, band_h)
        roi_y0 = min(scan_positions)
        roi_y1 = min(height, max(y + band_h for y in scan_positions))
        roi_img = cam_img[roi_y0:roi_y1, :, :]
        roi_mask = np.zeros((roi_y1 - roi_y0, width), dtype=np.uint8)
        for scan_y in scan_positions:
            band = cam_img[scan_y:scan_y + band_h, :, :]
            if band.shape[0] != band_h:
                continue
            band_mask = self._build_mask(band, height, width)
            offset = scan_y - roi_y0
            roi_mask[offset:offset + band_h] = cv2.bitwise_or(
                roi_mask[offset:offset + band_h], band_mask
            )

        candidates = self._component_candidates(
            roi_mask, roi_img, roi_y0, height, width
        )
        self._annotate_path_support(candidates, height, width)

        selected_mask = np.zeros((height, width), dtype=np.uint8)
        selected = self._choose_candidate(candidates, height, width)
        if selected is None:
            self.selected_scan_y = None
            self.selected_path_support = None
            self.selected_path_slope = None
            self.pending_reacquire_x = None
            self.pending_reacquire_count = 0
            return 0, 0.0, selected_mask

        selected_y = int(selected['scan_y'])
        selected_component = np.asarray(
            selected['labels'] == selected['label'], dtype=np.uint8
        ) * 255
        selected_mask[selected_y:selected_y + selected_component.shape[0]] = \
            selected_component

        raw_x = float(selected['x'])
        tracking_before_selection = (
            self.previous_line_x is not None and
            self.no_line_count < self.reacquire_after
        )
        if not tracking_before_selection and self.reacquire_confirm_frames > 1:
            confirm_limit = self.reacquire_confirm_distance * (
                float(width) / float(self.ref_image_w)
                if self.ref_image_w else 1.0
            )
            if (self.pending_reacquire_x is not None and
                    abs(raw_x - self.pending_reacquire_x) <= confirm_limit):
                self.pending_reacquire_count += 1
                self.pending_reacquire_x = 0.5 * (
                    self.pending_reacquire_x + raw_x
                )
            else:
                self.pending_reacquire_x = raw_x
                self.pending_reacquire_count = 1
            if self.pending_reacquire_count < self.reacquire_confirm_frames:
                self.selected_scan_y = selected_y
                return 0, 0.0, selected_mask
            raw_x = self.pending_reacquire_x
        self.pending_reacquire_x = None
        self.pending_reacquire_count = 0
        if not tracking_before_selection:
            filtered_x = raw_x
            self.line_velocity = 0.0
        else:
            observed_velocity = raw_x - self.previous_line_x
            self.line_velocity = (
                self.velocity_alpha * observed_velocity +
                (1.0 - self.velocity_alpha) * self.line_velocity
            )
            alpha = self.line_position_alpha
            filtered_x = (
                alpha * raw_x + (1.0 - alpha) * self.previous_line_x
            )
        self.previous_line_x = filtered_x
        self.previous_component_width_ref = selected['width_ref']
        self.previous_component_area_ref = selected['area_ref']
        self.selected_scan_y = selected_y
        self.selected_path_support = selected['path_support']
        self.selected_path_slope = selected['path_slope']
        return (
            int(round(filtered_x)),
            float(selected['confidence']),
            selected_mask,
        )

    def _update_illumination_guard(self, cam_img):
        if not self.illumination_guard_enabled:
            self.illumination_hold_remaining = 0
            return False

        height, width = cam_img.shape[:2]
        y0, band_h, target = self._scaled_geometry(height, width)
        self._geometry = (y0, band_h)
        self.target_pixel = target
        scan_positions = self._scan_positions(height, y0, band_h)
        roi_y0 = min(scan_positions)
        roi_y1 = min(height, max(y + band_h for y in scan_positions))
        road_roi = cam_img[roi_y0:roi_y1]
        brightness = float(np.median(np.max(road_roi, axis=2)))
        self.scene_brightness = brightness

        if self.previous_scene_brightness is None:
            self.previous_scene_brightness = brightness
            self.illumination_delta = 0.0
            return False

        delta = abs(brightness - self.previous_scene_brightness)
        self.previous_scene_brightness = brightness
        self.illumination_delta = delta
        changed = delta >= self.illumination_change_threshold
        if changed:
            self.illumination_hold_remaining = self.illumination_hold_frames
            logger.info(
                "Illumination changed by %.1f; pausing for exposure recovery",
                delta,
            )
        elif self.illumination_hold_remaining > 0:
            if delta > self.illumination_stable_threshold:
                self.illumination_hold_remaining = max(
                    self.illumination_hold_remaining, 2
                )
            else:
                self.illumination_hold_remaining -= 1
        return self.illumination_hold_remaining > 0

    def _pid_coordinate(self, x, width):
        if self.ref_image_w and width:
            return float(x) * float(self.ref_image_w) / float(width)
        return float(x)

    def _max_runtime_line_width(self, width):
        if self.ref_image_w and self.ref_image_w != width:
            return max(1, int(round(
                self.max_line_width * width / float(self.ref_image_w)
            )))
        return max(1, self.max_line_width)

    def run(self, cam_img):
        if cam_img is None:
            return 0.0, 0.0, None

        if self._update_illumination_guard(cam_img):
            self.no_line_count += 1
            self.line_velocity *= self.velocity_decay
            self.steering = 0.0
            self.throttle = 0.0
            self.selected_scan_y = None
            self.selected_path_support = None
            self.selected_path_slope = None
            self.curve_strength = 0.0
            self.desired_throttle = 0.0
            height, width = cam_img.shape[:2]
            line_x = int(round(self.previous_line_x)) \
                if self.previous_line_x is not None else 0
            mask = np.zeros((height, width), dtype=np.uint8)
            out_img = self.overlay_display(cam_img, mask, line_x, 0.0) \
                if self.overlay_image else cam_img
            self._maybe_capture_debug_frame(
                cam_img, out_img, line_x, 0.0
            )
            return self.steering, self.throttle, out_img

        line_x, confidence, mask = self.get_i_color(cam_img)
        width = cam_img.shape[1]
        target_control = self._pid_coordinate(self.target_pixel, width)
        line_control = self._pid_coordinate(line_x, width)
        self.pid_st.setpoint = target_control

        if confidence >= self.confidence_threshold:
            self.no_line_count = 0
            self.steering = float(np.clip(
                self.pid_st(line_control), -1.0, 1.0
            ))

            steering_curve = float(np.clip(
                (abs(self.steering) - self.curve_steering_start) /
                (self.curve_steering_full - self.curve_steering_start),
                0.0, 1.0,
            ))
            path_slope = abs(self.selected_path_slope or 0.0)
            path_curve = float(np.clip(
                (path_slope - self.curve_path_slope_start) /
                (self.curve_path_slope_full - self.curve_path_slope_start),
                0.0, 1.0,
            ))
            self.curve_strength = max(steering_curve, path_curve)
            self.desired_throttle = (
                self.throttle_straight +
                (self.throttle_curve - self.throttle_straight) *
                self.curve_strength
            )
            if confidence < self.low_confidence_threshold:
                self.desired_throttle = min(
                    self.desired_throttle, self.low_confidence_throttle
                )
            self.desired_throttle = float(np.clip(
                self.desired_throttle,
                min(self.throttle_curve, self.throttle_straight),
                max(self.throttle_curve, self.throttle_straight),
            ))
            if self.throttle > self.desired_throttle:
                self.throttle = max(
                    self.desired_throttle,
                    self.throttle - self.throttle_decel_step,
                )
            else:
                if self.throttle < self.throttle_min:
                    self.throttle = min(
                        self.desired_throttle,
                        self.throttle_min,
                    )
                else:
                    self.throttle = min(
                        self.desired_throttle,
                        self.throttle + self.throttle_accel_step,
                    )
        else:
            self.no_line_count += 1
            self.line_velocity *= self.velocity_decay
            self.curve_strength = 1.0
            self.desired_throttle = 0.0
            self.throttle = max(
                0.0, self.throttle - self.no_line_throttle_step
            )
            if self.no_line_count >= self.no_line_stop_frames:
                self.throttle = 0.0
                self.steering = 0.0
            if self.no_line_count == 1 or self.no_line_count % 20 == 0:
                logger.info(
                    "No line detected: confidence %.4f < %.4f (frames=%d)",
                    confidence, self.confidence_threshold, self.no_line_count,
                )

        out_img = cam_img
        if self.overlay_image:
            out_img = self.overlay_display(
                cam_img, mask, line_x, confidence
            )
        self._maybe_capture_debug_frame(
            cam_img, out_img, line_x, confidence
        )
        return self.steering, self.throttle, out_img

    def overlay_display(self, cam_img, mask, line_x, confidence):
        if self.input_color_order == 'BGR':
            # DonkeyCar's OAK-D part returns OpenCV BGR frames. The web UI
            # expects RGB, so convert only the debug output for correct colour.
            img = cv2.cvtColor(cam_img, cv2.COLOR_BGR2RGB)
        else:
            img = np.copy(cam_img)
        y0, band_h = self._geometry or (self.scan_y, self.scan_height)
        detected = mask > 0
        if np.any(detected):
            tint = np.empty_like(img)
            tint[:, :] = (255, 210, 0)
            blended = cv2.addWeighted(img, 0.65, tint, 0.35, 0)
            img[detected] = blended[detected]

        for scan_y in self._scan_positions(img.shape[0], y0, band_h):
            cv2.rectangle(
                img, (0, scan_y),
                (img.shape[1] - 1, min(img.shape[0] - 1,
                                      scan_y + band_h - 1)),
                (80, 80, 80), 1,
            )

        cv2.line(img, (self.target_pixel, 0),
                 (self.target_pixel, img.shape[0] - 1), (0, 255, 0), 2)
        if confidence >= self.confidence_threshold:
            selected_y = self.selected_scan_y \
                if self.selected_scan_y is not None else y0
            cv2.line(img, (line_x, selected_y),
                     (line_x, min(img.shape[0] - 1,
                                  selected_y + band_h - 1)),
                     (255, 0, 0), 2)

        display = [
            "STEERING:{:.2f}".format(self.steering),
            "THROTTLE:{:.2f}".format(self.throttle),
            "LINE X:{:d} TARGET:{:d}".format(line_x, self.target_pixel),
            "CONF:{:.3f} LOST:{:d}".format(confidence, self.no_line_count),
            "CURVE:{:.2f} DESIRED:{:.2f} SLOPE:{:.2f}".format(
                self.curve_strength,
                self.desired_throttle,
                self.selected_path_slope or 0.0,
            ),
            "LIGHT:{:.0f} DELTA:{:.0f} HOLD:{:d}".format(
                self.scene_brightness or 0.0,
                self.illumination_delta,
                self.illumination_hold_remaining,
            ),
        ]
        for index, text in enumerate(display):
            cv2.putText(
                img, text, (10, 14 + index * 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1,
            )
        return img
