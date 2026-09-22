"""
Watches the audio chunk directory for new WAV files and transcribes each
using faster-whisper, appending timestamped lines to the transcript file.
"""
import time
from pathlib import Path
from faster_whisper import WhisperModel
import torch

# Automatically use CUDA if available, otherwise use a lightweight CPU model
USE_CUDA = torch.cuda.is_available()
MODEL_SIZE = "small" if USE_CUDA else "base"
DEVICE = "cuda" if USE_CUDA else "cpu"
COMPUTE_TYPE = "float16" if USE_CUDA else "int8"


class Transcriber:
    def __init__(self, chunk_dir: Path, transcript_path: Path, stop_event, model_size: str = MODEL_SIZE):
        self.chunk_dir = chunk_dir
        self.transcript_path = transcript_path
        self.stop_event = stop_event
        self.model = WhisperModel(model_size, device=DEVICE, compute_type=COMPUTE_TYPE)
        self._seen = set()
        self._text_buffer = []

    def run(self):
        while not self.stop_event.is_set():
            chunks = sorted(self.chunk_dir.glob("chunk_*.wav"))
            # Skip the last chunk because ffmpeg may still be writing to it
            for wav in chunks[:-1] if len(chunks) > 1 else []:
                if wav in self._seen:
                    continue
                self._seen.add(wav)
                self._transcribe(wav)
            time.sleep(2)

    def _transcribe(self, wav_path: Path):
        try:
            segments, _ = self.model.transcribe(str(wav_path))
            text = " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as exc:
            text = ""
            print(f"Transcription error on {wav_path.name}: {exc}")

        if text:
            line = f"[{time.strftime('%H:%M:%S')}] {text}"
            self._text_buffer.append(line)
            with open(self.transcript_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            print(line)

    def recent_text(self, chars: int = 3000) -> str:
        joined = "\n".join(self._text_buffer)
        return joined[-chars:]