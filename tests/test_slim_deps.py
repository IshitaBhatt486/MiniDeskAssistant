"""The replacements for scipy, faster-whisper and the anthropic SDK (20 Nov 2026). No network: Claude is a local fake."""

import io
import itertools
import json
import os
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import numpy as np

import deskbot  # noqa: F401
from deskbot.assistant import claude_http, stt
from deskbot.assistant.brain import ClaudeBrain
from deskbot.companion.calibration import level_matrix
from deskbot.vision.lap_compat import linear_sum_assignment


class TestHungarian(unittest.TestCase):
    def brute(self, c):
        n, m = c.shape
        if n <= m:
            return min(sum(c[i, p[i]] for i in range(n)) for p in itertools.permutations(range(m), n))
        return self.brute(c.T)

    def test_optimal_on_random_and_tied_matrices(self):
        rng = np.random.default_rng(3)
        for t in range(400):
            n, m = rng.integers(1, 7, 2)
            c = rng.uniform(0, 1, (n, m)) if t % 2 else rng.integers(0, 3, (n, m)).astype(float)
            r, k = linear_sum_assignment(c)
            self.assertEqual(len(r), min(n, m))
            self.assertEqual(len(set(r)), len(r))
            self.assertEqual(len(set(k)), len(k))
            self.assertTrue(np.all(np.diff(r) > 0))                     # rows sorted, like scipy
            self.assertAlmostEqual(c[r, k].sum(), self.brute(c), places=9)

    def test_empty(self):
        r, k = linear_sum_assignment(np.zeros((0, 3)))
        self.assertEqual((len(r), len(k)), (0, 0))


class TestLevelMatrix(unittest.TestCase):
    def test_gravity_goes_to_plus_z_with_a_proper_rotation(self):
        rng = np.random.default_rng(4)
        for v in [*rng.normal(size=(200, 3)), np.array([0, 0, 9.8]), np.array([0, 0, -9.8]), np.array([1e-9, 0, -1])]:
            r = level_matrix(v)
            np.testing.assert_allclose(r @ (v / np.linalg.norm(v)), [0, 0, 1], atol=1e-9)
            np.testing.assert_allclose(r @ r.T, np.eye(3), atol=1e-9)
            self.assertAlmostEqual(np.linalg.det(r), 1.0, places=9)


def wav(samples, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


class TestWhisperCpp(unittest.TestCase):
    def test_wav_decoding_and_resampling(self):
        tone = 0.5 * np.sin(np.arange(8000) / 8000 * 2 * np.pi * 440)
        a = stt.wav_to_float(wav(tone, rate=8000))
        self.assertEqual(a.dtype, np.float32)
        self.assertAlmostEqual(len(a), 16000, delta=2)                  # 1 s at 16 kHz
        self.assertAlmostEqual(float(np.abs(a).max()), 0.5, delta=0.01)

    def test_trim_silence_keeps_a_margin(self):
        a = np.concatenate([np.zeros(32000), 0.3 * np.ones(16000), np.zeros(32000)]).astype(np.float32)
        t = stt.trim_silence(a)
        self.assertAlmostEqual(len(t), 16000 + 2 * 4000, delta=320)      # 1 s of sound + 0.25 s each side
        self.assertEqual(len(stt.trim_silence(np.zeros(32000, np.float32))), 0)

    def test_model_name_and_transcription(self):
        w = stt.WhisperCpp("tiny.en")
        self.assertEqual(w.model_name, "tiny.en-q8_0")
        self.assertEqual(stt.WhisperCpp("base.en-q5_1").model_name, "base.en-q5_1")
        seen = {}

        class Seg:
            def __init__(self, text):
                self.text = text

        class FakeModel:
            def transcribe(self, audio):
                seen["audio"] = audio
                return [Seg(" Hey Pip, "), Seg("turn left. ")]

        w._model = FakeModel()
        speech = np.concatenate([np.zeros(16000), 0.3 * np.sin(np.arange(16000) / 10), np.zeros(16000)])
        self.assertEqual(w.transcribe(wav(speech)), "Hey Pip, turn left.")
        self.assertLess(len(seen["audio"]), 48000)                       # silence trimmed before Whisper
        self.assertEqual(w.transcribe(wav(np.zeros(16000))), "")        # silence never reaches the model

    def test_backend_choice(self):
        with mock.patch.object(stt.WhisperCpp, "available", return_value=True):
            self.assertIsInstance(stt.local_backend("tiny.en"), stt.WhisperCpp)
        with mock.patch.object(stt.WhisperCpp, "available", return_value=False), \
                mock.patch.object(stt.LocalWhisper, "available", return_value=True):
            self.assertIsInstance(stt.local_backend("tiny.en"), stt.LocalWhisper)


class FakeClaude(BaseHTTPRequestHandler):
    script = []      # [(status, body dict, headers dict)]
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeClaude.seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        status, payload, headers = FakeClaude.script.pop(0)
        data = json.dumps(payload).encode()
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class TestClaudeHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeClaude)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeClaude.script, FakeClaude.seen = [], []
        self.env = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test", "ANTHROPIC_BASE_URL": self.url})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def client(self, **kw):
        return claude_http.Anthropic(max_retries=kw.pop("max_retries", 1), timeout=5.0, **kw)

    def test_request_shape_and_response_access(self):
        FakeClaude.script = [(200, {"id": "msg_1", "stop_reason": "tool_use",
                                    "usage": {"input_tokens": 12, "output_tokens": 3, "cache_read_input_tokens": 7},
                                    "content": [{"type": "tool_use", "id": "tu_1", "name": "get_time", "input": {}}]}, {})]
        r = self.client().beta.messages.create(model="claude-sonnet-5-5", max_tokens=10, betas=["a-1", "b-2"],
                                               fallbacks="default", messages=[{"role": "user", "content": "hi"}])
        req = FakeClaude.seen[0]
        self.assertEqual(req["path"], "/v1/messages")
        self.assertEqual(req["headers"]["x-api-key"], "sk-test")
        self.assertEqual(req["headers"]["anthropic-version"], claude_http.API_VERSION)
        self.assertEqual(req["headers"]["anthropic-beta"], "a-1,b-2")
        self.assertNotIn("betas", req["body"])
        self.assertEqual(req["body"]["fallbacks"], "default")
        self.assertEqual((r.stop_reason, r.usage.input_tokens, r.usage.cache_creation_input_tokens), ("tool_use", 12, None))
        block = r.content[0]
        self.assertEqual((block.type, block.name, block.id, block.input), ("tool_use", "get_time", "tu_1", {}))
        json.dumps({"role": "assistant", "content": r.content})          # sendable back as-is (tool loop)

    def test_bearer_token_when_no_api_key(self):
        FakeClaude.script = [(200, {"content": [], "usage": {}}, {})]
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": "tok"}):
            self.client().messages.create(model="m", max_tokens=1, messages=[])
        self.assertEqual(FakeClaude.seen[0]["headers"]["authorization"], "Bearer tok")
        self.assertNotIn("x-api-key", FakeClaude.seen[0]["headers"])

    def test_errors_map_to_sdk_classes(self):
        err = lambda t: {"type": "error", "error": {"type": t, "message": "nope"}}   # noqa: E731
        for status, cls in [(401, claude_http.AuthenticationError), (403, claude_http.PermissionDeniedError),
                            (404, claude_http.NotFoundError), (400, claude_http.APIStatusError)]:
            FakeClaude.script = [(status, err("x_error"), {})]
            with self.assertRaises(cls) as ctx:
                self.client(max_retries=0).messages.create(model="m", max_tokens=1, messages=[])
            self.assertEqual((ctx.exception.status_code, ctx.exception.type, ctx.exception.message), (status, "x_error", "nope"))

    def test_retries_429_and_5xx_then_succeeds(self):
        FakeClaude.script = [(529, {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}, {"retry-after": "0"}),
                             (200, {"content": [{"type": "text", "text": "ok"}], "usage": {}}, {})]
        r = self.client(max_retries=1).messages.create(model="m", max_tokens=1, messages=[])
        self.assertEqual(r.content[0].text, "ok")
        self.assertEqual(len(FakeClaude.seen), 2)
        FakeClaude.script = [(429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}}, {"retry-after": "0"})]
        with self.assertRaises(claude_http.RateLimitError):
            self.client(max_retries=0).messages.create(model="m", max_tokens=1, messages=[])
        FakeClaude.script = [(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}, {})]
        FakeClaude.seen = []
        with self.assertRaises(claude_http.APIStatusError):
            self.client(max_retries=3).messages.create(model="m", max_tokens=1, messages=[])
        self.assertEqual(len(FakeClaude.seen), 1)                        # 400 is never retried

    def test_connection_error(self):
        c = claude_http.Anthropic(base_url="http://127.0.0.1:9", max_retries=0, timeout=2.0)
        with self.assertRaises(claude_http.APIConnectionError):
            c.messages.create(model="m", max_tokens=1, messages=[])

    def test_brain_speaks_the_right_reason(self):
        cb = ClaudeBrain({})
        self.assertIs(cb._anthropic, claude_http)
        self.assertEqual(cb.classify_error(claude_http.AuthenticationError(401, "authentication_error", "x")), "my AI key was rejected")
        self.assertEqual(cb.classify_error(claude_http.RateLimitError(429)), "the AI is rate limiting me")
        self.assertEqual(cb.classify_error(claude_http.APIStatusError(529)), "the AI service had an error")
        self.assertEqual(cb.classify_error(claude_http.APIConnectionError("x")), "I can't reach the internet")


if __name__ == "__main__":
    unittest.main()
