"""
Captures the system's meeting audio (PulseAudio / PipeWire monitor source)
into sequential ~10s WAV chunks for the transcriber to pick up.
"""
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

CHUNK_SECONDS = 10
MONITOR_SOURCE = "default.monitor"


class AudioCapture:
    def __init__(self, monitor_source: str = MONITOR_SOURCE):
        self.monitor_source = monitor_source
        self.chunk_dir = Path(tempfile.mkdtemp(prefix="meeting_audio_"))
        self._proc = None

    def start(self):
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found. Install it via: sudo apt install ffmpeg")

        pattern = str(self.chunk_dir / "chunk_%05d.wav")
        cmd = [
            "ffmpeg", "-y",
            "-f", "pulse", "-i", self.monitor_source,
            "-ar", "16000", "-ac", "1",
            "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
            "-reset_timestamps", "1",
            pattern,
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)

    def stop(self):
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

        # Clean up temporary WAV directory
        if self.chunk_dir.exists():
            shutil.rmtree(self.chunk_dir, ignore_errors=True)