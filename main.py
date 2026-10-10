import time
import cv2
import numpy as np
from collections import deque
import serial

camera = cv2.VideoCapture(0)

if not camera.isOpened():
    raise RuntimeError("Could not open the webcam")

arduino = serial.Serial("/dev/cu.usbmodem3101", 9600)
time.sleep(2)

trajectory = deque(maxlen=150)
recent_centers = deque(maxlen=5)

flight_armed = False
flight_started = False

flight_points = []
flight_start_time = None
last_seen_time = None

last_airtime = 0
last_distance = 0
last_horizontal_distance = 0

last_score = 0
last_smoothness = 0

while True:
    success, frame = camera.read()

    if not success:
        break

    frame = cv2.flip(frame, 1)

    # Convert the camera image into HSV color space.
    hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    lower_yellow = np.array([20, 100, 120])
    upper_yellow = np.array([40, 255, 255])

    mask = cv2.inRange(hsv_frame, lower_yellow, upper_yellow)

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
        if area > 100:
            (x, y), radius = cv2.minEnclosingCircle(largest_contour)
            raw_center = (int(x), int(y))
            recent_centers.append(raw_center)

            smoothed_x = int(
                sum(point[0] for point in recent_centers) / len(recent_centers)
            )
            smoothed_y = int(
                sum(point[1] for point in recent_centers) / len(recent_centers)
            )

            center = (smoothed_x, smoothed_y)
            trajectory.appendleft(center)

            current_time = time.perf_counter()

            if flight_armed:
                if not flight_started:
                    flight_started = True
                    flight_start_time = current_time
                    print("Flight started!")

                flight_points.append(center)
                last_seen_time = current_time

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

    for index in range(1, len(trajectory)):
        previous_point = trajectory[index - 1]
        current_point = trajectory[index]

        thickness = max(1, int(6 * (1 - index / len(trajectory))))

        cv2.line(
            frame,
            previous_point,
            current_point,
            (255, 0, 255),
            thickness,
        )
    current_time = time.perf_counter()

    if (
        flight_started
        and last_seen_time is not None
        and current_time - last_seen_time > 0.5
    ):
        last_airtime = last_seen_time - flight_start_time

        # Calculates total movment across image in pixels
        last_distance = 0

        for index in range(1, len(flight_points)):
            x1, y1 = flight_points[index - 1]
            x2, y2 = flight_points[index]

            segment_distance = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            last_distance += segment_distance

            if len(flight_points) >= 2:
                starting_x = flight_points[0][0]
                ending_x = flight_points[-1][0]
                last_horizontal_distance = abs(ending_x - starting_x)

                start_point = flight_points[0]
                end_point = flight_points[-1]

                straight_line_distance = (
                    (end_point[0] - start_point[0]) ** 2
                    + (end_point[1] - start_point[1]) ** 2
                ) ** 0.5

                # A straight path approaches 1.0; a shaky path is lower.
                if last_distance > 0:
                    last_smoothness = straight_line_distance / last_distance
                else:
                    last_smoothness = 0

                last_smoothness = max(0, min(1, last_smoothness))

                frame_width = frame.shape[1]

                airtime_points = min(last_airtime / 2.0, 1.0) * 40

                distance_points = min(
                    last_horizontal_distance / (frame_width * 0.75),
                    1.0,
                ) * 40

                smoothness_points = last_smoothness * 20

                last_score = round(
                    airtime_points
                    + distance_points
                    + smoothness_points
                )

                print(f"Smoothness: {last_smoothness * 100:.0f}%")
                print(f"Flight score: {last_score}/100")

        print(f"Airtime: {last_airtime:.2f} seconds")
        print(f"Path length: {last_distance:.0f} pixels")
        print(f"Horizontal distance: {last_horizontal_distance} pixels")

        if len(flight_points) >= 2:
            arduino.write(f"SCORE:{last_score}\n".encode())
            arduino.flush()
            print(f"Sent score {last_score} to Arduino")

        # Prevent this flight from being sent repeatedly
        flight_started = False
        flight_armed = False

        if flight_started:
            status = "FLYING"
        elif flight_armed:
            status = "ARMED"
        else:
            status = "Press SPACE to arm"

        cv2.putText(
            frame,
            status,
            (20, 75),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
        )

        cv2.putText(
            frame,
            f"Last flight: {last_airtime:.2f}s | {last_distance:.0f}px",
            (20, 110),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
        )
        cv2.putText(
            frame,
            f"Score: {last_score}/100",
            (20, 145),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )


    cv2.imshow("Paper Plane Tracker", frame)
    cv2.imshow("Detection Mask", mask)

    key = cv2.waitKey(1) & 0xFF

    if key == ord("q"):
        break

    elif key == ord("c"):
        trajectory.clear()
        recent_centers.clear()

    elif key == ord(" "):
        flight_armed = True
        flight_started = False

        flight_points.clear()
        trajectory.clear()
        recent_centers.clear()  # Clear smoothing from the previous flight

        flight_start_time = None
        last_seen_time = None

        print("Flight armed. Throw the plane!")


camera.release()
cv2.destroyAllWindows()