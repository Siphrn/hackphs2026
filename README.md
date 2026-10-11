# SkyTrace Paper Airplane Scorer

Throw a yellow paper airplane through the laptop camera view. OpenCV tracks the
flight, estimates its future path, scores how smoothly it moves throughout the
visible portion of the throw, sends the score to an
Arduino LCD, and updates a live browser dashboard.

## Run it

### ElevenLabs voice commentary

Start the tracker normally; voice credentials load automatically from Mac Keychain
(or `ELEVENLABS_API_KEY` if set):

```sh
python code/main.py
```

There is no startup key prompt or separate verification request. For one-time setup
on another Mac, or to replace a rotated key, run `python code/configure_voice.py`.
The key is stored securely in Keychain, never source files or the browser. Rotate
keys shared in chat. Enable Text to Speech access; the default voice is George
(`JBFqnCBsd6RMkjVDRZzb`), overridable with `ELEVENLABS_VOICE_ID`.

In the website's top bar, switch **Flight coach** on once to allow browser audio.
It automatically speaks once after each completed flight while enabled. Switching
it off stops speech and prevents further requests from that browser; speech already
being generated may still consume credits. There are no voice play or replay controls,
and switching back on does not repeat an already-announced flight. The switch
starts off on page load so browsers can unlock sound from your click.
Feedback tiers are 0–24, 25–49, 50–74, 75–89, and 90–100.
Speech includes the exact score. Only the score and a short scripted message go
to ElevenLabs, not camera video. Suggestions are general coaching, not measured
wing diagnostics. Internet and ElevenLabs credits are required for audio; tracking
and scoring still work offline. Audio generation runs in the background and is
deduplicated per flight, including across browser tabs. The last 12 flights are
cached in memory to deduplicate requests. ElevenLabs still authenticates actual
speech requests; an invalid or expired key cannot be bypassed. The old
`code/start_with_voice.py` launcher also works without a prompt.

### Tracker

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

### Flight history and trajectory replay

The left panel keeps the last 50 completed flights lasting at least 0.50 seconds,
newest first. History resets when the tracker process restarts (not when the browser
refreshes). Collapse or expand it with the animated arrow; reduced-motion preferences
are respected. Click a flight name to edit it, then press Enter or click away to save.
Escape cancels; names must contain 1–60 characters and update on both laptops.
Check **Compare** to add up to five color-coded, translucent paths
over the current graph. **Clear overlays** removes comparisons without deleting history.

Press a flight's **Replay** to animate its recorded path on the same graph. Pause,
resume, scrub the timeline, or choose 0.5× / 1× / 2× playback. Replay never replaces
live tracking, changes the current score, or requests spoken commentary. Closing
replay leaves that flight's full comparison path visible.

History lives only in tracker memory and is shared with both laptops through
`/api/history`. The previous `.skytrace/flights.sqlite3` file is no longer read or
written. History contains
positions, sample times, and metrics—not camera video, audio, or API keys. Flights
recorded before this feature was installed cannot be recovered automatically.
Different frame resolutions are normalized for overlays; comparisons only make
sense with the same camera position and view, and are not physical-distance measurements.

### Graph

- Solid yellow line: measured trajectory
- Dashed blue line: predicted future path
- Speed: camera pixels per second
- Angle: direction calculated from recent tracked points
- Landing position and remaining airtime: continuously updated 2D estimate

The current prediction is intentionally camera-relative. Converting pixels to
meters requires camera calibration against an object of known size.

Completed results are frozen. Voice requests carry the run ID, flight ID, and
exact score; mismatches are rejected. Audio URLs are unique per tracker run and
are never browser-cached, preventing old scores from being spoken after a restart.
The graph retains the original launch point, breaks lines at invalid samples or
large jumps, and distinguishes the last observed position, an estimated frame
exit, and an estimated landing at the model's ground reference (90% of frame height).
