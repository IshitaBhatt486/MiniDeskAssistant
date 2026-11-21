# Smaller dependencies: numpy instead of scipy, whisper.cpp, Claude over HTTPS (20 Nov 2026)

The second round of slimming, after [ncnn-detector.md](ncnn-detector.md) removed PyTorch and Ultralytics.
The robot's Python packages on the Pi:

| | Installed | Packages |
| --- | --- | --- |
| Before (PyTorch + Ultralytics) | 1,711 MB | 104 + MediaPipe |
| After the NCNN detector | 816 MB | 86 + MediaPipe |
| **Now** | **427 MB** (298 MB pip + 129 MB MediaPipe) | **61 + MediaPipe** |

Measured the same way as before: both sets installed for `aarch64-manylinux_2_28`, Python 3.11, with
`uv pip install --target`, then their file sizes added up.

| Replaced | By | Saved | Behaviour |
| --- | --- | --- | --- |
| scipy (120 MB) | ~40 lines of numpy | 120 MB | identical results |
| faster-whisper + CTranslate2 + onnxruntime + PyAV + tokenizers + Hugging Face hub (261 MB) | whisper.cpp through `pywhispercpp` (15 MB) | ~250 MB | same Whisper tiny.en model, 8-bit |
| `anthropic` SDK + pydantic + httpx2 + jiter … (~25 MB) | `deskbot/assistant/claude_http.py`, standard library | ~25 MB | same requests and errors |

Now 427 MB: MediaPipe 129, OpenCV headless + ncnn 106, matplotlib family 59, numpy 56, Pillow 22, whisper.cpp 15,
Vosk 8, everything else 34 (rich, questionary, bleak + dbus-fast, luma.oled, Adafruit MPU-6050 + Blinka, ahrs …).

## 1. scipy → numpy

scipy was used in exactly two places.

**Track matching**: `lap_compat.linear_sum_assignment()`. It replaces `scipy.optimize.linear_sum_assignment` with the
same contract: rows sorted ascending, `min(n, m)` pairs, rectangular matrices (transposed so rows ≤ columns). It's
the shortest-augmenting-path Hungarian algorithm with row/column potentials `u`, `v`. Each row is added in turn:
the reduced costs `a[i0] − u[i0] − v` update the per-column minimum `minv`, the cheapest free column is chosen,
the potentials shift by that minimum, and when a free column is reached the path recorded in `way` is flipped.
It's O(n²m), vectorised per row; the tracker's matrices are a few dozen at most. `lapjv()` (lap's `cost_limit`
padding) and `bytetrack.py` are unchanged on top of it.
Checked: the **same pairs as scipy** on 2,000 random float matrices up to 8×8, the same optimal total on 1,000 more
full of ties, and the brute-force tests in `tests/test_slim_deps.py` and `tests/test_mapping.py`. The ByteTrack test
against Ultralytics (`tests/test_ncnn_detector.py`) still passes with the same IDs.

**IMU calibration**: `calibration.level_matrix()`. It replaces `Rotation.align_vectors(z, g)` for one vector pair
with the shortest-arc rotation (Rodrigues): `R = I + sin θ·K + (1 − cos θ)·K²`, where `K` is the cross-product matrix of
the unit axis `g × z`. If gravity already points along +z, `R = I`; exactly upside down, it's 180° about x. Checked: the
same matrix as scipy within 5·10⁻¹⁵ on 500 random vectors; `R·g = +z`, `R·Rᵀ = I` and `det R = 1` in the tests.

## 2. faster-whisper → whisper.cpp

`deskbot/assistant/stt.py` `WhisperCpp` is the `local` speech-to-text backend whenever `pywhispercpp` is installed.
whisper.cpp is the C/C++ port of Whisper, with ARM NEON kernels: it is what most Raspberry Pi voice projects use.

- **Model:** the `local_whisper_model` setting (default `tiny.en`). A plain name gets its 8-bit version, `tiny.en-q8_0`
  (44 MB instead of 75 MB, about the same accuracy, faster on the Pi's Cortex-A72). A name that already has
  `-q…` or ends in `.bin` is used as given. It downloads once into `run_prototype/models/whisper/`, which
  `tools/deploy.sh` keeps.
- **Call:** `Model(name, models_dir=models/whisper, n_threads=2, print_progress=False, print_realtime=False,
  redirect_whispercpp_logs_to=None)`, loaded on first use and kept. Then `model.transcribe(float32 samples)` with greedy
  decoding (the default, sampling strategy 0), and the segment texts are joined. Two threads leave the other cores
  to the camera and the safety loop, as before.
- **Audio:** `wav_to_float()` reads the 16-bit WAV with the standard `wave` module (mixes to mono, resamples to 16 kHz by
  linear interpolation if needed). No ffmpeg or PyAV.
- **Silence:** `trim_silence()` stands in for faster-whisper's VAD filter, because Whisper tends to invent words in long
  silences. It uses 20 ms frames: everything before the first and after the last frame louder than −45 dBFS is cut,
  keeping 0.25 s of margin. Under 0.3 s of sound left → `""` without calling the model. (Clips peaking below −50 dBFS
  were already rejected earlier.)
- **One at a time:** a lock, as before. The wake-word fallback in `full/wake.py` uses the same backend.
- **Fallback:** `local_backend()` uses whisper.cpp, or the old `LocalWhisper` (faster-whisper) if only that is
  installed, so an older setup keeps working until `setup.sh` runs.

**Not measured on the Pi yet.** Windows Smart App Control blocks `pywhispercpp`'s DLL on the laptop (the same as
ncnn and faster-whisper). The tests check the audio handling, model naming, backend choice and joining of segments
with a fake model, and the `pywhispercpp` API was read from the installed package (1.5.1). On the Pi:
`python main.py full`, say something, and the log shows the time per clip.

## 3. anthropic SDK → `claude_http.py`

The robot used four things from the SDK: `client.beta.messages.create(...)`, attribute access on the response
(`resp.stop_reason`, `resp.usage.input_tokens`, `block.type/.text/.name/.input/.id`), sending `resp.content` back
in the tool loop, and the error classes. `claude_http.py` provides exactly these with the same names, so `brain.py`
(`self._anthropic = claude_http`), `buddy/notify.py` and `full/reader.py` didn't change their calls.

- `POST {ANTHROPIC_BASE_URL or https://api.anthropic.com}/v1/messages`; JSON body = every keyword argument except
  `betas`.
- Headers: `x-api-key: $ANTHROPIC_API_KEY`, or `Authorization: Bearer $ANTHROPIC_AUTH_TOKEN` if only that is set (same
  order as the SDK); `anthropic-version: 2026-10-21` (what the SDK it replaces, anthropic 2.8.0, sent);
  `anthropic-beta: a,b` from `betas=[...]` (used for the server-side refusal fallback on non-Haiku models).
- Response: JSON turned into `Obj`, a `dict` subclass with attribute access, where a missing key reads as `None`
  (like the SDK's optional fields). Because blocks are still plain dicts, `{"role": "assistant", "content": resp.content}`
  is sent back exactly as received.
- Errors: the body `{"type": "error", "error": {"type", "message"}}` becomes `AuthenticationError` (401),
  `PermissionDeniedError` (403), `NotFoundError` (404), `RateLimitError` (429) or `APIStatusError` (others), each with
  `.status_code`, `.type`, `.message`. Network failures and timeouts become `APIConnectionError`.
  `ClaudeBrain.classify_error` works unchanged.
- Retries, like the SDK: 408, 409, 429, ≥ 500 and connection errors, `max_retries` times (the brain uses 1). The wait
  is `retry-after-ms` / `retry-after` (capped at 8 s), else 0.5 s doubled each time; `x-should-retry` overrides.
  400-type errors are never retried. Timeout per attempt: the client's `timeout` (40 s in the brain).
- It always loads (standard library only). So the "anthropic SDK can't load" problem on the laptop (Smart App Control
  blocking `jiter`'s DLL) is gone, and the brain tests that used to be skipped there now run.

Checked in `tests/test_slim_deps.py` against a local fake server (no real API calls): path and headers, `betas` as a
header and not in the body, bearer auth, attribute access, re-sending content, every error class, retry on 529 then
success, no retry on 400, connection error, and the spoken reason for each error.

## setup.sh removes the old packages

`scripts/setup.sh` keeps one list, `REMOVED_PKGS`, of every package the old install had and the new one doesn't, and
uninstalls whichever of them are in `run_prototype/.venv` (`pip list --local`; Linux only; with or without
`--no-vision`), then runs `pip cache purge`. The list was made by installing both sets for the Pi and comparing:

- first round: torch, torchvision, ultralytics (+ thop, platform), lap, polars (+ runtime), opencv-python, sympy,
  mpmath, networkx, psutil, jinja2, markupsafe, httpx, httpcore, nvidia-*, triton
- this round: scipy, anthropic, faster-whisper, ctranslate2, onnxruntime, av, tokenizers, huggingface-hub, hf-xet,
  pydantic, pydantic-core, annotated-types, typing-inspection, jiter, docstring-parser, anyio, sniffio, h11, httpx2,
  httpcore2, truststore, filelock, fsspec, pyyaml, click, protobuf, opentelemetry-api

Checked: the list matches every package only the old install had, except `setuptools` (kept for pip). It matches none
of the 61 packages in the new install, and no `deskbot` module imports any of them. Every module still imports, and
none of them is loaded, with all of them made unimportable. MediaPipe (installed with `--no-deps`) needs absl-py,
certifi, numpy, flatbuffers and matplotlib, which are all still installed; it doesn't need protobuf in this version.
