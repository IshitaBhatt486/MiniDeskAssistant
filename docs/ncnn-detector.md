# YOLO26n on NCNN without PyTorch (20 Nov 2026)

The robot now runs the detector straight on NCNN, with ByteTrack rewritten in numpy. **PyTorch, torchvision,
Ultralytics, `lap` and the full-GUI OpenCV are no longer installed on the robot.** The installed Python packages
went from **1.71 GB to 0.82 GB**. The detections, track IDs and boxes are the same as before: they were checked frame
by frame against Ultralytics.

| File | What |
| --- | --- |
| `run_prototype/deskbot/vision/ncnn_detector.py` | **new**: letterbox → NCNN → NMS → un-letterbox → ByteTrack (`NcnnDetector`) |
| `run_prototype/deskbot/vision/bytetrack.py` | **new**: ByteTrack + Kalman filter in numpy, settings from `bytetrack.yaml` |
| `run_prototype/deskbot/vision/detector.py` | `make_detector()` picks NcnnDetector (NCNN folder) or the old Ultralytics `YoloDetector` (`.pt`) |
| `run_prototype/deskbot/vision/model.py` | no PyYAML; `NoModel` error with the fix; export only where Ultralytics is installed |
| `run_prototype/scripts/export-model.sh` | exports in a **temporary venv** that is deleted afterwards, then benchmarks |
| `run_prototype/scripts/setup.sh` | installs `requirements-vision.txt` (ncnn, opencv-python-headless, scipy); removes the old packages |
| `tests/test_ncnn_detector.py` | 11 tests, including the frame-by-frame match against Ultralytics |

The old `YoloDetector` is kept unchanged. It's what a laptop with Ultralytics uses when it only has the `.pt`
weights (Windows Smart App Control blocks the NCNN DLL and the PNNX converter there).

## What runs per frame

All of this replaces what `model.track(persist=True)` did inside Ultralytics 8.4.213. Each step mirrors Ultralytics'
own code, so the results are identical, not just similar.

1. **Letterbox** (`letterbox()`). `r = min(320/h, 320/w)`, resize to `round(w·r) × round(h·r)` with
   `cv2.INTER_LINEAR` (skipped when the size already fits), pad to **320 × 320** with grey 114, image centred (padding
   `round(d − 0.1)` before, `round(d + 0.1)` after). BGR → RGB, HWC → CHW, ÷ 255 as float32. A 320×240 camera frame
   gets 40 px of padding top and bottom. Ultralytics uses the full square for NCNN models: its smaller
   "multiple of 32" rectangle only applies to PyTorch or dynamic exports.
2. **Network** (`NcnnRunner`). `ncnn.Net` with `use_vulkan_compute = False` and `opt.num_threads = VisionConfig.threads`
   (3; the camera process uses `RuntimeConfig.camera_threads` = 1), loading `model.ncnn.param` + `.bin`. One extractor
   per frame: input `in0` (the first input name), output = the first of the sorted output names (Ultralytics does
   the same to work around a PNNX naming issue). Output: **(84, 2100)**, which is cx, cy, w, h in input pixels plus
   80 class scores (sigmoid already applied) for each of 40² + 20² + 10² anchors.
   YOLO26's NMS-free ("end2end") head is **not** in the NCNN export: Ultralytics turns it off for NCNN, because NCNN
   has no top-k. So step 3 is needed. `decode()` also accepts an end2end output `(K, 6)` in case a future export keeps it.
3. **NMS** (`decode()`, `nms()`). Best class per anchor; keep score > `VisionConfig.conf` (0.10, strict `>`);
   optional class filter; at most 30,000 candidates; boxes to x1y1x2y2; **class-aware** greedy NMS (boxes offset
   by class × 7680 so different classes never suppress each other) at **IoU 0.5** (Ultralytics' predict default);
   at most 300 boxes.
4. **Back to the image.** Subtract the padding, divide by `r`, clip to the frame.
5. **ByteTrack** (`bytetrack.py`, settings in `bytetrack.yaml`: high 0.35, low 0.1, new track 0.45, buffer 45 frames,
   match 0.8, fuse_score on):
   - split the boxes into high (≥ 0.35) and low (0.1–0.35) scores; boxes with zero width or height are ignored
   - Kalman-predict every tracked and lost track. The state is (cx, cy, aspect, h) plus velocities, with
     position/velocity noise weights 1/20 and 1/160 of the height. A lost track's height velocity is zeroed.
   - match tracks to high boxes by Hungarian assignment on `1 − IoU × score`, gated at 0.8
   - match the remaining *tracked* tracks to low boxes on `1 − IoU`, gated at 0.5; tracks still unmatched become lost
   - unconfirmed tracks (seen once) may match the leftover high boxes (gate 0.7), otherwise they are removed
   - leftover high boxes scoring ≥ 0.45 start new tracks. A new track is confirmed when it's seen a second time
     (or straight away on the very first frame).
   - lost for more than 45 frames → removed. A tracked/lost pair overlapping at IoU > 0.85 keeps the older track.
   - the output boxes are the tracks' Kalman boxes, clipped to the frame; the score is the latest detection's
   - if no track is output but an unconfirmed one exists, the frame returns nothing (Ultralytics hides new tracks
     until they're confirmed). If there are no tracks at all, the raw detections are returned with `track_id = None`.

   Hungarian assignment uses scipy through `lap_compat.lapjv()`. It pads the cost matrix the way `lap.lapjv` does
   with `cost_limit`, so it picks exactly the matches the `lap` package picked.
6. `predict()` runs steps 1–4 only (benchmarks, mAP); `reset()` clears the tracker (map cleared);
   `warmup()` runs the network twice so NCNN has allocated its memory before anything is timed.

Class names come from the export's `metadata.yaml`, read with a few regular expressions (no PyYAML), or else from
`coco.NAMES`.

## Making the model: `scripts/export-model.sh`

Exporting still needs PyTorch + Ultralytics + PNNX, but only once. The script:

1. asks the robot's venv for `model_name` / `imgsz` and whether `models/yolo26n_ncnn_model` already exists
   (skips the export unless `--force`)
2. creates `~/.cache/deskbot-export-venv` with the system Python and installs CPU-only torch/torchvision (Linux,
   from download.pytorch.org/whl/cpu) and `ultralytics>=8.4.0`, with `--no-cache-dir`. `TMPDIR` points at
   `~/.cache/pip-tmp`, because `/tmp` on Raspberry Pi OS is a small RAM disk.
3. downloads `yolo26n.pt`, runs `model.export(format="ncnn", imgsz=320)`, moves the result to
   `models/yolo26n_ncnn_model/`, and copies Ultralytics' `bus.jpg` to `models/sample.jpg` (for `model bench` and the tests)
4. deletes the temporary venv and pip's temp folder (`--keep` keeps the venv, ~1 GB, so a later export is quicker)
5. runs `python -m deskbot model bench` in the robot's venv: ncnn + numpy only

It needs internet and about 1.5 GB of free space while it runs. It refuses to run on Windows (PNNX is blocked
there). `scripts/setup.sh` calls it unless `--no-model` or `--no-vision` is given.

If the model is missing at start-up, `resolve_model()` raises `NoModel("... bash scripts/export-model.sh")`. The camera
process and the dashboard catch it and log **"Vision disabled: …"**, and the rest of the robot keeps running.
`main.py doctor` shows the model as missing, with the same command.

## Upgrading a Pi that was installed the old way

`scripts/setup.sh` (or `tools/deploy.sh … --install`), with or without `--no-vision`, removes every package the old
install had and the new one doesn't: `torch`, `torchvision`, `ultralytics`, `ultralytics-thop`, `ultralytics-platform`,
`lap`, `polars`, `polars-runtime-32`, `opencv-python`, `sympy`, `mpmath`, `networkx`, `psutil`, `jinja2`, `markupsafe`,
`httpx`, `httpcore`, `nvidia-*`, `triton` (nothing left needs them; anthropic now uses `httpx2`) from `run_prototype/.venv`,
then `pip cache purge` drops the cached wheels. It only removes packages installed
in that venv (`pip list --local`), never apt ones. Then it installs `opencv-python-headless`. The two OpenCV packages
share the `cv2/` folder, so headless is force-reinstalled if `opencv-python` was just removed. The cleanup only runs on
Linux, in `run_prototype/.venv`: the laptop's top-level `.venv` keeps Ultralytics for the tools and benchmarks.
An existing `models/yolo26n_ncnn_model` is reused as it is.

## Size (Raspberry Pi, aarch64, Python 3.11)

Measured by installing both package sets for the Pi's platform into empty folders with
`uv pip install --target … --python-platform aarch64-manylinux_2_28 --python-version 3.11` and adding up the file
sizes. That's what lands in `.venv/lib/python3.11/site-packages`.

| | Before | After |
| --- | --- | --- |
| pip packages (requirements*.txt + CPU torch/torchvision) | 1,582 MB, 104 packages | **687 MB, 86 packages** |
| MediaPipe (`--no-deps`, same in both) | 129 MB | 129 MB |
| **Total** | **1,711 MB** | **816 MB** (−895 MB, −52 %) |

Removed: torch 625 MB, polars 172 MB, opencv-python 136 MB (replaced by opencv-python-headless 93 MB), sympy 27 MB,
networkx 7 MB, torchvision 7 MB, ultralytics 5 MB, setuptools 3 MB, lap 3 MB, mpmath 2 MB and 9 smaller packages.

What the 816 MB is now:

| Feature | Packages | MB |
| --- | --- | --- |
| Speech to text | faster-whisper, ctranslate2, onnxruntime, av, tokenizers, huggingface-hub, hf-xet | 261 |
| Vision | scipy 120, opencv-python-headless 93, ncnn 13 | 226 |
| Hand gestures | mediapipe | 129 |
| Figures | matplotlib, fonttools, kiwisolver, contourpy … | 58 |
| numpy | | 56 |
| Pillow | | 21 |
| Claude | anthropic, pydantic, httpx … | 17 |
| Wake word | vosk | 8 |
| Everything else | rich, questionary, bleak + dbus-fast, luma.oled, Adafruit MPU-6050 + Blinka, ahrs, protobuf … | 41 |

Not included: the apt packages (picamera2, gpiozero, espeak-ng …), which aren't installed by pip; the code in
`run_prototype/` (1.5 MB); and the model files, which are downloaded on first use (YOLO26n NCNN ~10 MB, face models
39 MB, gesture model 8 MB, Vosk wake word 40 MB, Whisper tiny.en ~75 MB).

## Verified (laptop, 20 Nov 2026)

- **Same output as Ultralytics.** `tests/test_ncnn_detector.py::TestMatchesUltralytics` runs the same network
  through PyTorch with the end2end head off (exactly what the NCNN export contains) as the "runner". It compares 60
  frames: a pan and zoom over `bus.jpg` and `zidane.jpg` at 320×240, with blank frames at 12–14 and 22 so tracks are
  lost and found again. Each frame is checked against Ultralytics' `predict()` and `track(persist=True)` with the same
  `bytetrack.yaml`, and gives the same classes, scores (4 decimals), boxes (±0.01 px) and track IDs. The first run of
  the comparison found two differences, both fixed: Ultralytics letterboxes NCNN models to the full square, and it
  clips track boxes to the frame.
- The numpy pieces have their own tests: metadata without PyYAML, tracker settings, letterbox padding, class-aware NMS,
  greedy NMS against brute force, a track surviving a gap and expiring after the buffer, low-score boxes continuing
  but never starting a track, the detector end-to-end with a fake network, and `make_detector`.
- **With torch, torchvision, ultralytics, lap and yaml made unimportable**, every `deskbot` module imports, none of
  them gets loaded, `resolve_model` and `export_model` raise `NoModel` with the fix, and `doctor` reports ncnn ✓,
  scipy ✓ and "model not exported → bash scripts/export-model.sh".
- Whole suite: 345 passed, 1 skipped (the real-NCNN test, which needs the Pi).

**Not run on the Pi yet.** On the robot: `bash scripts/setup.sh` (removes the old packages and exports the model),
then `bash scripts/export-model.sh` prints the NCNN timing, then `bash scripts/sensors.sh detect` shows it live.
The real NCNN runner (`NcnnRunner`) is the only part that couldn't run on Windows.
