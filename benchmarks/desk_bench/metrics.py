"""
Detection and tracking metrics (numpy only, no pycocotools).

Detection (COCO conventions)
    AP per class: predictions sorted by score, each matched greedily to the unmatched ground-truth box
    of the same class with the highest IoU >= threshold; precision made monotone, then averaged at the
    101 recall points 0, 0.01, ..., 1. mAP50 = mean AP at IoU 0.5; mAP50-95 = mean over IoU 0.50:0.05:0.95.
    Classes with no ground truth in the set are left out of the mean. Crowd regions are ignored.
    P / R at the robot's operating score threshold (IoU 0.5) are reported too, because the robot does
    not see the whole precision-recall curve, only the boxes above its threshold.

Tracking on a clip that shows one object (Objectron)
    found       fraction of frames where the target class is reported
    id_switches times the target's track ID changes between consecutive frames
    ids         distinct track IDs given to the target (1 = perfect)
    longest     longest unbroken run with the target, as a fraction of the clip
    jitter      1 - IoU of the target box between consecutive frames (box stability)
    agreement   mean IoU against detecting on EVERY frame (how well "detect every N + optical flow"
                reproduces full detection)
"""

from __future__ import annotations

import numpy as np

IOU_THRESHOLDS = np.round(np.linspace(0.5, 0.95, 10), 2)


def iou_matrix(a, b):
    """IoU between every box in a (N, 4) and b (M, 4), xyxy."""
    a = np.asarray(a, np.float64).reshape(-1, 4)
    b = np.asarray(b, np.float64).reshape(-1, 4)
    if not len(a) or not len(b):
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-9)


def iou(a, b):
    return float(iou_matrix([a], [b])[0, 0])


def average_precision(tp, scores, n_gt):
    """COCO 101-point interpolated AP from per-prediction TP flags."""
    if n_gt == 0:
        return None
    if len(tp) == 0:
        return 0.0
    order = np.argsort(-np.asarray(scores), kind="stable")
    tp = np.asarray(tp, np.float64)[order]
    ctp = np.cumsum(tp)
    cfp = np.cumsum(1 - tp)
    recall = ctp / n_gt
    precision = ctp / np.maximum(ctp + cfp, 1e-9)
    precision = np.maximum.accumulate(precision[::-1])[::-1]      # monotone envelope
    pts = np.linspace(0, 1, 101)
    idx = np.searchsorted(recall, pts, side="left")
    return float(np.mean([precision[i] if i < len(precision) else 0.0 for i in idx]))


def _match(pred_boxes, pred_scores, gt_boxes, thr):
    """Greedy COCO matching for one image + class. Returns TP flags in prediction order."""
    tp = np.zeros(len(pred_boxes))
    if not len(pred_boxes) or not len(gt_boxes):
        return tp
    ious = iou_matrix(pred_boxes, gt_boxes)
    used = np.zeros(len(gt_boxes), bool)
    for i in np.argsort(-np.asarray(pred_scores), kind="stable"):
        cand = np.where(~used & (ious[i] >= thr))[0]
        if len(cand):
            j = cand[np.argmax(ious[i, cand])]
            used[j] = True
            tp[i] = 1
    return tp


def evaluate(preds, gts, classes, op_conf=0.35):
    """preds/gts: per image, list of (label, score, box) / (label, box).
    Returns {"map50", "map", "precision", "recall", "per_class": {label: {"ap50", "ap", "n_gt"}}}."""
    per_class = {}
    tp_op = fp_op = n_gt_all = 0
    for label in classes:
        n_gt = 0
        flags = {t: [] for t in IOU_THRESHOLDS}
        scores = []
        for p_img, g_img in zip(preds, gts):
            pb = [p[2] for p in p_img if p[0] == label]
            ps = [p[1] for p in p_img if p[0] == label]
            gb = [g[1] for g in g_img if g[0] == label]
            n_gt += len(gb)
            scores += ps
            for t in IOU_THRESHOLDS:
                flags[t] += list(_match(pb, ps, gb, t))
            keep = [i for i, s in enumerate(ps) if s >= op_conf]
            tp = _match([pb[i] for i in keep], [ps[i] for i in keep], gb, 0.5)
            tp_op += int(tp.sum())
            fp_op += int(len(tp) - tp.sum())
        n_gt_all += n_gt
        if n_gt == 0:
            continue
        aps = [average_precision(flags[t], scores, n_gt) for t in IOU_THRESHOLDS]
        per_class[label] = {"ap50": aps[0], "ap": float(np.mean(aps)), "n_gt": n_gt}
    vals = list(per_class.values())
    return {
        "map50": float(np.mean([v["ap50"] for v in vals])) if vals else None,
        "map": float(np.mean([v["ap"] for v in vals])) if vals else None,
        "precision": tp_op / (tp_op + fp_op) if tp_op + fp_op else None,
        "recall": tp_op / n_gt_all if n_gt_all else None,
        "per_class": per_class,
    }


def target_track(frames_dets, label):
    """Per frame: the largest box of `label` as (box, track_id) or None."""
    out = []
    for dets in frames_dets:
        cand = [d for d in dets if d.label == label]
        if not cand:
            out.append(None)
            continue
        d = max(cand, key=lambda d: (d.box[2] - d.box[0]) * (d.box[3] - d.box[1]))
        out.append((d.box, d.track_id))
    return out


def tracking_metrics(frames_dets, label, reference=None):
    tr = target_track(frames_dets, label)
    n = len(tr)
    found = [t is not None for t in tr]
    switches, ids, jit = 0, set(), []
    run = best = 0
    for i, t in enumerate(tr):
        if t is None:
            run = 0
            continue
        run += 1
        best = max(best, run)
        if t[1] is not None:
            ids.add(t[1])
        if i and tr[i - 1] is not None:
            prev = tr[i - 1]
            if t[1] is not None and prev[1] is not None and t[1] != prev[1]:
                switches += 1
            jit.append(1 - iou(prev[0], t[0]))
    out = {
        "frames": n,
        "found": sum(found) / n if n else None,
        "id_switches": switches,
        "ids": len(ids),
        "longest": best / n if n else None,
        "jitter": float(np.mean(jit)) if jit else None,
    }
    if reference is not None:
        ref = target_track(reference, label)
        agree = [iou(a[0], b[0]) for a, b in zip(tr, ref) if b is not None and a is not None]
        missed = sum(1 for a, b in zip(tr, ref) if b is not None and a is None)
        both = sum(1 for b in ref if b is not None)
        out["agreement"] = float(np.sum(agree) / both) if both else None   # a missed frame counts as IoU 0
        out["missed_vs_ref"] = missed
    return out
