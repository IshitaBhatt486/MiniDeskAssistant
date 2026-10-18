# Sensor fusion maps: geometric, semantic, confidence heatmap (15 Nov 2026)

The robot builds **three maps** from the 4 ultrasonic sensors, the 2 IR edge sensors and the camera's object detections.
The dashboard shows all three:

| Map | Built from | Answers |
| --- | --- | --- |
| **Geometric** | ultrasonic (free beam + hit), IR (floor / desk edge), the robot's own footprint | *Is there something solid here?* |
| **Semantic** | camera detections (YOLO26n + ByteTrack), ranged by the ground plane or the front ultrasonic | *What is here? (cup, book, phone…)* |
| **Confidence heatmap** | geometric + semantic, fused | *How sure are we that there is / isn't an object here?* |

| | |
| --- | --- |
| Code | `deskbot/mapping/grid.py` (geometric), `semantic.py` (objects), `fusion.py` (mapper thread + fusion + heatmap) |
| Config | `deskbot/config.py` → `MappingConfig` (every constant below) |
| Entry | `scripts/start.sh` / `python -m deskbot run` (`--sim` for the simulator) |
| API | `GET /api/fusion`, `POST /api/fusion/reset` |
| Tests | `tests/test_mapping.py`, `tests/test_system.py` |
| Dependencies | numpy only (the vision side is in [vision.md](vision.md)) |

The older single-layer mapper (`dashboard/mapping.py`, [mapping.md](mapping.md)) is unchanged and still used by
`dashboard/server_mapping.py` / `server_multisonar.py`.

---

## 1. Research behind the design (brief)

| Question | What the sources say | What we do |
| --- | --- | --- |
| How to forget stale evidence in an occupancy grid? | Multiplying log-odds by γ < 1 per step fades old evidence (AV2 occupancy-grid notes). Decaying the *whole* map every step costs CPU/memory traffic (time-aware OGM patent). Per-cell timestamps and category-dependent rates are the alternatives | **Per-cell timestamp, decayed lazily** when a cell is read or written. **Different half-lives**: 90 s for geometry, 45 s for objects (objects get moved, walls don't) |
| How to combine a camera with range sensors? | Camera gives **bearing** (from pixel column + intrinsics), sonar gives **range**. Take the range from the sonar beam with the closest bearing (opti-acoustic semantic SLAM, arXiv 2403.12837; camera/sonar patent US 11954918) | Bearing from the box centre; range from the **front ultrasonic** when the object is within ±10° of straight ahead and the ranges agree, otherwise from the **ground plane** |
| Map objects per cell or per object? | Object-level maps (landmarks with class + position) are standard in semantic SLAM | **Object-level** `Landmark`s, rasterised only when the dashboard asks |
| Heatmap colours for "confident yes / unknown / confident no" | Diverging scale = two hues + a **neutral midpoint**, never a rainbow (dataviz guidelines) | Blue (sure: empty) → grey (unknown/stale) → red (sure: object), interpolated in OKLab |

## 2. Architecture and threads

```
 Robot (dashboard/robot.py + multisonar.py)          Vision (deskbot/vision)
   sensor thread 10 Hz -> latest_reading()             camera thread -> newest frame only
   20 ms safety loop   -> wheel_log                    vision thread -> results (seq, t_capture, detections)
            │ read-only                                          │ read-only
            ▼                                                    ▼
 FusionMapper thread (10 Hz, deskbot/mapping/fusion.py) ──────────┘
   odometry (wheel_log replay, inherited from dashboard/mapping.Mapper)
   pose history (t, x, y, θ)  ── lets a detection use the pose at ITS capture time
   DecayGrid  <- sonar cones, IR, footprint
   SemanticMap <- detections (+ misses)
            │ snapshot() under the mapper lock
            ▼
 GET /api/fusion  (HTTP thread, gzip)  ->  fusion.js draws 3 canvases
```

Same isolation rules as the original mapper. The mapper **never** touches motors or GPIO. The safety loop never waits for
mapping or vision, and every mapper/vision failure is caught and logged, never raised into the robot. `FusionMapper` subclasses
`MultiSonarMapper` (so it gets the 4-sonar geometry and the dead reckoning). It overrides `_reset_state`, `_integrate`,
`reset` and `snapshot`.

## 3. Geometric layer: `DecayGrid`

| Property | Value |
| --- | --- |
| Grid | `size = 80` × `resolution = 0.05` m → **4 m × 4 m**, start pose in the centre, row 0 = bottom |
| Storage | numpy: `L` float32 log-odds, `T` float64 last-update time, `edge` bool, `seen` bool (~90 KB) |
| Index | `col = floor(x/res) + n/2`, `row = floor(y/res) + n/2`, flat `i = row·n + col` |

**Time decay (staleness):**

```
L_eff(now) = L · exp(−ln2 · (now − T) / half_life)          half_life = geo_half_life_s = 90 s
```

- On **read** (`logodds(now)`), the whole array is decayed in one vectorised expression. Nothing runs on a timer.
- On **write** (`add(idx, Δ, now)`), the touched cells are first decayed to `now`, then `Δ` is added, then clamped to
  [−4, 4], and `T = now`. This is the standard additive log-odds Bayes update with an exponential forgetting factor.
- After one half-life without an observation the evidence is halved. After about 4 half-lives (6 min) the cell is back near
  p = 0.5, so it shows as **unknown/stale** on the heatmap.

**Sensor model** (constants in `MappingConfig`):

| Event | Δ log-odds |
| --- | --- |
| Ultrasonic beam passes through a cell | `l_free = −0.40` |
| Ultrasonic hit (< `sonar_max_useful` 1.2 m) | `l_occ = +0.85` |
| IR sees the floor / robot footprint (radius 6 cm) | `l_floor = −0.60` |
| IR sees a drop | permanent `edge` flag (desk edges don't move) |

**Cone raycasting, vectorised.** Each reading casts `sonar_rays = 5` rays across the ±7.5° HC-SR04 cone. Each ray is
sampled every half cell with `numpy.linspace`/`outer`, and the samples are converted to cell indices in one call. Then:

- `occ = unique(end cells)` if it was a hit, and `free = unique(all other samples) − occ`.
- **Every cell is updated once per reading.** Near the sensor, all 5 rays cross the same cells. The old mapper counted
  that as 3 observations (it had 3 rays) and over-confidently cleared those cells. Hit cells are never also marked free.
- "No echo" (≥ 1.2 m) marks the whole cone free up to 1.2 m and adds no hit.

## 4. Semantic layer: `SemanticMap`

**Object-level.** Each physical object is one `Landmark`:

| Field | Meaning |
| --- | --- |
| `x, y, var` | position mean and isotropic variance (m²), fused with a 1-D Kalman filter per axis |
| `L, t_update` | existence log-odds and when it last changed (hit or miss) |
| `t_seen` | last detection |
| `votes` | accumulated detection scores per label; the label shown is the arg-max |
| `track_ids` | ByteTrack IDs associated with it |

### From a detection to a map position (`fusion.py::_integrate_frame`)

1. `u = box centre x`, `v = box bottom y`. The bottom-centre of the box is where the object stands on the desk.
2. **Bearing** `= atan2(−(u − cx), fx)`, with `fx = (W/2)/tan(HFOV/2)`.
3. **Range**, in order of preference:
   - **Front ultrasonic**, if `|bearing| ≤ sonar_fuse_deg` (10°), the sonar has a hit, and it agrees with the ground estimate
     (`|r_sonar − r_ground| < max(8 cm, 40 %)`). The sonar then supplies the range, with σ ≈ 2 cm + 3 % of the range.
     It is counted in `stats.sonar_fused`.
   - **Ground plane:** the pixel ray of (u, v) is intersected with the desk plane, using the camera height and pitch
     (`CameraModel.ground_point`). σ = 2 cm + 10 cm·r², because the error grows with distance squared.
   - If the box bottom touches the image edge (the base is cut off), the ground estimate is wrong. If the sonar can't help
     either, the detection is **unlocalised**. It can still refresh an existing object with the same track ID, but it never
     creates one or moves one.
4. The box bottom is the object's **front face**, so the centre is placed one class radius further along the bearing
   (`config.OBJECT_RADIUS`: cup 4.5 cm, book 10 cm, laptop 17 cm …).
5. Detections beyond `max_detect_range` (1.5 m) are ignored.
6. **Pose at capture time.** The robot→map transform uses `pose_at(t_capture)`, interpolated linearly (heading the short
   way round ±π) from the last 40 s of poses. A frame captured 80 ms before its detections were ready is placed where
   the robot *was*, so it isn't smeared along the motion.

### Association (`SemanticMap._associate`)

1. **Same ByteTrack ID** as a known object → same object, unless it jumped more than 2× the gate.
2. Otherwise, the **nearest object with the same label** inside the gate `gate_m + 2·sqrt(var_obj + var_obs)` (0.15 m + 2σ).
3. Otherwise a **new object** (only if the detection is localised).

Each object takes at most one detection per frame; detections are processed in descending score order.

### Updates

| Event | Position | Existence `L` |
| --- | --- | --- |
| Detected | Kalman: `k = var/(var + R)`, `x += k(z − x)`, `var = (1 − k)var` | `L_eff + l_hit·score` (1.2 × score), clamped to ±4 |
| **Should be visible but wasn't detected** (miss) | unchanged | `L_eff − l_miss` (0.6) |
| Not observed | `var` grows by `position_drift` (0.0004 m²/s) | decays with `sem_half_life_s` = 45 s |
| `L_eff < prune_logodds` (−1), or no update for 6 half-lives | removed | |

**"Should be visible"** (`visible(lm)` in `fusion.py`) means all of these, at the frame's capture pose:

- The object's front face projects inside the image (10 px margin).
- It is between 10 cm and 1.5 m away.
- No detection in the same frame covers its bearing at a range at least 8 cm closer (that would occlude it).

### Why this handles objects moved while the camera looked away

- While unseen, existence **decays toward 0 (p = 0.5)**, never toward "still there". On the maps it fades to unknown.
- While unseen, the position variance **grows**. The blob gets wider and fainter, and the uncertainty ring on the semantic
  map grows. A re-sighting near the old spot still associates with it.
- When the robot looks at the old spot again and the object isn't there, each processed frame is a **miss**. At ~15 fps
  the object is removed within a few frames (verified: `tests/test_system.py::test_3_moved_object_is_forgotten`).
- Objects that are *out of view* get no misses, so turning away doesn't delete the map. It only ages it.

## 5. Confidence heatmap (fusion)

At snapshot time (`fusion.py::snapshot` + `semantic_layer`):

```
sem(cell)   = strongest  L_eff(object) · w(d)     over objects (by |value|; keeps "sure: empty" too)
              w = 1 inside the object radius, exp(−(d − r)² / 2σ²) outside, σ = max(√var, cell)
fused(cell) = clip( L_geo_eff(cell) + heat_object_weight · sem(cell), −4, 4 )
P(object)   = 1 / (1 + e^(−fused))           -> sent as uint8 0..255 (128 ≈ unknown)
confidence  = |2P − 1|
```

Adding log-odds = treating the two layers as independent evidence (standard Bayesian fusion). Both terms are already
decayed, so stale data → |fused| small → P ≈ 0.5 → **middle colour**.

Colours (`deskbot/web/static/fusion.css`, tokens `--heat-free`, `--heat-mid`, `--heat-occ`):

| P(object) | Meaning | Light | Dark |
| --- | --- | --- | --- |
| 0 | sure: nothing there | `#1c5cab` blue | `#5598e7` |
| 0.5 | unknown **or stale** | `#f0efec` neutral grey | `#383835` |
| 1 | sure: an object | `#c4302f` red | `#e66767` |

The 256-entry colour table is interpolated in **OKLab** (perceptually even) and rebuilt when the OS theme changes. Desk
edges are drawn as outlined cells on the heatmap (they're a drop, not an object). Hovering any map shows position,
P(object), confidence, the object label and the geometric probability.

## 6. Dashboard (`/api/fusion`)

The payload (gzip, typically **~2.6 kB**; mostly-uniform layers compress about 10×):

| Field | Content |
| --- | --- |
| `geo`, `heat`, `sem_p` | base64 uint8, `size²` cells, row-major, row 0 = bottom |
| `sem_label` | base64 uint8 index into `labels` (0 = none) |
| `edges` | flat indices of desk-edge cells |
| `objects` | `id, label, x, y, sigma, radius, p, confidence, age, hits, misses, tracks, source` |
| `pose`, `trail`, `camera` | robot pose, path, camera FOV for the semantic map wedge |
| `stats` | update rate, frames used, observations, sonar-ranged detections, observed / confident area, mean confidence, median age, half-lives |

Cards (from `deskbot/web/static/cards.html`, spliced into the existing page):

- **Geometric map:** classic occupancy shading. White = free, background = unknown/stale, ink = obstacle, orange = desk edge.
  Also the trail and the robot arrow.
- **Semantic map:** faint geometry underneath. Object cells are coloured by label (fixed categorical order; a label keeps
  its colour, which never depends on rank), with opacity = existence confidence. Each object has a direct label
  (`cup 92 %`), with collision-avoided placement, and an uncertainty ring that is dashed once the object has gone unseen
  for 3 s. The camera FOV wedge and the object list (position ±σ, P(still there) bar, last seen) are shown as well.
- **Confidence heatmap:** the diverging map, a gradient legend, confident area, mean confidence and map rate. The
  **Clear maps** button is here.
- In simulation, **Move the mug** relocates the mug, so you can watch the old position fade or get cleared by misses.

## 7. Tunables (`MappingConfig`)

| Name | Default | Effect |
| --- | --- | --- |
| `size`, `resolution` | 80, 0.05 m | 4 m × 4 m map |
| `geo_half_life_s` | 90 s | how fast sonar/IR evidence fades to unknown |
| `sem_half_life_s` | 45 s | how fast objects fade (lower = assume things move more often) |
| `position_drift` | 0.0004 m²/s | how fast an unseen object's position gets uncertain (≈ 13 cm σ after 45 s) |
| `l_hit`, `l_miss` | 1.2, 0.6 | evidence per detection / per miss |
| `max_detect_range` | 1.5 m | ignore detections beyond this (the ground-plane estimate gets poor) |
| `sonar_fuse_deg` | 10° | detections this close to straight ahead use the front ultrasonic for range |
| `gate_m` | 0.15 m | association gate (+ 2σ) |
| `prune_logodds` | −1.0 | delete an object below this evidence |
| `heat_object_weight` | 1.0 | weight of the semantic layer in the heatmap |

**Camera mounting must be measured on the robot** (`CameraConfig`: `x`, `height_m`, `pitch_deg`, `hfov_deg`/`vfov_deg`).
The ground-plane range depends directly on height and pitch. To check them, put a cup 30 cm straight ahead and read its
position in the object list; 1° of pitch error shifts a 30 cm range by about 2 cm. The odometry calibration is the same as
before ([mapping.md §2](mapping.md)).

## 8. Verified (simulation)

- `tests/test_system.py`, simulated robot + simulated camera + `SimDetector` (5 % missed detections, 1.5 px box noise):
  - the cup and bottle are mapped **within 5 cm** of their true positions. A manual run gave 0.6 cm and 1.6 cm errors
    (cup 32.7, 13.4 cm vs. true 33, 14 cm)
  - the heatmap is > 200/255 (confident object) at the cup
  - when the mug is moved behind the robot, the old cup is removed within 4 s and the untouched bottle stays
  - pose interpolation, including the heading wrap at 0/2π
- `tests/test_mapping.py`: cone free/hit, once-per-reading updates, exact half-life, decay folded into updates, clamping,
  edges; Kalman fusion, association with and without track IDs, label separation, misses, out-of-view ≠ miss, fade to
  p ≈ 0.5, variance growth, unlocalised refresh.
- Dashboard rendered in headless Edge: all three maps, the object list, legend and camera card.

**Not run on the real robot yet.** Calibrate the camera mount and odometry first.

## Reflections and glass

The three sensors fail differently on shiny and transparent things:

| Surface | Ultrasonic (HC-SR04) | Camera (YOLO26n) | IR edge sensors (point down) |
| --- | --- | --- | --- |
| glass / acrylic barrier, head-on | **echo**: sound reflects off it | sees **through** it, finds nothing | not affected |
| glass / smooth surface at a steep angle | **specular**: the pulse bounces away. Either no echo (max range) or a late **multipath** echo | sees through it | not affected |
| mirror / glossy screen | echo (it's a surface) | may detect **reflected** objects (a person in a mirror) | not affected |
| shiny / dark desk patch | not affected | not affected | may misread (IR absorbed or reflected away) |

Research: specular sonar returns are a classic failure. A max-range reading should be treated as "free *or* a
missed echo", not strong free space. Glass is often visible in the data but discarded by standard occupancy updates
(Foster et al., ICRA 2013). Cross-checking with another sensor is the usual fix. What is implemented, all in
software, with no new hardware:

| Mechanism | Where | What it does |
| --- | --- | --- |
| **No-echo = weak free** | `grid.sonar(free_delta=…)`, `MappingConfig.l_free_no_echo = −0.10` (normal free: −0.40) | A reading at max range (2.0 m, no echo) clears space 4× more weakly, so one bounced-away pulse can't erase a glass wall the sensor heard head-on a moment ago |
| **Multipath rejection** | `fusion.SonarFilter`, `jump_confirm_m = 0.15`, `jump_confirm_n = 2` | A reading suddenly **longer** than the last accepted one by > 15 cm is held back until it repeats; a detour echo rarely repeats exactly. **Shorter** readings are believed at once, the safe direction. Mapping only: the safety rules still use every raw reading. `stats.multipath_rejected` counts them |
| **Seen through glass / reflection** | `_integrate_frame`, `behind_surface_m = 0.15`, `behind_surface_weight = 0.3` | A detection straight ahead (within ±10°) whose ground-plane range is > 15 cm *beyond* the surface the front sonar hears is behind glass or reflected in it. Its existence evidence is scaled ×0.3 and its source shows as "behind surface". `stats.behind_surface` counts them |
| **"Unrecognised" obstacles** | `FusionMapper._mark_viewed`, `unrecognised()`, `camera_seen_s = 20`, `unexplained_p = 0.7` | The mapper records which cells each frame's camera view covered (stopping at the sonar surface straight ahead). A cell the sonar says is occupied (p > 0.7), that the camera looked at in the last 20 s, with no recognised object on it or next to it, is listed in `/api/fusion` → `unrecognised`. The semantic map draws it **hatched**: "unrecognised (wall / glass)". It stays an obstacle in the heatmap: the camera's silence never overrules the sonar |
| Safety unchanged | motor process | Glass that echoes stops the robot like any obstacle. The sonar, not the camera, is what keeps it from driving into glass |

What it can't do: glass hit at a steep angle that **never** echoes is invisible to every sensor on this robot. The
weak free evidence only makes the map forget slowly. The hardware fix is a ToF/LiDAR sensor (README → Future
improvements). Wet or glossy desk patches that fool the IR edge sensors are not handled.

