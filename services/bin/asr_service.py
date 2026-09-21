#!/usr/bin/env python3
"""Minimal OpenAI-compatible ASR endpoint backed by sherpa-onnx SenseVoice.

Runs the same small SenseVoice model the NAS xiaozhi server used, but on the
Mac mini M4 (Metal/CPU) so local speech recognition is ~10x faster than the
NAS Celeron. xiaozhi's `OpenaiASR` provider POSTs multipart audio here and reads
{"text": ...}.
"""
import email
import io
import json
import os
import wave
from email import policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import sherpa_onnx

MODEL_DIR = os.environ.get(
    "XZ_ASR_MODEL_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "models",
                 "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"),
)
TOKEN = os.environ.get("XZ_ASR_TOKEN", "")
PORT = int(os.environ.get("XZ_ASR_PORT", "8879"))
THREADS = int(os.environ.get("XZ_ASR_THREADS", "4"))

LANG = os.environ.get("XZ_ASR_LANG", "en")

recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
    model=os.path.join(MODEL_DIR, "model.int8.onnx"),
    tokens=os.path.join(MODEL_DIR, "tokens.txt"),
    num_threads=THREADS,
    use_itn=True,
    language=LANG,
)


def wave_to_16k_mono(payload):
    with wave.open(io.BytesIO(payload)) as f:
        rate = f.getframerate()
        channels = f.getnchannels()
        width = f.getsampwidth()
        frames = f.readframes(f.getnframes())
    if width != 2:
        raise ValueError("only 16-bit PCM WAV is supported")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels == 2:
        samples = samples.reshape(-1, 2).mean(axis=1)
    if rate != 16000:
        target = int(len(samples) * 16000 / rate)
        samples = np.interp(
            np.linspace(0, len(samples), target, endpoint=False),
            np.arange(len(samples)),
            samples,
        ).astype(np.float32)
    return samples


def extract_audio(body, content_type):
    message = email.message_from_bytes(
        b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body,
        policy=policy.default,
    )
    fallback = None
    for part in message.iter_parts():
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        if part.get_filename():
            return payload
        fallback = fallback or payload
    if fallback:
        return fallback
    raise ValueError("no audio part in request")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", "/v1/health"):
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") not in ("/v1/audio/transcriptions", "/audio/transcriptions"):
            self._send(404, {"error": "not found"})
            return
        if TOKEN and self.headers.get("Authorization", "") != "Bearer " + TOKEN:
            self._send(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            payload = extract_audio(body, self.headers.get("Content-Type", ""))
            samples = wave_to_16k_mono(payload)
            stream = recognizer.create_stream()
            stream.accept_waveform(16000, samples)
            recognizer.decode_stream(stream)
            self._send(200, {"text": stream.result.text})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"error": str(exc)})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("xz-asr listening on 0.0.0.0:%d" % PORT, flush=True)
    server.serve_forever()
