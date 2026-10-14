"""
YOLO26n model files: download once, export to NCNN once, benchmark.

    models/yolo26n.pt              PyTorch weights (downloaded from the Ultralytics GitHub release, free)
    models/yolo26n_ncnn_model/     NCNN export: model.ncnn.param + model.ncnn.bin + metadata.yaml

Why NCNN: Tencent's NCNN is built for ARM CPUs (NEON, fp16 storage, Winograd convs), and
Ultralytics' Raspberry Pi guide measures it as the fastest export format on Pi. The export is made at
the same `imgsz` the detector runs at (320), so there is no resizing of the network at runtime.
Everything runs locally: there is no cloud inference and no API cost.
"""

from __future__ import annotations

import shutil
import statistics
import time
from pathlib import Path

from .. import MODELS_DIR
from ..config import CameraConfig, VisionConfig


def ncnn_dir(vcfg: VisionConfig) -> Path:
    return MODELS_DIR / f"{vcfg.model_name}_ncnn_model"


def _exported_imgsz(path: Path):
    meta = path / "metadata.yaml"
    try:
        import yaml  # PyYAML, an Ultralytics dependency

        imgsz = yaml.safe_load(meta.read_text(encoding="utf-8")).get("imgsz")
        return int(imgsz[0] if isinstance(imgsz, (list, tuple)) else imgsz)
    except Exception:
        return None


def find_model(vcfg: VisionConfig):
    """Path of a usable NCNN export (matching imgsz), or None."""
    d = ncnn_dir(vcfg)
    if d.is_dir() and any(d.glob("*.param")) and _exported_imgsz(d) in (None, vcfg.imgsz):
        return d
    return None


def export_model(vcfg: VisionConfig, log=print):
    """Download the .pt weights if needed and export them to NCNN at vcfg.imgsz. Returns the folder."""
    from ultralytics import YOLO

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    pt = MODELS_DIR / f"{vcfg.model_name}.pt"
    log(f"Loading {pt.name} (downloads ~5 MB the first time)...")
    model = YOLO(str(pt))
    target = ncnn_dir(vcfg)
    if target.exists():
        shutil.rmtree(target)
    log(f"Exporting to NCNN at imgsz={vcfg.imgsz} (takes a minute; downloads the PNNX converter once)...")
    try:
        out = Path(model.export(format="ncnn", imgsz=vcfg.imgsz, verbose=False))
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)  # don't leave a half-written export behind
        raise
    if out.resolve() != target.resolve():
        shutil.move(str(out), str(target))
    (MODELS_DIR / ".ncnn_export_failed").unlink(missing_ok=True)
    log(f"Model ready: {target}")
    return target


def ensure_model(vcfg: VisionConfig, log=print):
    return find_model(vcfg) or export_model(vcfg, log)


FAILED_MARKER = MODELS_DIR / ".ncnn_export_failed"


def resolve_model(vcfg: VisionConfig, log=print, allow_fallback=True):
    """NCNN export if possible. If exporting fails (e.g. Windows Smart App Control blocks the PNNX
    converter) fall back to the PyTorch .pt weights: same detections, just slower.
    A failed export is remembered (models/.ncnn_export_failed) so later starts don't spend a minute
    re-trying it; `deskbot model export` always retries and clears the marker on success."""
    found = find_model(vcfg)
    if found:
        return found
    pt = MODELS_DIR / f"{vcfg.model_name}.pt"
    if allow_fallback and FAILED_MARKER.exists() and pt.exists():
        log(f"Using PyTorch weights {pt.name} (NCNN export failed earlier: {FAILED_MARKER.read_text().strip()[:120]}). "
            "Retry with: python -m deskbot model export")
        return pt
    try:
        return export_model(vcfg, log)
    except Exception as exc:
        if not allow_fallback:
            raise
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        FAILED_MARKER.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        log(f"NCNN export failed ({type(exc).__name__}: {exc}). Falling back to PyTorch weights {pt.name} - slower.")
        return pt


def sample_image(ccfg: CameraConfig):
    """A real photo for benchmarks/tests: Ultralytics ships bus.jpg; resized to the camera size."""
    import cv2
    import ultralytics

    path = Path(ultralytics.__file__).parent / "assets" / "bus.jpg"
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(path)
    return cv2.resize(img, (ccfg.width, ccfg.height), interpolation=cv2.INTER_AREA)


def benchmark(vcfg: VisionConfig, ccfg: CameraConfig, runs=50, image=None, log=print):
    """Time detect+track on one image. Returns a dict of milliseconds."""
    from .camera import Frame
    from .detector import YoloDetector

    path = resolve_model(vcfg, log)
    det = YoloDetector(vcfg, path)
    img = sample_image(ccfg) if image is None else image
    det.warmup(img)
    times, dets = [], []
    for i in range(runs):
        t0 = time.perf_counter()
        dets = det(Frame(i + 1, 0.0, img))
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return {
        "model": str(path),
        "imgsz": vcfg.imgsz,
        "threads": getattr(det, "threads", None),
        "runs": runs,
        "mean_ms": round(statistics.fmean(times), 1),
        "p50_ms": round(times[len(times) // 2], 1),
        "p95_ms": round(times[int(len(times) * 0.95) - 1], 1),
        "fps": round(1000 / statistics.fmean(times), 1),
        "detections": [f"{d.label} {d.score:.2f}" for d in dets],
    }
