"""
Benchmark data: open, free datasets, downloaded once into benchmarks/data/ (git-ignored).

COCO val2017 (images: Flickr, various Creative Commons licences; annotations: CC BY 4.0, cocodataset.org)
    The official annotation archive (~250 MB) is downloaded once; only instances_val2017.json is kept.
    Then only the images containing desk objects are fetched one by one (~160 kB each).
    Default 300 images ~ 50 MB. Saved as benchmarks/data/coco/subset.json + images.

Objectron (Google, C-UDA 1.0: free for computational use, github.com/google-research-datasets/Objectron)
    Short phone videos circling one object. The first `per_class` clips of the official TEST split of cup,
    book, bottle and laptop are downloaded (~20 MB each), shrunk once to the robot's camera size
    (320 px, 30 fps, mp4) and the originals deleted. Default 2 per class -> 8 clips, ~18 MB kept.
"""

from __future__ import annotations

import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

from deskbot import ROOT

from . import BENCH_HOME
from deskbot.vision.coco import CATEGORY_TO_INDEX, DESK_CLASSES, NAMES

DATA = BENCH_HOME / "data"
COCO_DIR = DATA / "coco"
OBJ_DIR = DATA / "objectron"

COCO_ANN_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
COCO_IMG_URL = "http://images.cocodataset.org/val2017/{}"
OBJ_INDEX_URL = "https://raw.githubusercontent.com/google-research-datasets/Objectron/master/index/{}_annotations_test"
OBJ_VIDEO_URL = "https://storage.googleapis.com/objectron/videos/{}/video.MOV"
OBJ_CLASSES = ("cup", "book", "bottle", "laptop")

HEADERS = {"User-Agent": "deskbot-benchmark/1.0"}


def _download(url, dest, log=print, label=None):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, step = 0, max(total // 10, 1)
        nxt = step
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if label and total and done >= nxt:
                log(f"  {label}: {done * 100 // total}% of {total / 1e6:.0f} MB")
                nxt += step
    tmp.replace(dest)
    return dest


# ---------------- COCO ----------------

def coco_subset_path():
    return COCO_DIR / "subset.json"


def download_coco(n_images=300, log=print):
    """Fetch the desk-object subset of COCO val2017. Returns the subset dict."""
    COCO_DIR.mkdir(parents=True, exist_ok=True)
    ann = COCO_DIR / "instances_val2017.json"
    if not ann.exists():
        zpath = COCO_DIR / "annotations_trainval2017.zip"
        if not zpath.exists():
            log("Downloading COCO annotations (~250 MB, once)...")
            _download(COCO_ANN_URL, zpath, log, "annotations")
        with zipfile.ZipFile(zpath) as z, z.open("annotations/instances_val2017.json") as src, open(ann, "wb") as dst:
            shutil.copyfileobj(src, dst)
        zpath.unlink()
    subset = build_coco_subset(json.loads(ann.read_text(encoding="utf-8")), n_images)
    coco_subset_path().write_text(json.dumps(subset), encoding="utf-8")
    log(f"Downloading {len(subset['images'])} images with desk objects...")
    for k, im in enumerate(subset["images"]):
        dest = COCO_DIR / "images" / im["file"]
        if not dest.exists():
            _download(COCO_IMG_URL.format(im["file"]), dest)
        if (k + 1) % 50 == 0:
            log(f"  {k + 1}/{len(subset['images'])}")
    return subset


def build_coco_subset(coco, n_images):
    """Images with at least one non-crowd desk object (not just people), evenly spread over val2017."""
    desk = {NAMES.index(c) for c in DESK_CLASSES}
    person = NAMES.index("person")
    by_image = {}
    for a in coco["annotations"]:
        cls = CATEGORY_TO_INDEX.get(a["category_id"])
        if cls is None:
            continue
        x, y, w, h = a["bbox"]
        by_image.setdefault(a["image_id"], []).append([cls, x, y, x + w, y + h, int(a.get("iscrowd", 0))])
    chosen = []
    for im in sorted(coco["images"], key=lambda i: i["id"]):
        boxes = by_image.get(im["id"], [])
        objs = [b for b in boxes if b[0] in desk and b[0] != person and not b[5] and (b[3] - b[1]) * (b[4] - b[2]) >= 32 * 32]
        if objs:
            chosen.append({"id": im["id"], "file": im["file_name"], "w": im["width"], "h": im["height"], "boxes": boxes})
    if len(chosen) > n_images:
        step = len(chosen) / n_images
        chosen = [chosen[int(i * step)] for i in range(n_images)]
    return {"source": "COCO val2017 (annotations CC BY 4.0)", "classes": DESK_CLASSES, "images": chosen}


def load_coco():
    p = coco_subset_path()
    if not p.exists():
        raise FileNotFoundError("No COCO subset yet: run `python -m deskbot bench download` first")
    subset = json.loads(p.read_text(encoding="utf-8"))
    subset["images"] = [im for im in subset["images"] if (COCO_DIR / "images" / im["file"]).exists()]
    return subset


def coco_image(im):
    return COCO_DIR / "images" / im["file"]


# ---------------- Objectron ----------------

def download_objectron(per_class=2, width=320, log=print):
    """Download and shrink the first `per_class` test clips of each class. Returns [(path, label)]."""
    import cv2

    OBJ_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for cls in OBJ_CLASSES:
        req = urllib.request.Request(OBJ_INDEX_URL.format(cls), headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            names = [ln.strip() for ln in r.read().decode().splitlines() if ln.strip()][:per_class]
        for name in names:
            small = OBJ_DIR / (name.replace("/", "_") + ".mp4")
            if not small.exists():
                raw = OBJ_DIR / (name.replace("/", "_") + ".MOV")
                log(f"Downloading Objectron {name} (~20 MB)...")
                _download(OBJ_VIDEO_URL.format(name), raw, log)
                shrink_video(raw, small, width)
                raw.unlink()
            out.append((small, coco_label(cls)))
    return out


def coco_label(objectron_class):
    return {"cup": "cup", "book": "book", "bottle": "bottle", "laptop": "laptop"}[objectron_class]


def shrink_video(src, dst, width=320):
    """Re-encode to `width` px wide (keeping the aspect ratio) so benchmark runs decode quickly."""
    import cv2

    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    writer = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        size = (width, int(round(h * width / w)))
        if writer is None:
            writer = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
        writer.write(cv2.resize(frame, size, interpolation=cv2.INTER_AREA))
    cap.release()
    if writer is None:
        raise RuntimeError(f"Could not decode {src}")
    writer.release()


def local_clips():
    """[(path, label)] of downloaded clips."""
    out = []
    for p in sorted(OBJ_DIR.glob("*.mp4")):
        cls = p.name.split("_")[0]
        if cls in OBJ_CLASSES:
            out.append((p, coco_label(cls)))
    return out


def read_frames(path, max_frames=None):
    import cv2

    cap = cv2.VideoCapture(str(path))
    frames = []
    while max_frames is None or len(frames) < max_frames:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    return frames
