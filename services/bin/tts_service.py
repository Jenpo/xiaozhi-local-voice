#!/usr/bin/env python3
"""Minimal OpenAI-compatible TTS endpoint.

Engines (XZ_TTS_ENGINE):
  piper  - resident Piper (model loaded once) ~0.15s/sentence, offline, good quality
  say    - macOS `say` ~0.7s/sentence (process spawn dominates)
  kokoro - sherpa-onnx Kokoro ~1.2s/sentence (best quality)

xiaozhi's `OpenAITTS` provider POSTs {model,input,voice,response_format,speed}
and plays the returned WAV.
"""
import io
import json
import os
import subprocess
import tempfile
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENGINE = os.environ.get("XZ_TTS_ENGINE", "piper")
PIPER_VOICE = os.environ.get("XZ_TTS_PIPER_VOICE", "/Volumes/S/AI-Runtimes/xz/piper/en_US-amy-medium.onnx")
MODEL_DIR = os.environ.get("XZ_TTS_MODEL_DIR", "/Volumes/S/AI-Runtimes/xz/models/kokoro-en-v0_19")
SID = int(os.environ.get("XZ_TTS_SID", "1"))
FALLBACK_VOICE = os.environ.get("XZ_TTS_VOICE", "Samantha")
RATE = int(os.environ.get("XZ_TTS_RATE", "165"))
TOKEN = os.environ.get("XZ_TTS_TOKEN", "")
PORT = int(os.environ.get("XZ_TTS_PORT", "8880"))

_piper = None
_kokoro = None


def get_piper():
    global _piper
    if _piper is None:
        from piper import PiperVoice
        _piper = PiperVoice.load(PIPER_VOICE)
    return _piper


def wav_from_pcm(pcm, sample_rate):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def synth_piper(text, speed):
    voice = get_piper()
    chunks = list(voice.synthesize(text))
    if not chunks:
        raise RuntimeError("piper produced no audio")
    pcm = b"".join(c.audio_int16_bytes for c in chunks)
    return wav_from_pcm(pcm, chunks[0].sample_rate)


def get_kokoro():
    global _kokoro
    if _kokoro is None:
        import sherpa_onnx
        _kokoro = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=os.path.join(MODEL_DIR, "model.onnx"),
                    voices=os.path.join(MODEL_DIR, "voices.bin"),
                    tokens=os.path.join(MODEL_DIR, "tokens.txt"),
                    data_dir=os.path.join(MODEL_DIR, "espeak-ng-data"),
                ),
                num_threads=4, provider="cpu"),
            max_num_sentences=1))
    return _kokoro


def synth_kokoro(text, speed):
    import numpy as np
    audio = get_kokoro().generate(text, sid=SID, speed=float(speed))
    pcm = np.clip(np.asarray(audio.samples, dtype=np.float32), -1.0, 1.0)
    return wav_from_pcm((pcm * 32767.0).astype("<i2").tobytes(), audio.sample_rate)


def synth_say(text, voice, speed):
    with tempfile.TemporaryDirectory() as tmp:
        aiff = os.path.join(tmp, "a.aiff")
        wav = os.path.join(tmp, "a.wav")
        rate = int(RATE * max(0.5, min(2.0, float(speed))))
        subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", aiff, text], check=True, timeout=60)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@24000", "-c", "1", aiff, wav], check=True, timeout=60)
        with open(wav, "rb") as handle:
            return handle.read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self._json(200, {"ok": True, "engine": ENGINE})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") not in ("/v1/audio/speech", "/audio/speech"):
            self._json(404, {"error": "not found"})
            return
        if TOKEN and self.headers.get("Authorization", "") != "Bearer " + TOKEN:
            self._json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            text = body.get("input") or body.get("text") or ""
            speed = float(body.get("speed") or 1.0)
            data = None
            for engine in [ENGINE, "say"]:
                try:
                    if engine == "piper":
                        data = synth_piper(text, speed)
                    elif engine == "kokoro":
                        data = synth_kokoro(text, speed)
                    else:
                        data = synth_say(text, body.get("voice") or FALLBACK_VOICE, speed)
                    break
                except Exception as exc:  # noqa: BLE001
                    print("%s failed: %r" % (engine, exc), flush=True)
            if data is None:
                raise RuntimeError("all TTS engines failed")
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": str(exc)})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("xz-tts listening on 0.0.0.0:%d engine=%s" % (PORT, ENGINE), flush=True)
    server.serve_forever()
