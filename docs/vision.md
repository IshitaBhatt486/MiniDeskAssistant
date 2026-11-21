# Vision: Pi camera + YOLO26n (NCNN) + ByteTrack (15 Nov 2026)

Detects and tracks objects on the desk with the Raspberry Pi camera, **entirely on the Pi**: no cloud, no API keys, no
per-call cost. The detections feed the semantic map and the confidence heatmap ([fusion.md](fusion.md)).

| | |
| --- | --- |
| Code | `deskbot/vision/`: `camera.py` (sources + latest-frame grabber), `detector.py` (YOLO + ByteTrack, sim detector), `pipeline.py` (threads, stats, JPEG), `geometry.py` (pixel ↔ desk), `model.py` (download / NCNN export / benchmark), `bytetrack.yaml`, `lap_compat.py` |
| Config | `deskbot/config.py` → `CameraConfig`, `VisionConfig` |
| Install | `scripts/setup.sh` (system camera packages, venv, NCNN + OpenCV, model export in a temporary venv) |
| Since 20 Nov 2026 | the robot runs NCNN directly with ByteTrack in numpy, no PyTorch/Ultralytics: [ncnn-detector.md](ncnn-detector.md). The Ultralytics notes below still describe the export and the laptop's `.pt` fallback |
| Try it | `scripts/sensors.sh detect` (live in the terminal) · `scripts/start.sh` (dashboard Camera card) · `scripts/export-model.sh` (export + benchmark) |

---

## 1. Research behind the choices (brief)

| Choice | Why |
| --- | --- |
| **YOLO26n** | Smallest YOLO26 model, ~2.4 M parameters / 1.3 GFLOPs. YOLO26 is end-to-end (**NMS-free**), so there is no NMS post-processing step on the CPU |
| **NCNN** (yes, it's the right framework here) | Ultralytics' Raspberry Pi guide says NCNN gives the best inference performance on Pi, because it is optimised for ARM (NEON, fp16 storage). Its table lists YOLO26n NCNN at ~67 ms on a **Pi 5** at 640 px, matching Arm's learning path (67.2 ms). ONNX was measured roughly 2× slower in an independent Pi 5 study |
| **imgsz 320** instead of 640 | 4× fewer pixels. On a Pi 4 (about 2–3× slower than a Pi 5) 640 px would be ~150–200 ms; 320 px brings it into the tens of ms. Desk objects at < 1.5 m are large in the frame, so 320 loses little. Export and runtime use the same size |
| **ByteTrack** via Ultralytics `model.track(persist=True, tracker=...)` | `persist=True` keeps the tracker state between per-frame calls (one tracker per camera). The tracker is set explicitly, because Ultralytics' default tracker has changed between versions. ByteTrack is motion + IoU only (no re-ID network), so it adds almost no CPU |
| **picamera2, small ISP-scaled stream, `queue=False`, 2 buffers** | Picamera2 docs: with the queue on, a returned frame can be up to one frame period older than the request; `queue=False` avoids that. Full-resolution `capture_array` is slow because of the copy, so ask the ISP (hardware) for the small size directly. Capture and inference go in separate threads |

## 2. Latency design

```
camera thread                      vision thread                        consumers (never block vision)
───────────────                    ─────────────                        ────────────────────────────
capture_array() 320x240 BGR  ─►  [ newest frame slot ]  ─►  wait_newer(last_seq)  ─►  results deque (32)
   (ISP scales, no CPU work)       overwritten, never queued   detect + track          ├─ FusionMapper (10 Hz)
                                                               publish result          ├─ /api/vision
                                                                                       └─ /camera.mjpg (draws + encodes
                                                                                          JPEG lazily, only if watched)
```

- **No queue anywhere.** The grabber keeps one slot. If inference is slower than the camera, intermediate frames are
  dropped and the detector always gets the freshest one. Latency (capture → detections ready) = inference + at most one
  frame period, however slow the model is. Verified: on a webcam, `frame→result` was inference + 26–38 ms.
- **Capture format.** `RGB888` in picamera2 is **B, G, R byte order**, which is exactly OpenCV/Ultralytics' BGR, so
  there's no colour conversion. Capture size = `CameraConfig.width/height` = 320×240 straight from the ISP, so the CPU
  doesn't resize. Ultralytics letterboxes 320×240 → 320×320.
- **Threads.** ncnn's `opt.num_threads` is capped at `VisionConfig.threads = 3`. Ultralytics leaves it at "all big
  cores", which would compete with the 20 ms safety loop, the mapper and the web server for the Pi 4's 4 cores. It is
  set on the loaded `ncnn.Net` after the first call (`YoloDetector._set_threads`). OpenCV is set to 1 thread.
- **Warm-up.** The first NCNN call allocates memory, so two warm-up frames are run and then the tracker is reset. The frame
  used for warm-up is stale by then, so the next fresh one is taken.
- **GIL.** Anything that runs alongside the detector must not busy-loop in Python. The terminal viewer only redraws when
  a new result arrives. Before that fix it starved the detector (inference 1.9 s → 0.6 s on the laptop test). The MJPEG
  stream sleeps until a new frame exists, and JPEGs are cached per frame.
- **Only pay for what's watched.** Boxes are drawn and JPEG-encoded in the HTTP thread, only when a browser is showing the
  Camera card, at ≤ `stream_fps` (10).

### Detect every N frames (multi-process runtime)

In the default runtime the camera process has **one core**, so YOLO runs on every 3rd frame
(`VisionConfig.detect_every`). Between detections, sparse Lucas-Kanade optical flow moves the boxes (`flow.py`):
median shift and median scale of ~12 corner points per box, ~1–2 ms per frame. IDs and labels are kept, and a box
that loses its points is held until the next detection. Only real detections feed the map. Details and the
research behind it: [runtime.md](runtime.md) §1 and §5; measured with `tools/run_benchmarks.sh video`.

## 3. ByteTrack settings (`deskbot/vision/bytetrack.yaml`)

The detector runs at `conf = 0.10`, and the tracker's thresholds decide what becomes a track. ByteTrack's second stage
matches **low-score** boxes (blur, partial occlusion) to existing tracks. With a high detector threshold those boxes would
be removed before the tracker ever saw them.

| Key | Value | Ultralytics default | Why |
| --- | --- | --- | --- |
| `track_high_thresh` | 0.35 | 0.25 | first-stage matches need a reasonably confident box |
| `track_low_thresh` | 0.10 | 0.10 | second stage |
| `new_track_thresh` | 0.45 | 0.25 | fewer false objects created on the map |
| `track_buffer` | 45 | 30 | ~3 s at 15 fps: IDs survive short occlusions |
| `match_thresh`, `fuse_score` | 0.8, True | same | |

Only **tracked** boxes are returned, so the map never sees one-frame flickers.

## 4. Model files (`deskbot/vision/model.py`)

```
models/yolo26n.pt                PyTorch weights, downloaded once from the Ultralytics GitHub release (~5 MB)
models/yolo26n_ncnn_model/       model.ncnn.param + model.ncnn.bin + metadata.yaml (imgsz 320)
models/.ncnn_export_failed       only if the export failed on this machine (see below)
```

- `python -m deskbot model export` downloads and exports (`model.export(format="ncnn", imgsz=320)`). Ultralytics
  downloads the PNNX converter the first time.
- `find_model()` only accepts an export whose `metadata.yaml` imgsz matches `VisionConfig.imgsz`. If you change imgsz,
  re-export.
- **Fallback.** If the export fails, the app uses `yolo26n.pt` (same detections, slower) and writes
  `models/.ncnn_export_failed`, so later starts don't re-try the slow export. `model export` always retries and removes
  the marker on success.
- `models/` is git-ignored.

## 5. Camera geometry (`deskbot/vision/geometry.py`)

Pinhole model, camera at `(x, y, height_m)` in the robot frame, tilted down by `pitch_deg`:

```
fx = (W/2) / tan(HFOV/2),  fy = (H/2) / tan(VFOV/2)
pixel (u, v) -> ray = forward + a·right + b·down,   a = (u − cx)/fx,  b = (v − cy)/fy
forward = (cos p, 0, −sin p),  right = (0, −1, 0),  down = (−sin p, 0, −cos p)
desk hit: t = height / −ray_z   (only if the ray points below the horizon)
```

`project()` is the exact inverse. It is used by the simulator and by the "should this object be visible?" test. Unit tests
check the round trip to 1e-6 m.

FOV defaults are for the **Camera Module v2** (62.2° × 48.8°). Module 3: 66° × 41°. v1: 53.5° × 41.4°.

## 6. Camera sources (`camera.py`)

| `--camera` | Class | Notes |
| --- | --- | --- |
| `pi` (default on the robot) | `PiCamera` | picamera2 `create_video_configuration(main=320×240 RGB888, buffer_count=2, queue=False, FrameRate=30)`, optional 180° flip (`rotate_180`) |
| `webcam` / `0`, `1`… | `OpenCVCamera` | `CAP_PROP_BUFFERSIZE = 1`. On **Windows** it uses **DirectShow**, because Media Foundation hung when opened in the same process as PyTorch |
| a file path | `OpenCVCamera` | plays in real time and loops |
| `sim` (default with `--sim`) | `SimCamera` + `SimDetector` | renders the simulated desk (mug, book, bottle, flat phone) from the simulated pose with the same `CameraModel`; boxes come from geometry, with occlusion; 5 % misses, 1.5 px noise. Tests the whole vision → map path without a model |
| `none` | | maps from sonar + IR only |

**Load order.** The detector is loaded **before** the camera is opened. The camera then only streams once the model is
ready, and the Windows torch/Media Foundation deadlock is avoided.

## 7. ByteTrack's `lap` dependency (`lap_compat.py`)

Since 20 Nov 2026 `lap` isn't installed at all: `bytetrack.py` always uses `lap_compat.lapjv()` (numpy Hungarian since 20 Nov 2026, scipy before that).
What follows is how it started, as a fallback for Ultralytics' tracker.

ByteTrack's matching uses the compiled `lap` package. On machines where it can't load (Windows **Smart App Control**
blocks unsigned DLLs: *"An Application Control policy has blocked this file"*), `install()` registers a stand-in `lap`
module. Its `lapjv(cost, extend_cost=True, cost_limit=L)` gives the **same assignment**: the problem is padded so that
leaving a row/column unmatched costs L/2, and solved with scipy's Hungarian algorithm. A unit test checks it against
exhaustive search on 30 random matrices. On the Pi the real `lap` loads and the stand-in is never used.

## 8. Dashboard and API

- `GET /api/vision`: camera, camera model, detector, camera fps, detection fps, mean inference ms, mean capture→result
  ms, age of the newest result, and the current detections (`label, score, box, track_id`).
- `GET /camera.mjpg`: annotated MJPEG (boxes in the categorical palette, `label score #track`).
  `GET /camera.jpg`: one frame. The page falls back to polling JPEGs with `?still=1`.
- The **Camera** card shows the live stream, the three timings and the detection chips.

## 9. Measured

| Where | Model | imgsz | Result |
| --- | --- | --- | --- |
| Laptop (i5-1235U), `model bench` | PyTorch `.pt` fallback (NCNN export blocked by Smart App Control) | 320 | detect + track **p50 226 ms**; sample photo → bus 0.86, person ×3 |
| Laptop, live webcam (DirectShow) | PyTorch fallback | 320 | inference ~560–610 ms; capture→result = inference + 26–38 ms (no queueing); the webcam itself only gave ~1 fps |
| Raspberry Pi 4 | NCNN | 320 | **not measured yet.** Run `scripts/export-model.sh`, which prints mean/p50/p95. Estimated from the Pi 5 figures above: a few tens of ms |

**Not run on the Pi or the Pi camera yet.**

## 10. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Vision disabled: No Raspberry Pi camera detected` | reseat the ribbon; `rpicam-hello --list-cameras`; stop other camera programs |
| `No module named picamera2` inside the venv | the venv must use `--system-site-packages` (`scripts/setup.sh` does that); `sudo apt install python3-picamera2` |
| Export fails on the Pi | 64-bit OS needed; free disk space ≥ 1 GB; retry `scripts/export-model.sh` |
| Low fps / high latency | `scripts/doctor.sh` CPU temperature (the Pi 4 throttles at 80 °C, so add a heatsink or fan); keep `imgsz = 320`; lower `threads` if the robot's controls lag |
| Objects in the wrong place on the map | measure `CameraConfig.height_m` and `pitch_deg` ([fusion.md §7](fusion.md)) |
| Boxes upside down | set `CameraConfig.rotate_180 = True` |
| Startup takes ~30 s on Windows | importing PyTorch (the laptop's `.pt` fallback) is that slow. The Pi doesn't import PyTorch |
