import math
import os
import time
from collections import deque
from glob import glob
from statistics import median

import cv2
import numpy as np
import serial

from dashboard_server import dashboard_state, start_dashboard_server
from flight_prediction import predict_flight


FLIGHT_END_TIMEOUT = 0.35
MIN_SCORING_MOVEMENT = 3.0
MAX_SMOOTH_TURN_RATE = 360.0


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


def calculate_flight_smoothness(samples):
    """Score the consistency of the entire visible flight from 0.0 to 1.0."""
    segments = []

    for previous, current in zip(samples, samples[1:]):
        previous_time, previous_x, previous_y = previous
        current_time, current_x, current_y = current
        elapsed = current_time - previous_time
        delta_x = current_x - previous_x
        delta_y = current_y - previous_y
        distance = math.hypot(delta_x, delta_y)

        # Tiny movements are usually camera or contour jitter, not the airplane.
        if elapsed <= 0 or distance < MIN_SCORING_MOVEMENT:
            continue

        segments.append(
            {
                "time": current_time,
                "heading": math.atan2(delta_y, delta_x),
                "speed": distance / elapsed,
            }
        )

    if len(segments) < 3:
        return 0.0

    total_heading_change = 0.0
    for previous, current in zip(segments, segments[1:]):
        heading_change = current["heading"] - previous["heading"]
        wrapped_change = (heading_change + math.pi) % (2 * math.pi) - math.pi
        total_heading_change += abs(math.degrees(wrapped_change))

    visible_duration = max(segments[-1]["time"] - segments[0]["time"], 0.01)
    turn_rate = total_heading_change / visible_duration
    heading_score = max(0.0, 1.0 - turn_rate / MAX_SMOOTH_TURN_RATE)

    speeds = [segment["speed"] for segment in segments]
    typical_speed = median(speeds)
    speed_deviation = median(abs(speed - typical_speed) for speed in speeds)
    relative_speed_deviation = (
        speed_deviation / typical_speed if typical_speed > 0 else 1.0
    )
    speed_score = max(0.0, 1.0 - min(relative_speed_deviation / 0.75, 1.0))

    # Direction changes are the strongest sign of wobble. Speed consistency has
    # a smaller influence because a good airplane naturally slows during flight.
    smoothness = heading_score * 0.85 + speed_score * 0.15
    return max(0.0, min(1.0, smoothness))


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
flight_times = []
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

                if flight_armed and (
                    not flight_started or current_time - last_seen_time <= FLIGHT_END_TIMEOUT
                ):
                    trajectory.appendleft(center)

                    if not flight_started:
                        flight_started = True
                        flight_complete = False
                        flight_start_time = current_time
                        print("Flight started!")

                    flight_points.append(center)
                    flight_times.append(current_time - flight_start_time)
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

                last_smoothness = calculate_flight_smoothness(
                    list(flight_samples)
                )
                last_score = round(last_smoothness * 100)

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
            # Keep the actual launch point, even after the camera's short trail rolls over.
            trajectory=[list(point) for point in flight_points],
            trajectory_times=list(flight_times),
            prediction=prediction["points"],
            forecast_endpoint=prediction["forecast_endpoint"],
            forecast_kind=prediction["forecast_kind"],
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
            flight_times.clear()
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
            flight_times.clear()
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
