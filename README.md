# SkyTrace Paper Airplane Scorer

Throw a yellow paper airplane through the laptop camera view. OpenCV tracks the
flight, estimates its future path, scores the throw, sends the score to an
Arduino LCD, and updates a live browser dashboard.

## Run it

1. Connect the Arduino and close the Arduino IDE Serial Monitor.
2. Activate the Python virtual environment.
3. From the repository root, run:

   ```bash
   python code/main.py
   ```

4. Open [http://localhost:8000](http://localhost:8000) on the tracking laptop.
5. Press Space in the OpenCV camera window to arm a throw. Press Q to quit and C
   to clear the displayed path.

## Use the second laptop

Connect both laptops to the same Wi-Fi network. On the tracking Mac, find its
local address with:

```bash
ipconfig getifaddr en0
```

On the second laptop, open `http://TRACKING_LAPTOP_IP:8000`, replacing the
placeholder with that address. The dashboard runs locally and does not require
internet access.

## Dashboard measurements

- Solid yellow line: measured trajectory
- Dashed blue line: predicted future path
- Speed: camera pixels per second
- Angle: direction calculated from recent tracked points
- Landing position and remaining airtime: continuously updated 2D estimate

The current prediction is intentionally camera-relative. Converting pixels to
meters requires camera calibration against an object of known size.
