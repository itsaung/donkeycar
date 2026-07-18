"""Two-lane visual controller for Sungsan's DonkeyCar experiment.

The physical track has a dashed yellow divider and a solid white outer edge.
For the left lane the white edge is left of the divider; for the right lane it
is right of the divider.  The controller detects both markings, estimates the
selected lane centre, and PID-steers that centre toward the camera centre.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class _Candidate:
    x: float
    area: float
    width: int
    height: int


@dataclass
class _Observation:
    index: int
    y: int
    yellow_x: float | None
    white_x: float | None
    center_x: float
    paired: bool
    confidence: float
    weight: float


class LaneFollower:
    """Follow either lane using its yellow and white boundaries."""

    def __init__(self, pid, cfg):
        self.pid_st = pid
        self.lane_side = str(getattr(cfg, "LANE_SIDE", "left")).lower()
        if self.lane_side not in {"left", "right"}:
            raise ValueError("LANE_SIDE must be 'left' or 'right'")

        self.input_color_order = str(
            getattr(cfg, "CV_INPUT_COLOR_ORDER", "BGR")
        ).upper()
        if self.input_color_order not in {"BGR", "RGB"}:
            raise ValueError("CV_INPUT_COLOR_ORDER must be 'BGR' or 'RGB'")

        self.overlay_image = bool(getattr(cfg, "OVERLAY_IMAGE", True))
        self.ref_w = int(getattr(cfg, "IMAGE_W", 160))
        self.ref_h = int(getattr(cfg, "IMAGE_H", 120))
        self.scan_y = int(getattr(cfg, "LANE_SCAN_Y", 52))
        self.scan_height = int(getattr(cfg, "LANE_SCAN_HEIGHT", 10))
        self.scan_count = int(getattr(cfg, "LANE_SCAN_COUNT", 4))
        self.scan_step = int(getattr(cfg, "LANE_SCAN_STEP", 15))

        self.yellow_lo = np.asarray(
            getattr(cfg, "LANE_YELLOW_THRESHOLD_LOW", (18, 18, 35)),
            dtype=np.uint8,
        )
        self.yellow_hi = np.asarray(
            getattr(cfg, "LANE_YELLOW_THRESHOLD_HIGH", (35, 255, 255)),
            dtype=np.uint8,
        )
        self.white_lo = np.asarray(
            getattr(cfg, "LANE_WHITE_THRESHOLD_LOW", (0, 0, 135)),
            dtype=np.uint8,
        )
        self.white_hi = np.asarray(
            getattr(cfg, "LANE_WHITE_THRESHOLD_HIGH", (180, 70, 255)),
            dtype=np.uint8,
        )
        self.yellow_min_dominance = int(
            getattr(cfg, "LANE_YELLOW_MIN_DOMINANCE", 8)
        )
        self.yellow_max_rg_diff = int(
            getattr(cfg, "LANE_YELLOW_MAX_RG_DIFF", 35)
        )
        self.white_max_channel_spread = int(
            getattr(cfg, "LANE_WHITE_MAX_CHANNEL_SPREAD", 70)
        )

        self.min_component_area = float(
            getattr(cfg, "LANE_MIN_COMPONENT_AREA_PX", 3)
        )
        self.max_marking_width = float(
            getattr(cfg, "LANE_MAX_MARKING_WIDTH_PX", 18)
        )
        self.white_max_marking_width = float(
            getattr(cfg, "LANE_WHITE_MAX_MARKING_WIDTH_PX", 70)
        )
        self.nominal_lane_width = float(
            getattr(cfg, "LANE_NOMINAL_WIDTH_PX", 52)
        )
        self.lane_width_ref_y = float(
            getattr(cfg, "LANE_WIDTH_REFERENCE_Y", 82)
        )
        self.min_lane_width = float(
            getattr(cfg, "LANE_MIN_WIDTH_PX", 20)
        )
        self.max_lane_width = float(
            getattr(cfg, "LANE_MAX_WIDTH_PX", 90)
        )
        self.acquire_boundary_distance = float(
            getattr(cfg, "LANE_ACQUIRE_BOUNDARY_DISTANCE_PX", 32)
        )
        self.curve_reacquire_boundary_distance = float(
            getattr(cfg, "LANE_CURVE_REACQUIRE_DISTANCE_PX", 75)
        )
        self.max_center_jump = float(
            getattr(cfg, "LANE_MAX_CENTER_JUMP_PX", 30)
        )
        self.max_boundary_jump = float(
            getattr(cfg, "LANE_MAX_BOUNDARY_JUMP_PX", 30)
        )
        self.max_band_center_deviation = float(
            getattr(cfg, "LANE_MAX_BAND_CENTER_DEVIATION_PX", 28)
        )
        self.center_smoothing = float(
            getattr(cfg, "LANE_CENTER_SMOOTHING", 0.35)
        )
        self.steering_limit = float(
            getattr(cfg, "LANE_STEERING_LIMIT", 0.65)
        )
        self.max_steering_step = float(
            getattr(cfg, "LANE_MAX_STEERING_STEP", 0.20)
        )

        self.target_pixel_cfg = getattr(cfg, "TARGET_PIXEL", None)
        self.target_threshold = float(getattr(cfg, "TARGET_THRESHOLD", 10))
        self.no_lane_stop_frames = int(
            getattr(cfg, "LANE_NO_LINE_STOP_FRAMES", 5)
        )
        self.reacquire_after_frames = int(
            getattr(cfg, "LANE_REACQUIRE_AFTER_FRAMES", 5)
        )

        self.throttle_min = float(getattr(cfg, "THROTTLE_MIN", 0.25))
        self.throttle_max = float(getattr(cfg, "THROTTLE_MAX", 0.35))
        self.throttle = float(
            getattr(cfg, "THROTTLE_INITIAL", self.throttle_min)
        )
        self.throttle_step = float(getattr(cfg, "THROTTLE_STEP", 0.02))
        self.no_lane_throttle_step = float(
            getattr(cfg, "LANE_NO_LINE_THROTTLE_STEP", 0.05)
        )
        self.single_boundary_throttle = float(
            getattr(cfg, "LANE_SINGLE_BOUNDARY_THROTTLE", 0.20)
        )

        self.steering = 0.0
        self.last_center = None
        self.last_yellow = None
        self.last_white = None
        self.last_yellow_by_band = {}
        self.last_white_by_band = {}
        self.lost_frames = 0
        self._debug = {}

    def _scale(self, height, width):
        return float(width) / self.ref_w, float(height) / self.ref_h

    def _scan_bands(self, height, width):
        _, sy = self._scale(height, width)
        band_h = max(2, int(round(self.scan_height * sy)))
        bands = []
        for index in range(max(1, self.scan_count)):
            y0 = int(round((self.scan_y + index * self.scan_step) * sy))
            y0 = int(np.clip(y0, 0, max(0, height - band_h)))
            bands.append((index, y0, band_h))
        return bands

    def _build_masks(self, band):
        if self.input_color_order == "BGR":
            hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
            blue, green, red = cv2.split(band)
        else:
            hsv = cv2.cvtColor(band, cv2.COLOR_RGB2HSV)
            red, green, blue = cv2.split(band)

        yellow = cv2.inRange(hsv, self.yellow_lo, self.yellow_hi)
        red_i = red.astype(np.int16)
        green_i = green.astype(np.int16)
        blue_i = blue.astype(np.int16)
        yellow_relation = (
            (np.minimum(red_i, green_i) - blue_i >= self.yellow_min_dominance)
            & (np.abs(red_i - green_i) <= self.yellow_max_rg_diff)
        )
        yellow = cv2.bitwise_and(
            yellow, (yellow_relation.astype(np.uint8) * 255)
        )

        white = cv2.inRange(hsv, self.white_lo, self.white_hi)
        channels = np.stack((red_i, green_i, blue_i), axis=2)
        spread = channels.max(axis=2) - channels.min(axis=2)
        white = cv2.bitwise_and(
            white, ((spread <= self.white_max_channel_spread).astype(np.uint8) * 255)
        )
        white = cv2.bitwise_and(white, cv2.bitwise_not(yellow))

        yellow = cv2.medianBlur(yellow, 3)
        white = cv2.medianBlur(white, 3)
        return yellow, white

    def _components(self, mask, sx, sy, max_width_ref=None):
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(
            mask, connectivity=8
        )
        min_area = max(2.0, self.min_component_area * sx * sy)
        width_limit = (
            self.max_marking_width
            if max_width_ref is None
            else float(max_width_ref)
        )
        max_width = max(2.0, width_limit * sx)
        candidates = []
        for label in range(1, count):
            x, _y, w, h, area = stats[label]
            if area < min_area or w > max_width:
                continue
            pixels_y, pixels_x = np.where(labels == label)
            if pixels_x.size == 0:
                continue
            lower_cut = np.percentile(pixels_y, 55)
            lower_x = pixels_x[pixels_y >= lower_cut]
            representative_x = float(
                np.median(lower_x if lower_x.size else pixels_x)
            )
            candidates.append(
                _Candidate(representative_x, float(area), int(w), int(h))
            )
        return candidates

    @staticmethod
    def _nearest(candidates, expected):
        if not candidates:
            return None
        return min(candidates, key=lambda c: (abs(c.x - expected), -c.area))

    def _nominal_width(self, band_center_ref):
        perspective = max(0.55, band_center_ref / max(1.0, self.lane_width_ref_y))
        return self.nominal_lane_width * perspective

    def _select_observation(
        self,
        yellow_candidates,
        white_candidates,
        target,
        sx,
        band_center_ref,
        index,
        y_center,
        image_width,
    ):
        nominal_ref = self._nominal_width(band_center_ref)
        nominal = nominal_ref * sx
        min_width = max(self.min_lane_width, nominal_ref * 0.55) * sx
        max_width = min(self.max_lane_width, nominal_ref * 1.55) * sx
        direction = -1.0 if self.lane_side == "left" else 1.0

        previous_yellow = self.last_yellow_by_band.get(index)
        previous_white = self.last_white_by_band.get(index)
        expected_yellow = (
            previous_yellow
            if previous_yellow is not None
            else target - direction * nominal / 2.0
        )
        yellow = self._nearest(yellow_candidates, expected_yellow)
        if (
            yellow is not None
            and previous_yellow is None
            and abs(yellow.x - expected_yellow)
            > self.acquire_boundary_distance * sx
        ):
            yellow = None
        if (
            yellow is not None
            and previous_yellow is not None
            and abs(yellow.x - previous_yellow) > self.max_boundary_jump * sx
        ):
            yellow = None

        expected_white = (
            previous_white
            if previous_white is not None
            else target + direction * nominal / 2.0
        )
        eligible_white = white_candidates
        if yellow is not None:
            if self.lane_side == "left":
                eligible_white = [
                    item
                    for item in white_candidates
                    if min_width <= yellow.x - item.x <= max_width
                ]
                expected_white = yellow.x - nominal
            else:
                eligible_white = [
                    item
                    for item in white_candidates
                    if min_width <= item.x - yellow.x <= max_width
                ]
                expected_white = yellow.x + nominal
        elif previous_yellow is not None:
            if self.lane_side == "left":
                eligible_white = [
                    item
                    for item in white_candidates
                    if min_width * 0.7
                    <= previous_yellow - item.x
                    <= max_width * 1.25
                ]
                expected_white = previous_yellow - nominal
            else:
                eligible_white = [
                    item
                    for item in white_candidates
                    if min_width * 0.7
                    <= item.x - previous_yellow
                    <= max_width * 1.25
                ]
                expected_white = previous_yellow + nominal
        white = self._nearest(eligible_white, expected_white)
        if (
            white is not None
            and previous_white is not None
            and abs(white.x - previous_white) > self.max_boundary_jump * sx
        ):
            white = None

        if yellow is not None and white is not None:
            center = (yellow.x + white.x) / 2.0
            paired = True
            confidence = 1.0
        elif yellow is not None:
            center = yellow.x + direction * nominal / 2.0
            paired = False
            confidence = 0.60
        elif white is not None:
            reacquiring_curve = self.lost_frames >= self.reacquire_after_frames
            acquire_distance = (
                self.curve_reacquire_boundary_distance
                if reacquiring_curve
                else self.acquire_boundary_distance
            )
            allowed = previous_white is not None or (
                abs(white.x - expected_white) <= acquire_distance * sx
            )
            if not allowed:
                return None
            center = white.x - direction * nominal / 2.0
            paired = False
            confidence = 0.45
        else:
            return None

        if not 0.0 <= center < image_width:
            return None

        closeness_weight = 1.0 + 0.45 * index
        if paired:
            closeness_weight *= 1.35
        return _Observation(
            index=index,
            y=y_center,
            yellow_x=None if yellow is None else yellow.x,
            white_x=None if white is None else white.x,
            center_x=float(center),
            paired=paired,
            confidence=confidence,
            weight=closeness_weight,
        )

    def _detect(self, image, target):
        height, width = image.shape[:2]
        sx, sy = self._scale(height, width)
        observations = []
        debug_bands = []

        for index, y0, band_h in self._scan_bands(height, width):
            band = image[y0:y0 + band_h, :, :]
            yellow_mask, white_mask = self._build_masks(band)
            yellow_candidates = self._components(yellow_mask, sx, sy)
            white_candidates = self._components(
                white_mask,
                sx,
                sy,
                max_width_ref=self.white_max_marking_width,
            )
            band_center_ref = self.scan_y + index * self.scan_step + self.scan_height / 2
            observation = self._select_observation(
                yellow_candidates,
                white_candidates,
                target,
                sx,
                band_center_ref,
                index,
                y0 + band_h // 2,
                width,
            )
            if observation is not None:
                observations.append(observation)
            debug_bands.append((y0, band_h, yellow_mask, white_mask))

        if not observations:
            return None, 0.0, observations, debug_bands

        spread = self.max_band_center_deviation * sx
        best_anchor = max(
            observations,
            key=lambda anchor: sum(
                item.weight
                for item in observations
                if abs(item.center_x - anchor.center_x) <= spread
            ),
        )
        trusted = [
            item
            for item in observations
            if abs(item.center_x - best_anchor.center_x) <= spread
        ]
        weights = np.asarray([item.weight for item in trusted], dtype=np.float64)
        centers = np.asarray([item.center_x for item in trusted], dtype=np.float64)
        center = float(np.average(centers, weights=weights))
        confidence = float(
            np.average(
                np.asarray([item.confidence for item in trusted]),
                weights=weights,
            )
        )

        if self.last_center is not None:
            if abs(center - self.last_center) > self.max_center_jump * sx:
                return None, 0.0, trusted, debug_bands
            keep = float(np.clip(self.center_smoothing, 0.0, 0.95))
            center = (1.0 - keep) * center + keep * self.last_center

        return center, confidence, trusted, debug_bands

    def _pid_coordinate(self, x, width):
        if width:
            return float(x) * float(self.ref_w) / float(width)
        return float(x)

    def _handle_missing(self):
        self.lost_frames += 1
        self.throttle = max(0.0, self.throttle - self.no_lane_throttle_step)
        self.steering *= 0.55
        if abs(self.steering) < 0.02:
            self.steering = 0.0
        if self.lost_frames >= self.no_lane_stop_frames:
            self.steering = 0.0
            self.throttle = 0.0
        if self.lost_frames >= self.reacquire_after_frames:
            self.last_center = None
            self.last_yellow = None
            self.last_white = None
            self.last_yellow_by_band.clear()
            self.last_white_by_band.clear()

    def run(self, cam_img):
        if cam_img is None:
            return 0.0, 0.0, None

        height, width = cam_img.shape[:2]
        target = (
            width / 2.0
            if self.target_pixel_cfg is None
            else float(self.target_pixel_cfg) * width / self.ref_w
        )
        center, confidence, observations, debug_bands = self._detect(cam_img, target)

        if center is None:
            self._handle_missing()
            if self.lost_frames in {1, self.no_lane_stop_frames}:
                logger.info(
                    "LaneFollower: lane lost side=%s frames=%d",
                    self.lane_side,
                    self.lost_frames,
                )
        else:
            self.lost_frames = 0
            self.last_center = center
            selected = max(observations, key=lambda item: item.weight)
            for item in observations:
                if item.yellow_x is not None:
                    self.last_yellow_by_band[item.index] = item.yellow_x
                if item.white_x is not None:
                    self.last_white_by_band[item.index] = item.white_x
            if selected.yellow_x is not None:
                self.last_yellow = selected.yellow_x
            if selected.white_x is not None:
                self.last_white = selected.white_x

            target_control = self._pid_coordinate(target, width)
            center_control = self._pid_coordinate(center, width)
            if self.pid_st.setpoint != target_control:
                self.pid_st.setpoint = target_control
            requested_steering = float(np.clip(
                self.pid_st(center_control),
                -self.steering_limit,
                self.steering_limit,
            ))
            steering_delta = float(np.clip(
                requested_steering - self.steering,
                -self.max_steering_step,
                self.max_steering_step,
            ))
            self.steering += steering_delta

            sx, _ = self._scale(height, width)
            paired_boundary = any(item.paired for item in observations)
            if not paired_boundary:
                self.throttle = min(
                    self.single_boundary_throttle,
                    self.throttle + self.throttle_step,
                )
            elif abs(center - target) > self.target_threshold * sx:
                self.throttle = max(
                    self.throttle_min, self.throttle - self.throttle_step
                )
            else:
                self.throttle = min(
                    self.throttle_max, self.throttle + self.throttle_step
                )

        self._debug = {
            "target": target,
            "center": center,
            "confidence": confidence,
            "observations": observations,
            "bands": debug_bands,
            "lost_frames": self.lost_frames,
        }
        output = self.overlay_display(cam_img) if self.overlay_image else cam_img
        return self.steering, self.throttle, output

    def overlay_display(self, cam_img):
        if self.input_color_order == "BGR":
            image = cv2.cvtColor(cam_img, cv2.COLOR_BGR2RGB)
        else:
            image = np.copy(cam_img)

        debug = self._debug
        for y0, band_h, _yellow_mask, _white_mask in debug.get("bands", []):
            cv2.rectangle(
                image,
                (0, y0),
                (image.shape[1] - 1, min(image.shape[0] - 1, y0 + band_h)),
                (75, 75, 75),
                1,
            )

        for item in debug.get("observations", []):
            if item.yellow_x is not None:
                cv2.circle(image, (int(item.yellow_x), item.y), 6, (255, 220, 0), -1)
            if item.white_x is not None:
                cv2.circle(image, (int(item.white_x), item.y), 6, (255, 255, 255), -1)
            cv2.circle(image, (int(item.center_x), item.y), 5, (0, 220, 255), -1)

        target = debug.get("target")
        center = debug.get("center")
        if target is not None:
            cv2.line(
                image,
                (int(target), 0),
                (int(target), image.shape[0] - 1),
                (0, 255, 0),
                2,
            )
        if center is not None:
            cv2.line(
                image,
                (int(center), 0),
                (int(center), image.shape[0] - 1),
                (255, 60, 60),
                2,
            )

        observations = debug.get("observations", [])
        paired_count = sum(item.paired for item in observations)
        status = (
            f"LANE:{self.lane_side} STEER:{self.steering:.2f} "
            f"THROTTLE:{self.throttle:.2f} CONF:{debug.get('confidence', 0.0):.2f} "
            f"LOST:{self.lost_frames}"
        )
        cv2.putText(
            image,
            status,
            (8, 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            image,
            status,
            (8, 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        center_status = "NONE" if center is None else f"{center:.0f}"
        error_ref = (
            0.0
            if center is None or target is None
            else self._pid_coordinate(center - target, image.shape[1])
        )
        detail = (
            f"CENTER:{center_status} TARGET:{target:.0f} "
            f"PAIRS:{paired_count}/{len(observations)} "
            f"ERR_REF:{error_ref:+.1f}"
        )
        cv2.putText(
            image,
            detail,
            (8, 36),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            image,
            detail,
            (8, 36),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        return image
