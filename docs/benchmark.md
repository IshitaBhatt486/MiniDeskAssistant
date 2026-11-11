# Benchmark: detection under lighting, tracking on video, runtime latency (15 Nov 2026)

```bash
bash tools/run_benchmarks.sh                     # everything; downloads the data the first time (~420 MB, then ~85 MB kept)
bash tools/run_benchmarks.sh download            # data only
bash tools/run_benchmarks.sh images --limit 50   # quick accuracy run
bash tools/run_benchmarks.sh video --every 1,3,5
bash tools/run_benchmarks.sh video --video my_desk.mp4 --label cup   # your own recording
bash tools/run_benchmarks.sh system              # processes / latency only (no data, no model)
```

Also in the menu: `scripts/deskbot.sh` → **Benchmark**. Each run writes `benchmarks/results/<date-time>/report.md` (tables)
and `results.json` (everything). Both folders are git-ignored.

| | |
| --- | --- |
| Code | `deskbot/bench/`: `datasets.py` (download, subset), `lighting.py` (11 conditions), `metrics.py` (AP, mAP, tracking), `run.py` (the three benchmarks, report) |
| Tests | `tests/test_bench.py` (metric maths against hand-computed cases, lighting determinism) |

## 1. Datasets (open, free)

| Dataset | Licence | What's used | Size |
| --- | --- | --- | --- |
| [COCO](https://cocodataset.org) val2017 | annotations **CC BY 4.0**; images from Flickr under Creative Commons licences | 300 images containing desk objects (not only people), spread evenly across val2017, with every box in 18 desk classes | 250 MB annotation zip downloaded once (only the 25 MB val JSON is kept) + ~50 MB images |
| [Objectron](https://github.com/google-research-datasets/Objectron) (Google) | **C-UDA 1.0** (free for computational use) | first 2 clips per class of the official **test** split: cup, book, bottle, laptop. Each clip is one object filmed walking around it | ~20 MB per clip downloaded, re-encoded to 320 px (1–4 MB kept) and the original deleted |
| Your own video | yours | `--video FILE --label NAME` | |

Desk classes scored: person, bottle, wine glass, cup, bowl, chair, potted plant, tv, laptop, mouse, remote, keyboard,
cell phone, book, clock, vase, scissors, teddy bear (`deskbot/vision/coco.py`).

Why these: COCO is the dataset YOLO26 is trained and scored on, and it has every desk class with exact boxes.
Objectron is real handheld video of exactly the desk objects, which is what tracking needs. Real low-light
detection sets don't cover desk objects: ExDark has 12 classes, with no books, phones or laptops, and asks for
non-commercial use. LIS has 8 classes. So lighting is varied **synthetically and repeatably** instead (next section).

## 2. Lighting conditions (`lighting.py`)

Applied in linear light, the way the sensor sees it. Low light is modelled as **less light × the camera's gain**,
which amplifies shot noise (∝ √signal) and read noise. This follows the brightness, contrast, noise and blur
corruptions of the ImageNet-C / COCO-C robustness benchmarks, plus desk cases. Each image's noise is seeded with
its id, so runs are comparable.

| Condition | Model |
| --- | --- |
| `normal` | unchanged |
| `dim` | 30 % light, gain ×2 |
| `dark` | 10 % light, gain ×4 |
| `very_dark` | 3 % light, gain ×8 (heavy noise) |
| `bright` | 2.5× light, highlights clip |
| `harsh` | contrast ×1.8 |
| `low_contrast` | glare / haze: contrast ×0.45, lifted blacks |
| `backlit` | window behind the objects: brightness ramps from ×3 at the top to ×0.35 at the bottom |
| `warm` | tungsten ~2700 K (red ×1.3, blue ×0.55) |
| `cool` | cool LED / daylight ~7500 K |
| `motion_blur` | robot turning: 9 px horizontal blur |

## 3. Metrics

**Images** (`bench images`). Every image is first resized to the robot camera's 320 px width, so the detector sees
what the robot would. YOLO26n runs at imgsz 320 on **one thread**, the camera process's single core.

| Metric | Meaning |
| --- | --- |
| mAP50 | mean over classes of AP at IoU ≥ 0.5 (COCO 101-point interpolation, greedy best-IoU matching, crowd boxes ignored) |
| mAP50-95 | mean AP over IoU 0.50, 0.55 … 0.95 (rewards tight boxes, which matter for map positions) |
| vs normal | mAP50 relative to `normal`: how much a lighting condition costs |
| Precision / Recall | at the robot's operating threshold (score ≥ 0.35 = ByteTrack's `track_high_thresh`), IoU 0.5: what the robot actually acts on |
| Per-class AP50 | normal light, with box counts |
| Inference p50 / p95 | ms per image, this machine, NCNN if exported (else the PyTorch fallback) |

**Video** (`bench video`). The camera process's loop runs offline over every frame for N = 1, 3, 5. The clip shows
one object, so no per-frame boxes are needed.

| Metric | Meaning |
| --- | --- |
| Found | fraction of frames where the object's class is reported |
| ID switches | times the object's ByteTrack ID changes between consecutive frames |
| IDs | distinct IDs given to the object (1 = perfect) |
| Longest run | longest unbroken stretch with the object, as a fraction of the clip |
| Jitter | 1 − IoU of the object's box between consecutive frames (box stability) |
| Agreement | mean IoU against detecting on **every** frame (N = 1); a frame missed counts 0. How faithfully detect-every-N + optical flow reproduces full detection |
| CPU ms/frame | (detection ms + flow ms) ÷ frames, and whether that fits in a 30 fps frame (33 ms) |

**System** (`bench system`). Motor and sensor processes on the simulated robot. 300 commands (left / right / stop,
5–60 ms apart, so moves get preempted). Measures command → motor latency, sensor-sample age at the safety check,
preemptions, shared-memory read cost against a `Queue` round trip, and loop rates.

## 4. Results so far

Laptop (i5-1235U, Windows). The NCNN export is blocked by Smart App Control, so the image and video numbers use the
**PyTorch fallback** and are not Pi numbers. **Run `tools/run_benchmarks.sh` on the Pi for the real ones.**

See the newest `benchmarks/results/*/report.md`; the runs from development are summarised in [runtime.md](runtime.md) §8.

## 5. Recording your own test video

The most realistic test is your desk under your lamps:

```bash
rpicam-vid -t 20000 --width 640 --height 480 --framerate 30 -o desk_dark.h264   # on the Pi, lamp off
ffmpeg -i desk_dark.h264 -c copy desk_dark.mp4
bash tools/run_benchmarks.sh video --video desk_dark.mp4 --label cup --conditions normal
```

Use `--conditions normal` when the recording already has the lighting you want to test.

## 6. Open-source suite (`benchmarks.py`, 18 Nov 2026)

Install with `pip install -r benchmarks/requirements.txt`. Results below are from the development laptop.

### Planners against PythonRobotics A* (commit ef64608)

Same start and goal. The baseline uses a 5 cm grid and only avoids collisions; this project's routes also respect the sonar stop rule
and may keep extra clearance. The baseline's time includes building its grid.

| Desk | Chosen here | Route cm | Plan ms | PythonRobotics cm | PythonRobotics ms |
|---|---|---:|---:|---:|---:|
| open desk | direct | 81.3 | 14.2 | 82.1 | 111.4 |
| one obstacle | visibility | 107.4 | 39.9 | 151.9 | 125.7 |
| few obstacles | Theta* | 97.3 | 36.0 | 88.6 | 318.2 |
| many obstacles | A* | 135.8 | 54.4 | 132.4 | 558.6 |
| clutter | A* | 159.5 | 15.9 | 141.6 | 320.3 |
| narrow gap | A* | 94.0 | 26.2 | 124.0 | 346.0 |
| unexplored | A* | 110.7 | 43.5 | 108.6 | 367.5 |

### Other results

- **pyperf:** costmap 3.44 ms, A* 14.58 ms, Theta* 22.95 ms, visibility 16.78 ms, sensor filter 0.020 ms, adaptive check 0.039 ms, colour 0.266 ms.
- **evo:** simulated square, wheels 5% slower than assumed, commanded-speed odometry: ATE RMSE 1.88 cm, max 3.93 cm.
- **TrackEval, simulated camera:** fixed interval 136 detector runs, HOTA 0.823, MOTA 0.849, IDF1 0.922. Adaptive 61 runs, HOTA 0.806, MOTA 0.876, IDF1 0.934, no ID switches in either. Simulated detector IDs are stable, so this mainly tests box accuracy between detections. For real tracking data, pass MOT-format files with `--gt` and `--results`.
- **pycocotools:** 10 COCO images at 320 px with the PyTorch model: mAP50 0.498, mAP50-95 0.371, AR100 0.395. The sample is too small to quote as accuracy.
- **jiwer + LibriSpeech:** implemented but not run, because Smart App Control blocks `ctranslate2` on the laptop. Run `python benchmarks/benchmarks.py speech --limit 20` on the Pi.
