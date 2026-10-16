"""Free text-to-speech backends.

edge:  (default) Microsoft Edge's online voices via edge-tts. Free and no key, but
       an unofficial endpoint, so it may change or rate-limit. Fine for experiments.
piper: open-source, runs offline on CPU. Downloads the voice model once (~60 MB).
       Optional install: pip install piper-tts
"""

from __future__ import annotations

import os
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Protocol

DEFAULT_VOICES = {"piper": "en_US-lessac-medium", "edge": "en-US-AriaNeural"}


class VoiceError(RuntimeError):
    pass


class Voice(Protocol):
    name: str

    def synthesize(self, text: str, out_stem: Path) -> Path:
        """Speak `text` into out_stem.<ext> and return the file written."""
        ...


def _to_mp3(wav: Path) -> Path:
    """Compress to mp3 when ffmpeg is available; otherwise keep the wav."""
    if not shutil.which("ffmpeg"):
        return wav
    mp3 = wav.with_suffix(".mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1", "-b:a", "64k", str(mp3)],
        check=True,
    )
    wav.unlink()
    return mp3


class PiperVoice:
    def __init__(self, name: str = DEFAULT_VOICES["piper"], voices_dir: Path = Path("voices"),
                 length_scale: float = 1.0):
        self.name = name
        self.voices_dir = voices_dir
        self.length_scale = length_scale  # >1 speaks slower, <1 faster
        self._voice = None

    def _load(self):
        if self._voice is None:
            try:
                from piper import PiperVoice as _Piper
            except ImportError as e:
                raise VoiceError("Piper is not installed; run: pip install piper-tts") from e
            from piper.download_voices import download_voice

            model = self.voices_dir / f"{self.name}.onnx"
            if not model.exists():
                self.voices_dir.mkdir(parents=True, exist_ok=True)
                print(f"[voice] downloading Piper voice {self.name} (one time)")
                download_voice(self.name, self.voices_dir)
            self._voice = _Piper.load(model)
        return self._voice

    def synthesize(self, text: str, out_stem: Path) -> Path:
        from piper.config import SynthesisConfig

        wav = out_stem.with_suffix(".wav")
        with wave.open(str(wav), "wb") as f:
            self._load().synthesize_wav(text, f, syn_config=SynthesisConfig(length_scale=self.length_scale))
        return _to_mp3(wav)


class EdgeVoice:
    def __init__(self, name: str = DEFAULT_VOICES["edge"], rate: str = "+0%"):
        self.name = name
        self.rate = rate  # e.g. "-10%" slower, "+10%" faster

    def synthesize(self, text: str, out_stem: Path) -> Path:
        import asyncio

        import edge_tts

        mp3 = out_stem.with_suffix(".mp3")
        _trust_env_ca(edge_tts)
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        try:
            asyncio.run(edge_tts.Communicate(text, self.name, rate=self.rate, proxy=proxy).save(str(mp3)))
        except Exception as e:  # network refusals, rate limits, unknown voice names
            raise VoiceError(f"edge-tts could not reach Microsoft's voice service ({e}); "
                             "check network access to speech.platform.bing.com, or use --voice piper") from e
        return mp3


def _trust_env_ca(edge_tts) -> None:
    """edge-tts only trusts certifi's CAs. Behind a TLS-inspecting proxy (sandboxes,
    corporate networks) also trust the CA bundle named by SSL_CERT_FILE / REQUESTS_CA_BUNDLE."""
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    ctx = getattr(edge_tts.communicate, "_SSL_CTX", None)
    if ca and ctx is not None and os.path.exists(ca) and not getattr(ctx, "_coursegen_ca", False):
        ctx.load_verify_locations(cafile=ca)
        ctx._coursegen_ca = True


def get_voice(backend: str, name: str | None = None, speed: float = 1.0) -> Voice:
    """speed: 1.0 normal, 0.9 = 10% slower, 1.1 = 10% faster."""
    if backend == "piper":
        return PiperVoice(name or DEFAULT_VOICES["piper"], length_scale=1 / speed)
    if backend == "edge":
        return EdgeVoice(name or DEFAULT_VOICES["edge"], rate=f"{round((speed - 1) * 100):+d}%")
    raise ValueError(f"unknown voice backend: {backend}")


def duration_seconds(path: Path) -> float | None:
    if path.suffix == ".wav":
        with wave.open(str(path)) as f:
            return f.getnframes() / f.getframerate()
    if shutil.which("ffprobe"):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True,
        )
        try:
            return float(out.stdout.strip())
        except ValueError:
            return None
    return None
