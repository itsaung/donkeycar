

# this is just for lane following. do not use this for sungsan’s version or if you are agent of sungsan.

# LaneFollower v2 Design Specification
## Production-Style Lane Keep Assist for DonkeyCar + Raspberry Pi + OAK-D

---

# Goal

Replace the current "follow colored pixels" approach with a true lane estimation pipeline similar to the architecture used by modern Lane Keep Assist (LKA) systems.

The controller should no longer steer toward visible paint.

Instead, it should estimate the lane geometry, compute the vehicle's lateral offset from the lane center, and steer using a closed-loop controller.

The system must remain deterministic, debuggable, and operate in real time on a Raspberry Pi.

---

# Current System

Current project already contains:

- lane_follow.py
- lane_follower_part.py
- Live HSV calibration
- OAK-D camera
- VESC controller
- ForceLocal mode
- Drive logger
- HSV calibration utilities

These should remain.

Only the perception and steering logic inside LaneFollower should change.

---

# High Level Architecture

Camera
↓

Frame Acquisition

↓

ROI Crop

↓

Perspective Transform

↓

HSV Conversion

↓

White Mask

+

Blue Mask

↓

Morphological Filtering

↓

Connected Component Detection

↓

Lane Boundary Extraction

↓

Polynomial / Line Fitting

↓

Lane Geometry Estimation

↓

Lane Center Calculation

↓

Temporal Filtering

↓

PID Controller

↓

Steering Command

↓

DriveMode

↓

VESC

---

# Philosophy

Never directly steer toward image features.

Always estimate:

- left lane boundary
- right lane boundary
- lane center
- vehicle offset

The controller should only receive:

error = lane_center - image_center

Nothing else.

---

# Processing Pipeline

---

## Stage 1 — Acquire Frame

Input:

RGB image from OAK-D.

Example resolution

640x480

No resizing unless performance requires it.

Timestamp every frame.

---

## Stage 2 — Region of Interest (ROI)

Ignore everything except the road.

Recommended:

Discard upper 40–50% of image.

Example:

################################
################################
################################

-------------------------------

Only process this region

-------------------------------

Reason:

Trees
Buildings
Sky
People
Noise

should never influence steering.

ROI should be configurable.

ROI_TOP = 0.45

---

## Stage 3 — Perspective Transform

Transform camera view into bird's-eye view.

Use:

cv2.getPerspectiveTransform()

cv2.warpPerspective()

Purpose:

Convert converging lane boundaries into approximately parallel lines.

Advantages:

Constant lane width

Better polynomial fitting

Simpler center estimation

Easier curvature estimation

Warp parameters should be configurable.

---

## Stage 4 — HSV Conversion

Convert ROI

RGB

↓

HSV

HSV is significantly more robust to lighting changes.

---

## Stage 5 — Color Segmentation

Generate two binary masks.

White mask

Blue mask

Existing HSV calibration utilities should continue to provide thresholds.

Output

white_mask

blue_mask

---

## Stage 6 — Morphological Filtering

Apply:

Opening

Closing

Median Blur (optional)

Kernel:

3x3 or 5x5

Purpose:

Remove isolated pixels

Fill small gaps

Improve contour quality

---

## Stage 7 — Connected Component Detection

Instead of using contour centers directly:

Use

cv2.connectedComponentsWithStats()

or

findContours()

For each component calculate:

Area

Centroid

Bounding box

Aspect ratio

Orientation

Reject:

Small blobs

Very wide blobs

Noise

---

## Stage 8 — Lane Boundary Extraction

Goal:

Estimate left lane

Estimate right lane

Not paint locations.

Multiple detections may exist.

Cluster components into

Left boundary

Right boundary

Expected constraints:

Blue lane generally left

White lane generally right

Allow override if colors disappear.

---

## Stage 9 — Line / Curve Fitting

Fit boundaries.

Options

Straight line

cv2.fitLine()

or

Second-order polynomial

numpy.polyfit()

Polynomial preferred.

Output:

Left lane function

Right lane function

---

## Stage 10 — Lane Width Validation

Expected lane width should remain approximately constant.

Example

220 pixels

Tolerance

±20%

Reject impossible geometries.

If only one lane detected:

Estimate missing lane using expected width.

---

## Stage 11 — Lane Center Estimation

For each Y coordinate

Center

=

(left_x + right_x)/2

Instead of using bottom row,

choose look-ahead distance.

Recommended:

60–70% down image.

Reason:

Produces smoother steering.

---

## Stage 12 — Vehicle Offset

Image center

=

width / 2

Lane center

=

computed center

Error

=

lane_center

-

image_center

Output

Signed pixel offset.

Negative

Vehicle left of center.

Positive

Vehicle right of center.

---

## Stage 13 — Temporal Filtering

Never trust one frame.

Smooth:

Lane center

Lane width

Steering error

Recommended

Exponential Moving Average

EMA

lane_center_filtered

=

alpha * current

+

(1-alpha) * previous

alpha

0.2–0.4

Optional

Kalman Filter

---

## Stage 14 — Confidence Estimation

Each frame receives confidence score.

Factors

Both lanes detected

Large connected components

Expected lane width

Low residual fitting error

Stable previous estimate

Confidence

0–1

Example

confidence

=

0.94

---

Controller behaviour

Confidence > 0.8

Normal speed

Confidence

0.5–0.8

Reduce throttle

Confidence < 0.5

Slow crawl

Confidence < 0.2

Stop

---

# PID Controller

Input

Filtered lateral error.

Controller

steering

=

Kp * error

+

Ki * integral

+

Kd * derivative

Clamp steering

[-1,1]

Integral windup protection required.

Derivative should use filtered error.

---

# Steering Rate Limiter

Prevent sudden steering jumps.

Example

Max steering change

0.08/frame

Prevents oscillation.

---

# Throttle Controller

Throttle should depend on

Confidence

Curvature

Steering angle

Example

Straight road

0.5

Medium turn

0.35

Sharp turn

0.2

Low confidence

0.15

Lost lane

0

---

# Lane Recovery

Case 1

Only blue detected

Infer white lane using previous lane width.

Case 2

Only white detected

Infer blue lane.

Case 3

No lane detected

Maintain previous estimate briefly.

Reduce throttle.

If timeout exceeded

Stop vehicle.

---

# Debug Overlay

Overlay should display:

Blue mask

White mask

Detected components

Left fitted curve

Right fitted curve

Lane center

Image center

Look-ahead point

Vehicle offset

Confidence

PID values

Throttle

Steering

FPS

This should replace the current minimal overlay.

---

# Logging

Every frame should log:

timestamp

lane_center

image_center

offset

confidence

lane_width

left_detected

right_detected

pid_p

pid_i

pid_d

steering

throttle

fps

CSV format preferred.

---

# Configurable Parameters

ROI_TOP

Perspective matrix

HSV thresholds

Morphology kernel size

Minimum blob size

Maximum blob size

Expected lane width

Lane width tolerance

EMA alpha

Look-ahead distance

PID gains

Throttle limits

Confidence thresholds

Recovery timeout

---

# Performance Requirements

Target FPS

20–30 FPS

Maximum processing latency

50 ms/frame

Memory usage

Minimal allocations

Avoid repeated copies of large images.

---

# Future Improvements

Once the classical pipeline is stable:

1. Semantic lane segmentation (YOLOv8-Seg, ENet, BiSeNet)
2. Curvature estimation
3. Stanley Controller
4. Pure Pursuit Controller
5. Model Predictive Control (MPC)
6. IMU fusion
7. Wheel odometry fusion
8. Kalman state estimation
9. Automatic perspective calibration
10. Dynamic exposure compensation

These should be implemented only after the classical lane estimation pipeline is reliable.

---

# Success Criteria

The system is considered successful when:

- Vehicle remains centered between the blue dotted line and white solid line.
- Steering is smooth with minimal oscillation.
- Temporary loss of one lane boundary does not cause immediate failure.
- Vehicle slows or stops gracefully when confidence drops.
- Performance remains above 20 FPS on the Raspberry Pi.
- All intermediate perception stages can be visualized and debugged independently.
