# Obstacle-to-obstacle navigation

Ask the robot **"go from the cup to the bottle"** and it drives to the cup, then to the bottle, around everything
else on the desk. It measures each planning problem and picks the path planner that suits it.

| How to ask | Example |
|---|---|
| Voice or typed text | "go from the mug to the book", "drive to the bottle", "go from the nearest obstacle to obstacle 2" |
| API | `POST /api/assistant/commands` with `{"commands": [{"action": "navigate", "from_object": "cup", "to_object": "bottle"}]}` |
| Script, running robot | `python tools/navigate.py --from cup --to bottle --url http://localhost:8000` |
| Script, simulation | `python tools/navigate.py --from cup --to book --start 0.15 0.15 --stop-distance 0.10` |
| Compare the planners | `python tools/navigate.py --compare` (also `python main.py navigate --compare`) |

`from_object` is optional. Progress, the chosen planner, its reasons and the route are in `navigation` in
`GET /api/assistant`. The simulated run saves `route.png` and `report.json` in `outputs/navigation/<time>/`.

## Files

| File | Job |
|---|---|
| `deskbot/navigation/costmap.py` | Live maps to a planning grid that knows what the motor safety rules allow |
| `deskbot/navigation/planners.py` | The six planners and route shortening |
| `deskbot/navigation/selector.py` | Problem measurements, selection rules, fallbacks, window growth |
| `deskbot/navigation/navigator.py` | Name lookup, driving, replanning, recovery |
| `deskbot/navigation/scenes.py` | Synthetic desks for the tests and `--compare` |
| `navigate.py` | The runnable script |
| `tests/test_navigation.py` | Unit tests, including a fake robot |

Small hooks in existing code: `navigate` in `assistant/commands.py` (action, schema with `from_object`/`to_object`,
executor branch), phrase parsing and prompt text in `assistant/brain.py`, unidentified obstacles in the AI context
(`assistant/core.py`), creation and status in `assistant/app.py`, `NavigationConfig` in `config.py`, a tool entry in
`companion/cli.py`. Gestures can't trigger `navigate`, because a gesture can't name an object.

## From request to motion

1. **Names.** `find_target` matches map labels and synonyms (mug = cup, phone = cell phone, notebook = book). With
   several matches it takes the nearest. `obstacle 2` means the second-nearest sonar obstacle that no camera object
   explains. `nearest obstacle` and `farthest obstacle` consider everything. A missing name triggers a search (below).
2. **Grid.** The 5 cm maps are copied under the mapper's lock, then resampled into a window around the robot and the
   target: 2.5 cm cells up to a 2.5 m window, otherwise 5 cm.
3. **Selection and planning** (below). The robot stands still while planning.
4. **Driving.** Turn to the next waypoint (within 6 degrees), drive a hop of at most 20 cm with `robot.move`, then re-read
   the pose and the map. Moves go through the normal motor process, so every safety rule still applies.
5. **Replanning**, up to 8 times per leg: the way ahead changed, the target moved more than 8 cm, the robot is more than
   8 cm off the route, or a safety rule stopped it. A stop is remembered for the trip: a sonar stop becomes a small
   obstacle, a desk-edge stop becomes a 30 cm line of edge. After an edge or side stop the robot reverses 5 cm first.
6. **Arrival.** It stops on a ring around the target and turns to face it.

Face-the-user is paused during a trip. `stop`, a new command, the remote, being lifted or going to sleep cancels the trip
through the executor's normal cancel signal. Resetting the map ends it.

## The safety rule that shapes every route

The motor process stops a forward move when the front sonar reads at or below `stop_distance` (20 cm). A route that only
avoids collisions can therefore be undrivable: it may head at a wall and plan to turn just before it. So a segment A to B
is valid only if

- every point on it is at least `robot_radius + clearance_margin` = 10 cm from anything solid or any known edge, and
- nothing solid lies within `lookahead` past B, in the direction of travel, widened by the sonar beam.

```
lookahead = sonar offset (6 cm) + stop_distance + brake_margin (1.5 cm)        = 27.5 cm
cone_pad  = max(cell size, tan(7.5 deg) x stop_distance)                       = 2.6 cm
standoff  = lookahead + cone_pad + cell size                                   = 32.6 cm
```

`standoff` is the distance from the target's surface to the robot's centre when it stops (all at the default stop distance
and 2.5 cm cells). Stopping places are the free cells from `standoff` to `standoff + 4 cm`. Lowering the stop distance
lets the robot come closer. The safety limit itself is never changed by navigation.

## The planners

| Planner | Idea | Good at | Weak at |
|---|---|---|---|
| `direct` | One straight segment | Clear line, no search | Anything in the way |
| `theta_star` | Grid search whose parent can be any visible ancestor | Shortest routes on the test desks, few turns | About 12x the time of A* |
| `visibility` | A* over obstacle corners and goal samples | Very cheap with few obstacles | Longer routes here: the sonar rule forbids many corner-to-corner segments |
| `astar` | 8-connected search on a cost field | Keeps away from obstacles and unobserved floor; explores every reachable cell | Routes 10-30% longer because it buys clearance |
| `weighted_astar` | A* with the heuristic multiplied by 1.8 | Fast in clutter | Further from optimal |
| `rrt_connect` | Two random trees growing toward each other (fixed seed) | Open space when grid search is too slow | Longest routes, can miss narrow gaps |

Everything is pure Python plus numpy, with no new dependency.

## Adaptive selection

Measured for every plan:

| Variable | Meaning |
|---|---|
| `n_obstacles` | Separate solid things in the window |
| `density` | Share of the window the robot's centre can't occupy |
| `line_clear` | Clear line to a stopping place about as close as the nearest one (within 1.25x + 5 cm) |
| `n_on_route` | Obstacles the straight line runs into |
| `tight_on_route` | Gaps near the line that the robot fits through with under 3 cm to spare per side |
| `unknown_frac` | Share of the straight corridor nobody has observed |
| `object_sigma` | Mean position uncertainty of camera objects |
| `distance_m`, `free_cells`, `vertices` | Size of the search |
| `predicted_ms` | Expected A* time, from the search speed measured on this machine |

Rules, first match wins:

| # | Condition | Planner |
|---|---|---|
| 1 | Line clear, and under 45% of it unobserved | `direct` |
| 2 | Predicted A* time over 150 ms | `rrt_connect` if at most 10% blocked, else `weighted_astar` |
| 3 | At least 45% of the corridor unobserved, or object sigma at least 10 cm | `astar` |
| 4 | Tight gap on the way, at least 30% blocked, or at least 14 obstacles | `astar` |
| 5 | Predicted Theta* time (12x A*) within 150 ms | `theta_star` |
| 6 | At most 6 obstacles and at most 70 corners | `visibility` |
| 7 | Otherwise | `astar` |

The other planners follow as fallbacks. Each may use 300 ms; A* may use 1.5 s. Every route is shortened and re-validated
before use. If nothing is found, the window widens (45 cm, 1 m, whole map), because the way round may lie outside it.
Search speed is an exponential average of real searches, so a slower Pi moves toward rules 2 and 6 by itself.

### Measured on the laptop (`navigate.py --compare`, route cm / planner ms)

| Desk | Obstacles | Blocked | Chosen | visibility | Theta* | A* | weighted A* | RRT-Connect |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| open desk | 1 | 4% | direct (81 / 0) | 81 / 1 | 80 / 8 | 80 / 0 | 80 / 0 | 81 / 1 |
| one obstacle | 2 | 24% | visibility | 107 / 5 | 103 / 43 | 119 / 6 | 112 / 1 | 114 / 4 |
| few obstacles | 2 | 7% | Theta* | 124 / 3 | 97 / 8 | 139 / 3 | 131 / 2 | 120 / 4 |
| many obstacles | 13 | 24% | A* | 134 / 54 | 128 / 83 | 136 / 23 | 133 / 5 | 176 / 6 |
| clutter | 14 | 16% | A* | 130 / 6 | 127 / 4 | 160 / 4 | 160 / 3 | 138 / 12 |
| narrow gap | 3 | 15% | A* | 121 / 2 | 89 / 70 | 94 / 11 | 94 / 7 | 97 / 8 |
| unexplored | 2 | 19% | A* | 103 / 13 | 96 / 82 | 111 / 15 | 111 / 11 | 107 / 4 |
| long open route | 4 | 2% | visibility | 810 / 28 | 804 / 939 | 810 / 40 | 810 / 3 | 848 / 36 |
| walled off | 2 | 5% | correctly refuses | - | - | - | - | - |

Timings vary between runs. The rules and thresholds are hand-set from these desks, not learned or tuned on the real robot.
The time prediction is a rough fit and can be several times too high (on "one obstacle" it expected 208 ms for Theta*,
which took 43 ms), which makes the selector cautious rather than slow.

## Home, no-go zones and what the robot remembers

`deskbot/navigation/memory.py` keeps `data/nav_memory.json` (`nav_memory_sim.json` in simulation):

| Item | Set by | Effect on routes |
|---|---|---|
| Home | "this is home", or **Set home here** | "go home" drives to that exact spot and restores the heading |
| No-go zones | Drag on the **Navigation** card, or `POST /api/nav/memory` with `{"add": [[x, y], ...]}` | Hard: the body stays out (3-12 points, at most 24 zones) |
| Avoid points | Automatic, where a safety rule stopped the robot | Soft: +2 cost within 8 cm |
| Corridors | Automatic, cells driven at least twice | Soft: other floor costs +0.3 |

Soft costs affect A* and weighted A*. Hard zones affect every planner.

**Alignment.** Places are stored in map coordinates, and the map's origin is where the robot was when that map began. After a
restart or map reset (the default after a long pick-up) the memory is switched off instead of being trusted. Saying "this is
home" with the robot on its home spot moves everything by the rigid transform from the old home pose to the new one.
**It started from the same spot** on the card accepts the old coordinates. While misaligned, new zones are refused.

## Searching for something missing

If a name isn't on the map the robot turns once on the spot, then visits up to 3 places about 35 cm away, preferring unobserved
floor and places it hasn't tried, and looks around at each. If that fails it says "I cannot seem to find the ...", plays the
embarrassed motif and, on the companion runtime, shows the `embarrassed` face for 8 s.

## Confidence

Each plan gets `confidence = P(target exists) x (1 - 0.6 x unknown_frac) / (1 + sigma / 10 cm)`. Below 0.45 the robot says so,
plays the low-confidence motif and halves its hop length, so it re-checks the map twice as often. It is shown on the card and in
`GET /api/assistant`. The formula is hand-set and has not been validated against real outcomes.

## Tunables

All in `NavigationConfig` (`deskbot/config.py`), each with a comment. The ones most worth changing on the real robot:
`robot_radius`, `clearance_margin`, `time_budget_ms`, `hop_m`, `few_obstacles`, `many_obstacles`, `cluttered_density`.

## Limits

- **Tested in simulation only.** It has not run on the real robot or on a Pi, so Pi timing is unmeasured.
- **Position is dead reckoning**, with gyro heading on the companion runtime. There is no wheel-encoder or map correction,
  so error grows with distance. Real trips will be less accurate than simulated ones.
- **Desk edges are unknown until the IR sensors see them.** The first route may head off the desk. The IR rule stops the
  robot and it replans. One simulated trip needed 4 such stops before it found its way.
- **"At" the object means outside the sonar limit:** about 33-37 cm from its surface by default, less with a smaller stop
  distance. On a small desk two objects' rings can nearly touch, so a leg may be very short.
- **Objects are discs** of a typical size per class, so long objects such as books are approximate.
- **`obstacle N` numbers change** as the robot moves, because they are ordered by distance. A number is fixed when its leg starts.
- The Navigation card has been exercised through its API; its drawing and dragging still need a check in a real browser.

## Testing

```bash
python -m unittest tests.test_navigation        # no hardware
python tools/navigate.py --compare
python tools/navigate.py --from cup --to book --start 0.15 0.15 --stop-distance 0.10
python -m deskbot assistant --sim               # then type: go from the book to the bottle
```

## Smooth driving (robots with direct wheel commands)

On the multi-process robot the route is followed continuously at 20 Hz instead of in stop-and-go hops. Speed falls with heading error,
near the destination and as the front sonar approaches its limit. The robot only spins on the spot above 60 degrees of error, and each wheel
command changes by at most 0.08 per tick. When something is within 10 cm of the stop distance on a non-final leg, it bends toward the side
with more sonar room. The motor process still applies every safety rule and stops by itself if commands stop arriving. The simple
single-process robot and the tests keep the hop-based follower. The gains are untuned on real hardware.
