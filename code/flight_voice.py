"""Server-only ElevenLabs narration; credentials and audio stay in memory."""
import json
import os
import subprocess
import sys
import threading
from collections import OrderedDict
from functools import lru_cache
from uuid import uuid4
from urllib.error import HTTPError
from urllib.request import Request, urlopen


@lru_cache(maxsize=1)
def keychain_api_key():
    if sys.platform != "darwin":
        return ""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "skytrace.elevenlabs", "-a", "api-key", "-w"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def get_api_key():
    return os.environ.get("ELEVENLABS_API_KEY") or keychain_api_key()


def score_commentary(score):
    score = max(0, min(100, round(float(score))))
    if score >= 90:
        feedback = "Outstanding! That was an exceptionally smooth flight."
    elif score >= 75:
        feedback = "Great flight! Your plane stayed impressively smooth."
    elif score >= 50:
        feedback = "Nice effort! There was some wobble in the visible flight. Try a gentle, steady release."
    elif score >= 25:
        feedback = "A bumpy ride! Try a steadier release and check that both wings are even."
    else:
        feedback = "Let's try again! The visible flight was rough, or there wasn't enough tracking data to judge it."
    return f"Flight complete. Smoothness score: {score} out of 100. {feedback}"


class FlightVoice:
    def __init__(self):
        self._lock = threading.Lock()
        self._records = OrderedDict()
        self.session_id = uuid4().hex

    def snapshot(self, flight_id):
        with self._lock:
            return dict(self._records.get(flight_id, {"status": "idle"}),
                        configured=bool(get_api_key()))

    def request(self, flight_id, score):
        with self._lock:
            if flight_id in self._records:
                return  # One API request per flight, even across multiple browsers.
            self._records[flight_id] = {"status": "generating", "flight_id": flight_id,
                                        "score": max(0, min(100, round(float(score)))),
                                        "session_id": self.session_id, "text": score_commentary(score)}
            while len(self._records) > 12:
                self._records.popitem(last=False)
        threading.Thread(target=self._generate, args=(flight_id,), daemon=True).start()

    def _generate(self, flight_id):
        with self._lock:
            record = self._records.get(flight_id)
            if record is None:
                return
            text = record["text"]
        key = get_api_key()
        result = {"status": "error", "error": "Start the tracker with an ElevenLabs API key to enable speech."}
        if key:
            voice = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
            request = Request(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
                data=json.dumps({"text": text, "model_id": "eleven_multilingual_v2"}).encode(),
                headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=20) as response:
                    audio = response.read(5_000_001)
                if not audio or len(audio) > 5_000_000:
                    raise ValueError("Invalid audio")
                result = {"status": "ready", "audio_url": f"/api/voice/{self.session_id}/{flight_id}.mp3", "audio": audio}
            except HTTPError as error:
                message = {
                    401: "ElevenLabs rejected the key. Check or replace it.",
                    403: "Check the key's Text to Speech permission and access to this voice.",
                    429: "ElevenLabs quota or rate limit reached. Text feedback is still available.",
                }.get(error.code, "ElevenLabs is unavailable. Text feedback is still available.")
                result = {"status": "error", "error": message}
            except Exception:
                result = {"status": "error", "error": "Speech unavailable. Check your internet connection. Text feedback still works."}
        with self._lock:
            if flight_id in self._records:
                self._records[flight_id].update(result)

    def public_snapshot(self, flight_id):
        return {key: value for key, value in self.snapshot(flight_id).items() if key != "audio"}

    def audio(self, flight_id):
        with self._lock:
            return self._records.get(flight_id, {}).get("audio")
