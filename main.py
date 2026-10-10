import time
from collections import deque

import cv2
import numpy as np

camera = cv2.VideoCapture(0)

if not camera.isOpened():
    raise RuntimeError("Could not open the webcam")

# Every detection gets remembered as (timestamp, (x, y), radius) so we can
# draw the trail and later work out how long the plane was in the air.
MAX_HISTORY = 120
track_history = deque(maxlen=MAX_HISTORY)

while True:
    success, frame = camera.read()

    if not success:
        break

    # Convert the camera image into HSV color space.
    hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # Starting range for bright green.
    lower_green = np.array([35, 80, 80])
    upper_green = np.array([85, 255, 255])

    # White pixels represent detected green areas.
    mask = cv2.inRange(hsv_frame, lower_green, upper_green)

    # Remove small specks of noise.
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    # Find the outlines of detected objects.
    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    if contours:
        largest_contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest_contour)

        # Ignore very small detections.
        if area > 500:
            (x, y), radius = cv2.minEnclosingCircle(largest_contour)
            center = (int(x), int(y))
            track_history.append((time.time(), center, radius))

            cv2.circle(frame, center, int(radius), (0, 0, 255), 3)
            cv2.circle(frame, center, 5, (255, 0, 0), -1)

            cv2.putText(
                frame,
                f"Tracking: {center}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
            )

    # Draw the trail of recent positions, fading out the older ones.
    points = [p for _, p, _ in track_history]
    for i in range(1, len(points)):
        thickness = max(1, int(6 * i / len(points)))
        cv2.line(frame, points[i - 1], points[i], (0, 200, 255), thickness)

    cv2.imshow("Paper Plane Tracker", frame)
    cv2.imshow("Detection Mask", mask)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()