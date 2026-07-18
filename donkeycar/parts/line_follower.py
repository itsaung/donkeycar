import logging

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

        self.target_pixel_cfg = cfg.TARGET_PIXEL
        self.target_pixel = None
        self.target_threshold = cfg.TARGET_THRESHOLD
        self.confidence_threshold = cfg.CONFIDENCE_THRESHOLD
        self.max_line_width = int(getattr(cfg, 'MAX_LINE_WIDTH_PX', 25))
        self.min_line_aspect = float(getattr(
            cfg, 'MIN_LINE_ASPECT_RATIO', 0.55
        ))
        self.min_line_area = float(getattr(cfg, 'MIN_LINE_AREA_PX', 6.0))
        self.mask_kernel = max(
            1, int(getattr(cfg, 'MASK_MORPH_KERNEL_PX', 1))
        )
        self.max_line_jump = float(getattr(
            cfg, 'MAX_LINE_JUMP_PX', 25.0
        ))
        self.reacquire_after = max(
            1, int(getattr(cfg, 'REACQUIRE_LINE_AFTER_FRAMES', 5))
        )
        self.line_position_alpha = float(np.clip(
            getattr(cfg, 'LINE_POSITION_SMOOTHING', 0.65), 0.0, 1.0
        ))

        self.steering = 0.0
        self.throttle = cfg.THROTTLE_INITIAL
        self.delta_th = cfg.THROTTLE_STEP
        self.throttle_max = cfg.THROTTLE_MAX
        self.throttle_min = cfg.THROTTLE_MIN
        self.no_line_stop_frames = max(
            1, int(getattr(cfg, 'NO_LINE_STOP_FRAMES', 5))
        )
        self.no_line_throttle_step = float(getattr(
            cfg, 'NO_LINE_THROTTLE_STEP', self.delta_th
        ))
        self.no_line_count = 0
        self.previous_line_x = None
        self.selected_scan_y = None

        self.pid_st = pid
        self._geometry = None

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

    def _build_mask(self, band_rgb, frame_height, frame_width):
        hsv = cv2.cvtColor(band_rgb, cv2.COLOR_RGB2HSV)
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for low, high in self.color_ranges:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, low, high))

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
            self, mask, scan_y, frame_height, frame_width):
        max_width = self._max_runtime_line_width(frame_width)
        scale_x, scale_y = self._runtime_scales(
            frame_height, frame_width
        )
        min_area = max(
            1, int(round(self.min_line_area * scale_x * scale_y))
        )
        component_count, labels, stats, centroids = \
            cv2.connectedComponentsWithStats(mask, connectivity=8)
        candidates = []
        for label in range(1, component_count):
            x, _y, component_w, component_h, area = stats[label]
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
            confidence = float(peak_count) / float(max(1, mask.shape[0]))
            if confidence < self.confidence_threshold:
                continue

            candidates.append({
                'x': int(round(float(centroids[label][0]))),
                'scan_y': scan_y,
                'area': int(area),
                'height': int(component_h),
                'confidence': confidence,
                'label': label,
                'labels': labels,
            })
        return candidates

    def _choose_candidate(self, candidates, frame_height, frame_width):
        if not candidates:
            return None

        scale_x, _scale_y = self._runtime_scales(
            frame_height, frame_width
        )
        jump_limit = max(1.0, self.max_line_jump * scale_x)
        tracking = (
            self.previous_line_x is not None and
            self.no_line_count < self.reacquire_after
        )
        expected_x = self.previous_line_x if tracking else self.target_pixel

        best = None
        for candidate in candidates:
            distance = abs(float(candidate['x']) - float(expected_x))
            if tracking and distance > jump_limit:
                continue

            proximity = max(0.0, 1.0 - distance / jump_limit)
            height_score = min(
                1.0,
                float(candidate['height']) / float(max(1, self._geometry[1]))
            )
            road_depth = float(candidate['scan_y']) / float(
                max(1, frame_height - self._geometry[1])
            )
            score = (
                3.0 * proximity +
                1.5 * candidate['confidence'] +
                0.5 * height_score +
                0.25 * road_depth
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

        candidates = []
        for scan_y in self._scan_positions(height, y0, band_h):
            band = cam_img[scan_y:scan_y + band_h, :, :]
            if band.shape[0] != band_h:
                continue
            band_mask = self._build_mask(band, height, width)
            candidates.extend(self._component_candidates(
                band_mask, scan_y, height, width
            ))

        selected_mask = np.zeros((height, width), dtype=np.uint8)
        selected = self._choose_candidate(candidates, height, width)
        if selected is None:
            self.selected_scan_y = None
            return 0, 0.0, selected_mask

        selected_y = int(selected['scan_y'])
        selected_component = np.asarray(
            selected['labels'] == selected['label'], dtype=np.uint8
        ) * 255
        selected_mask[selected_y:selected_y + band_h] = selected_component

        raw_x = float(selected['x'])
        if self.previous_line_x is None:
            filtered_x = raw_x
        else:
            alpha = self.line_position_alpha
            filtered_x = (
                alpha * raw_x + (1.0 - alpha) * self.previous_line_x
            )
        self.previous_line_x = filtered_x
        self.selected_scan_y = selected_y
        return (
            int(round(filtered_x)),
            float(selected['confidence']),
            selected_mask,
        )

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

        line_x, confidence, mask = self.get_i_color(cam_img)
        width = cam_img.shape[1]
        target_control = self._pid_coordinate(self.target_pixel, width)
        line_control = self._pid_coordinate(line_x, width)
        self.pid_st.setpoint = target_control

        if confidence >= self.confidence_threshold:
            self.no_line_count = 0
            self.throttle = max(self.throttle, self.throttle_min)
            self.steering = float(np.clip(
                self.pid_st(line_control), -1.0, 1.0
            ))

            if abs(line_control - target_control) > self.target_threshold:
                self.throttle = max(
                    self.throttle_min, self.throttle - self.delta_th
                )
            else:
                self.throttle = min(
                    self.throttle_max, self.throttle + self.delta_th
                )
        else:
            self.no_line_count += 1
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
        return self.steering, self.throttle, out_img

    def overlay_display(self, cam_img, mask, line_x, confidence):
        img = np.copy(cam_img)
        y0, band_h = self._geometry or (self.scan_y, self.scan_height)
        detected = mask > 0
        if np.any(detected):
            tint = np.empty_like(img)
            tint[:, :] = (0, 210, 255)
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
        ]
        for index, text in enumerate(display):
            cv2.putText(
                img, text, (10, 14 + index * 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1,
            )
        return img
