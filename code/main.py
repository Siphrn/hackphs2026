import math
import os
import time
from collections import deque
from glob import glob

import cv2
import numpy as np
import serial

from dashboard_server import dashboard_state, start_dashboard_server


FLIGHT_END_TIMEOUT = 0.35


def connect_arduino():
    """Connect to an Arduino when available without blocking the tracker."""
    configured_port = os.environ.get("SKYTRACE_ARDUINO_PORT")
    detected_ports = glob("/dev/cu.usbmodem*") + glob("/dev/cu.usbserial*")
    candidate_ports = [port for port in [configured_port, *detected_ports] if port]

    for port in dict.fromkeys(candidate_ports):
        try:
            connection = serial.Serial(port, 9600, timeout=1)
            time.sleep(2)
            print(f"Arduino connected: {port}")
            return connection
        except serial.SerialException as error:
            print(f"Arduino unavailable on {port}: {error}")

    print("Arduino not found. OpenCV and the dashboard will continue without it.")
    return None


def predict_flight(samples, frame_width, frame_height):
    """Estimate velocity, angle, and a short future path in camera pixels."""
    empty_prediction = {
        "speed": 0,
        "angle": 0,
        "points": [],
        "remaining_airtime": 0,
        "projected_distance": 0,
        "landing_x": None,
        "confidence": 0,
    }

    if len(samples) < 2:
        return empty_prediction

    recent = list(samples)[-10:]
    first_time, first_x, first_y = recent[0]
    last_time, last_x, last_y = recent[-1]
    elapsed = last_time - first_time

    if elapsed <= 0.01:
        return empty_prediction

    velocity_x = (last_x - first_x) / elapsed
    velocity_y = (last_y - first_y) / elapsed
    speed = math.hypot(velocity_x, velocity_y)
    angle = math.degrees(math.atan2(-velocity_y, max(abs(velocity_x), 0.01)))

    # A lightweight 2D flight model for the hackathon demo. Because it is
    # recalculated each frame, the prediction corrects as new measurements arrive.
    downward_acceleration = 420.0
    ground_y = frame_height * 0.9
    predicted_points = []
    landing_x = None
    remaining_airtime = 0

    for step in range(1, 51):
        future_time = step * 0.04
        predicted_x = last_x + velocity_x * future_time
        predicted_y = (
            last_y
            + velocity_y * future_time
            + 0.5 * downward_acceleration * future_time**2
        )

        predicted_points.append(
            [
                round(max(0, min(frame_width, predicted_x)), 1),
                round(max(0, min(frame_height, predicted_y)), 1),
            ]
        )
        remaining_airtime = future_time

        if predicted_y >= ground_y or predicted_x < 0 or predicted_x > frame_width:
            landing_x = max(0, min(frame_width, predicted_x))
            break

    if landing_x is None and predicted_points:
        landing_x = predicted_points[-1][0]

    confidence = min(92, 35 + len(recent) * 6)

    return {
        "speed": speed,
        "angle": angle,
        "points": predicted_points,
        "remaining_airtime": remaining_airtime,
        "projected_distance": abs((landing_x or last_x) - last_x),
        "landing_x": landing_x,
        "confidence": confidence,
    }


camera = cv2.VideoCapture(0)

if not camera.isOpened():
    raise RuntimeError("Could not open the webcam")

arduino = connect_arduino()

dashboard_server = start_dashboard_server(port=8000)

trajectory = deque(maxlen=150)
recent_centers = deque(maxlen=5)
flight_samples = deque(maxlen=150)

flight_armed = False
flight_started = False
flight_complete = False

flight_points = []
flight_start_time = None
last_seen_time = None

last_airtime = 0
last_distance = 0
last_horizontal_distance = 0
last_score = 0
last_smoothness = 0

try:
    while True:
        success, frame = camera.read()

        if not success:
            break

        frame = cv2.flip(frame, 1)
        detected = False

        hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower_yellow = np.array([20, 100, 120])
        upper_yellow = np.array([40, 255, 255])
        mask = cv2.inRange(hsv_frame, lower_yellow, upper_yellow)

        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest_contour)

            if area > 100:
                detected = True
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
                current_time = time.perf_counter()

                if flight_armed:
                    trajectory.appendleft(center)

                    if not flight_started:
                        flight_started = True
                        flight_complete = False
                        flight_start_time = current_time
                        print("Flight started!")

                    flight_points.append(center)
                    flight_samples.append((current_time, center[0], center[1]))
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
        frame_height, frame_width = frame.shape[:2]
        prediction = predict_flight(flight_samples, frame_width, frame_height)

        if (
            flight_started
            and last_seen_time is not None
            and current_time - last_seen_time > FLIGHT_END_TIMEOUT
        ):
            last_airtime = last_seen_time - flight_start_time
            last_distance = 0
            last_horizontal_distance = 0
            last_smoothness = 0
            last_score = 0

            for index in range(1, len(flight_points)):
                x1, y1 = flight_points[index - 1]
                x2, y2 = flight_points[index]
                last_distance += math.hypot(x2 - x1, y2 - y1)

            if len(flight_points) >= 2:
                starting_x = flight_points[0][0]
                ending_x = flight_points[-1][0]
                last_horizontal_distance = abs(ending_x - starting_x)

                start_point = flight_points[0]
                end_point = flight_points[-1]
                straight_line_distance = math.hypot(
                    end_point[0] - start_point[0],
                    end_point[1] - start_point[1],
                )
                last_smoothness = (
                    straight_line_distance / last_distance
                    if last_distance > 0
                    else 0
                )
                last_smoothness = max(0, min(1, last_smoothness))

                airtime_points = min(last_airtime / 2.0, 1.0) * 40
                distance_points = min(
                    last_horizontal_distance / (frame_width * 0.75),
                    1.0,
                ) * 40
                smoothness_points = last_smoothness * 20
                last_score = round(
                    airtime_points + distance_points + smoothness_points
                )

                print(f"Smoothness: {last_smoothness * 100:.0f}%")
                print(f"Flight score: {last_score}/100")
                if arduino is None:
                    arduino = connect_arduino()

                if arduino is not None:
                    try:
                        arduino.write(f"SCORE:{last_score}\n".encode())
                        arduino.flush()
                        print(f"Sent score {last_score} to Arduino")
                    except serial.SerialException as error:
                        print(f"Could not send score to Arduino: {error}")
                        arduino.close()
                        arduino = None

            print(f"Airtime: {last_airtime:.2f} seconds")
            print(f"Path length: {last_distance:.0f} pixels")
            print(f"Horizontal distance: {last_horizontal_distance} pixels")
            flight_started = False
            flight_armed = False
            flight_complete = True

        if flight_started:
            status = "FLYING"
            displayed_airtime = current_time - flight_start_time
        elif flight_armed:
            status = "ARMED"
            displayed_airtime = last_airtime
        elif flight_complete:
            status = "COMPLETE"
            displayed_airtime = last_airtime
        else:
            status = "READY"
            displayed_airtime = last_airtime

        dashboard_state.update(
            status=status,
            detected=detected,
            score=last_score,
            airtime=displayed_airtime,
            path_length=last_distance,
            horizontal_distance=last_horizontal_distance,
            smoothness=last_smoothness,
            speed=prediction["speed"],
            angle=prediction["angle"],
            remaining_airtime=prediction["remaining_airtime"],
            projected_distance=prediction["projected_distance"],
            landing_x=prediction["landing_x"],
            prediction_confidence=prediction["confidence"],
            frame_width=frame_width,
            frame_height=frame_height,
            trajectory=[list(point) for point in reversed(trajectory)],
            prediction=prediction["points"],
        )

        display_status = (
            "Press SPACE to arm"
            if status in ("READY", "COMPLETE")
            else status
        )
        cv2.putText(
            frame,
            display_status,
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

        if key == ord("c"):
            trajectory.clear()
            recent_centers.clear()
            flight_points.clear()
            flight_samples.clear()
            flight_armed = False
            flight_started = False
            flight_complete = False
            flight_start_time = None
            last_seen_time = None

        if key == ord(" "):
            flight_armed = True
            flight_started = False
            flight_complete = False
            flight_points.clear()
            flight_samples.clear()
            trajectory.clear()
            recent_centers.clear()
            flight_start_time = None
            last_seen_time = None
            print("Flight armed. Throw the plane!")
finally:
    camera.release()
    if arduino is not None:
        arduino.close()
    dashboard_server.shutdown()
    cv2.destroyAllWindows()
