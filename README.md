# SkyTrace

### Every paper airplane throw becomes a flight experiment.

Track a paper airplane, visualize its path, compare designs, and hear your results—all from **one laptop**.

> Built at **HackPHS 2026** for the **“Into the Skies”** theme.
> SkyTrace brings together computer vision, Arduino hardware, and an interactive flight lab.

## The idea

Paper airplanes are easy to build, but their flights are hard to compare by eye.
SkyTrace turns each throw into something you can review: a camera-visible
trajectory, a smoothness score, a short motion forecast, and a tracked video clip.
Build, fly, compare, and improve.

## Features

- **Live tracking:** OpenCV follows yellow markings on your airplane through the webcam.
- **Smoothness scoring:** a 0–100 score based on direction and speed consistency during the visible flight.
- **Trajectory dashboard:** observed path, visible airtime, pixel-based speed, and a short-term forecast.
- **Plane profiles:** organize designs, reorder profiles, and drag saved flights into categories.
- **Flight comparisons:** overlay up to five previous trajectories and replay their recorded paths.
- **Flight videos:** watch short local clips with tracking annotations and the final score.
- **Arduino scoreboard:** send completed scores over USB to a 1602 LCD.
- **Optional voice coach:** ElevenLabs generates spoken, score-based feedback.

## What you need

**One laptop is enough.** The webcam tracker, Python server, browser dashboard,
recordings, and voice integration all run on the same machine. No second laptop
or separate frontend server is required.

- A laptop with a webcam and Python 3; the current setup was developed on macOS.
- A paper airplane with clearly visible yellow markings.
- For the scoreboard: an Arduino, USB cable, LCD1602, breadboard, and wiring matching the sketch.
- For voice feedback: an ElevenLabs API key, internet access, and available API credits.

Tracking and the dashboard work without an Arduino or internet connection.
Only the optional voice coach needs internet access.

## Quick start

### 1. Install dependencies

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\activate` instead of the `source` command.

### 2. Set up the scoreboard (optional)

Open [arduino/arduinoWriting.ino](arduino/arduinoWriting.ino) in the Arduino IDE
and upload it to your board. The sketch uses a parallel LCD connection:
`LiquidCrystal lcd(12, 11, 5, 4, 3, 2)`—wire your LCD to match.

Connect the Arduino to the **same laptop** by USB and close the Arduino IDE
Serial Monitor before starting Python. Communication uses **9600 baud**.

The tracker automatically checks common macOS Arduino ports. If necessary, set
`SKYTRACE_ARDUINO_PORT` to your board's serial port. Without a board, tracking
and the dashboard continue without the LCD.

### 3. Start SkyTrace

```bash
python code/main.py
```

Allow camera access if prompted. Open **[localhost:8000](http://localhost:8000)**
in a browser on that same laptop. If the port is occupied, use the dashboard URL
printed in the terminal instead.

Keep the OpenCV window and browser side by side. Python must stay running
while you use the dashboard.

### 4. Make your first throw

1. Keep the camera stationary and choose a well-lit background without other yellow objects.
2. Optionally add a design in **Planes**, then choose it under **Next throw**.
3. Focus the **OpenCV camera window** and press **Space** to arm the tracker.
4. Throw the airplane through the camera view.
5. Review its completed score, trajectory, and video in the browser.

**Keyboard controls—in the OpenCV window:**

- **Space:** arm a new throw.
- **C:** clear the current path and cancel an unfinished throw.
- **Q:** quit the tracker.

When the airplane is no longer tracked, the flight ends and its graph freezes.
Press Space to begin the next throw.

## Explore the Flight Log

### Flights

The log keeps the **50 most recent completed flights** lasting at least **0.50 seconds**.
Shorter detections are excluded as likely mishaps.

- Filter by plane with **All planes**.
- Click a name to rename it. Enter or clicking away saves; Escape cancels.
- Open **⋯** for Rename and **Move to plane…**.
- Drag a flight's dotted grip to reveal a category tray; drop onto a plane or **Unassigned**.
- Choose **Compare** to select up to five translucent overlays. **Done** hides controls without removing overlays.
- **Clear comparisons** removes overlays, not saved flights.
- **Replay** animates the recorded path with pause, scrubbing, and 0.5× / 1× / 2× speeds.
- **Video** opens the recorded camera view after encoding finishes.

Replays and videos never change the current score or trigger spoken commentary.

### Planes

Use **+ Add plane** to create a profile. Each row shows its saved flight count and
best score. Drag grips reorder the list; **⋯ → Move up/down** is an alternative.
Up to **30 profiles** can exist in a session.

The shared **Next throw** selector determines the plane recorded when you arm a
throw. Changing it during flight affects the next throw. Moving a saved flight
to another category does not change this selection.

## Optional ElevenLabs flight coach

On macOS, run the one-time secure credential setup:

```bash
python code/configure_voice.py
```

The key is stored in **macOS Keychain**, never source files or the browser.
Alternatively, provide `ELEVENLABS_API_KEY` through your environment. Never
commit API keys; rotate any key that has been exposed.

Start the tracker normally, then enable **Flight coach** in the dashboard's top
bar. Your click enables browser audio. It automatically speaks once per completed
flight while enabled. Disabling it stops playback and prevents new requests from
that browser; requests already generating may still consume credits.

The default voice is George (`JBFqnCBsd6RMkjVDRZzb`), configurable through
`ELEVENLABS_VOICE_ID`. Enable Text to Speech access on the API key.

**How AI is used:** ElevenLabs turns a short, scripted, score-based message into
speech. It does not calculate the score or predict the flight. Only that text is
sent to ElevenLabs—not camera footage. Feedback is general coaching, not a
diagnosis of the airplane's design.

## Local recordings & privacy

Recording begins at the first tracked detection, not while waiting for a throw.
Clearing or rearming discards an unfinished recording.

- **Format:** H.264 MP4, no audio, up to 15 seconds per throw, at most 640 pixels wide and 20 fps.
- **Storage cap:** 100 MiB of completed clips, with a 10 MiB cap per clip. Oldest clips expire first; scores and paths remain.
- **Capture buffer:** an additional bounded 8 MiB JPEG buffer and one background encoding job. Limited clips are marked as shortened; if encoding is unavailable or busy, tracking continues without a clip.
- **Session-only:** profiles, history, and completed clips live in tracker memory and clear when Python restarts. Refreshing the browser does not clear them.
- **Temporary encoding:** OpenCV uses a local scratch MP4 during encoding, removed immediately afterward. Footage is not uploaded to cloud services.

Clips also expire when their flight leaves the 50-flight log. Older throws cannot
gain recordings retroactively. The previous `.skytrace/flights.sqlite3` history
file is no longer read or written.

Although only one laptop is needed, the development server is reachable on the
local network. Anyone who can access it can view that session's dashboard and
clips. **Do not expose it to the public internet.**

## Understanding the measurements

The **solid yellow line** is observed motion; the **dashed blue line** is a
forecast. Comparison paths appear as translucent colored lines.

Speed and distance use **camera pixels**, not meters. The angle comes from recent
tracked positions. Prediction uses a simplified 2D motion model, not a complete
aerodynamic simulation.

The graph distinguishes launch, last observed position, estimated frame exit,
and estimated landing at the model's ground reference. **Leaving the camera is
not a measured landing.** Real-world measurements require calibration, and
meaningful comparisons require a consistent camera position and view.

## Built with

| Component | Technology |
| --- | --- |
| Tracking, scoring & forecasting | Python, OpenCV, NumPy |
| Local dashboard server | Python standard library |
| Dashboard & trajectory graphics | HTML, CSS, JavaScript, SVG |
| Physical scoreboard | Arduino, LiquidCrystal, USB serial via pyserial |
| Spoken feedback | ElevenLabs Text to Speech API |
| Video recording | OpenCV, H.264 MP4 |

## Testing & troubleshooting

Run checks from the repository root with the virtual environment active:

```bash
python -m unittest discover -s code -p 'test_*.py'
node code/test_coach.cjs
```

Node.js is needed only for the JavaScript checks, not to run the dashboard.

- **Camera won't open:** close other apps using it and check camera permissions.
- **Plane isn't detected:** check yellow markings, lighting, background, and the detection-mask window.
- **Dashboard isn't updating:** confirm Python is running and use its printed URL.
- **LCD isn't updating:** check wiring, serial port, matching sketch, and that Serial Monitor is closed.
- **Voice isn't playing:** enable Flight coach; check credentials, internet access, and API credits.
- **Video unavailable:** clips may be encoding, expired, or unavailable because the encoder is unsupported or busy.

Restart the tracker after installing code updates, then refresh the website.

---

**SkyTrace · HackPHS 2026 · Into the Skies**
