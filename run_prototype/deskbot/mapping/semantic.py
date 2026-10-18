"""
Semantic layer: a map of OBJECTS (cup, book, phone, ...) seen by the camera.

Object-level, not per-cell: every physical object is one `Landmark` with
    position      2-D mean + isotropic variance, fused over all sightings (1-D Kalman per axis)
    existence     log-odds that the object is really there. A detection adds, a miss subtracts
                  ("it should be in view but the detector doesn't see it"), and it decays toward 0 with time
    class         accumulated detection scores per label; the label shown is the arg-max
    track IDs     the ByteTrack IDs that have been associated with it

Why object-level: a 4 m map has 6400 cells but only a handful of objects, and the detector
reports objects, not cells. Keeping objects lets the map reason about "the cup", not "60 red cells".
It is rasterised into a grid only when the dashboard asks (see fusion.py).

Stale data (objects move while the camera looks elsewhere):
    * existence decays with half-life `sem_half_life_s` -> confidence -> 0 (unknown), not "still there"
    * position variance grows with time unseen (`position_drift`), so a stale object becomes a
      wider, fainter blob and a re-sighting nearby is still associated with it
    * a miss in view drops existence quickly, so a moved object disappears on the next look
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..config import MappingConfig, object_radius

LN2 = math.log(2.0)


@dataclass
class Observation:
    label: str
    score: float
    x: float | None          # world position (None = seen but not localisable, e.g. box cut off)
    y: float | None
    var: float               # position variance, m^2
    track_id: int | None
    source: str = "ground"   # "sonar" or "ground" (how the range was found)


@dataclass
class Landmark:
    id: int
    x: float
    y: float
    var: float
    L: float
    t_update: float          # last existence update (hit or miss)
    t_seen: float            # last detection
    t_created: float
    votes: dict = field(default_factory=dict)
    track_ids: set = field(default_factory=set)
    hits: int = 0
    misses: int = 0
    source: str = "ground"

    @property
    def label(self):
        return max(self.votes, key=self.votes.get)


class SemanticMap:
    def __init__(self, cfg: MappingConfig):
        self.cfg = cfg
        self.k = LN2 / cfg.sem_half_life_s
        self.objects: dict[int, Landmark] = {}
        self.by_track: dict[int, int] = {}
        self._next_id = 1
        self.frames = 0

    # -- time-dependent views --

    def existence(self, lm: Landmark, now):
        return lm.L * math.exp(-self.k * max(0.0, now - lm.t_update))

    def variance(self, lm: Landmark, now):
        return lm.var + self.cfg.position_drift * max(0.0, now - lm.t_seen)

    @staticmethod
    def probability(L):
        return 1.0 / (1.0 + math.exp(-L))

    # -- one processed camera frame --

    def update(self, now, observations, visible):
        """observations: [Observation]; visible(lm) -> True if lm should be in view and unoccluded."""
        cfg = self.cfg
        self.frames += 1
        matched = set()
        for ob in sorted(observations, key=lambda o: -o.score):
            lm = self._associate(ob, now, matched)
            if lm is None:
                if ob.x is None:
                    continue  # nothing to anchor an unlocalised sighting to
                lm = Landmark(self._next_id, ob.x, ob.y, ob.var, 0.0, now, now, now, source=ob.source)
                self.objects[lm.id] = lm
                self._next_id += 1
            matched.add(lm.id)
            # position: Kalman update with the variance grown since the last sighting
            if ob.x is not None:
                var = self.variance(lm, now)
                k = var / (var + ob.var)
                lm.x += k * (ob.x - lm.x)
                lm.y += k * (ob.y - lm.y)
                lm.var = (1 - k) * var
                lm.source = ob.source
            # existence: decayed prior + evidence scaled by detector confidence
            lm.L = min(cfg.l_max, self.existence(lm, now) + cfg.l_hit * ob.score)
            lm.t_update = lm.t_seen = now
            lm.votes[ob.label] = lm.votes.get(ob.label, 0.0) + ob.score
            lm.hits += 1
            if ob.track_id is not None:
                lm.track_ids.add(ob.track_id)
                self.by_track[ob.track_id] = lm.id

        # negative evidence: should be visible, wasn't detected
        for lm in list(self.objects.values()):
            if lm.id in matched or not visible(lm):
                continue
            lm.L = max(cfg.l_min, self.existence(lm, now) - cfg.l_miss)
            lm.t_update = now
            lm.misses += 1
        self.prune(now)

    def _associate(self, ob: Observation, now, taken):
        # 1) same ByteTrack ID as before -> same object (if it hasn't jumped impossibly far)
        if ob.track_id is not None and ob.track_id in self.by_track:
            lm = self.objects.get(self.by_track[ob.track_id])
            if lm is not None and lm.id not in taken:
                if ob.x is None or math.hypot(ob.x - lm.x, ob.y - lm.y) < self._gate(lm, ob, now) * 2:
                    return lm
        if ob.x is None:
            return None
        # 2) nearest object with the same label inside the gate
        best, best_d = None, None
        for lm in self.objects.values():
            if lm.id in taken or ob.label not in lm.votes:
                continue
            d = math.hypot(ob.x - lm.x, ob.y - lm.y)
            if d < self._gate(lm, ob, now) and (best_d is None or d < best_d):
                best, best_d = lm, d
        return best

    def _gate(self, lm, ob, now):
        return self.cfg.gate_m + 2 * math.sqrt(self.variance(lm, now) + ob.var)

    def prune(self, now):
        for lm in list(self.objects.values()):
            e = self.existence(lm, now)
            stale = now - lm.t_update > 6 * self.cfg.sem_half_life_s  # faded to ~1.5% of its evidence
            if e < self.cfg.prune_logodds or stale:
                del self.objects[lm.id]
        live = set(self.objects)
        self.by_track = {t: i for t, i in self.by_track.items() if i in live}

    # -- output --

    def describe(self, now):
        out = []
        for lm in self.objects.values():
            e = self.existence(lm, now)
            p = self.probability(e)
            out.append({
                "id": lm.id,
                "label": lm.label,
                "x": round(lm.x, 3),
                "y": round(lm.y, 3),
                "sigma": round(math.sqrt(self.variance(lm, now)), 3),
                "radius": object_radius(lm.label),
                "p": round(p, 3),
                "confidence": round(abs(2 * p - 1), 3),
                "age": round(now - lm.t_seen, 1),
                "hits": lm.hits,
                "misses": lm.misses,
                "tracks": sorted(lm.track_ids)[-3:],
                "source": lm.source,
            })
        out.sort(key=lambda o: -o["confidence"])
        return out
