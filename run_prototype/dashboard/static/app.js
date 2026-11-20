"use strict";

const POLL_MS = 200;
const SPARK_MAX_CM = 100;
const SVG_NS = "http://www.w3.org/2000/svg";

// BCM -> physical header pin for the wiring card; the server sends the full table from robot_config.py
let PHYSICAL_PIN = {};

const PIN_GROUPS = [
  ["Left motor (L298N)", [["ENA · PWM", "left_enable"], ["IN1 · forward", "left_forward"], ["IN2 · backward", "left_backward"]]],
  ["Right motor (L298N)", [["ENB · PWM", "right_enable"], ["IN3 · forward", "right_forward"], ["IN4 · backward", "right_backward"]]],
  ["Ultrasonic", [["TRIG", "us_trigger"], ["ECHO · via divider", "us_echo"]]],
  ["IR edge sensors", [["Front OUT", "ir_front"], ["Rear OUT", "ir_back"]]],
];

// extra rows when the 4-sonar server is running
const EXTRA_SONAR_GROUPS = [
  ["Left ultrasonic", [["TRIG", "us_left_trigger"], ["ECHO · via divider", "us_left_echo"]]],
  ["Right ultrasonic", [["TRIG", "us_right_trigger"], ["ECHO · via divider", "us_right_echo"]]],
  ["Rear ultrasonic", [["TRIG", "us_rear_trigger"], ["ECHO · via divider", "us_rear_echo"]]],
];

const $ = (id) => document.getElementById(id);

let latest = null;
let duration = 1;
let online = false;
let lastEventId = -1;
let pinsRendered = false;
let draggingSlider = false;
let msgTimer = null;

/* ---------------- API ---------------- */

async function api(path, body) {
  const opts = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

async function command(path, body) {
  try {
    const state = await api(path, body);
    render(state);
    showMessage("");
  } catch (err) {
    showMessage(err.message);
  }
}

function showMessage(text) {
  $("drive-msg").textContent = text;
  clearTimeout(msgTimer);
  if (text) msgTimer = setTimeout(() => ($("drive-msg").textContent = ""), 4000);
}

async function poll() {
  try {
    render(await api("/api/state"));
    setOnline(true);
  } catch {
    setOnline(false);
  }
  setTimeout(poll, POLL_MS);
}

function setOnline(value) {
  if (value === online && $("conn").dataset.state !== "connecting") return;
  online = value;
  $("conn").dataset.state = value ? "online" : "offline";
  $("conn-text").textContent = value ? "Connected" : "Disconnected";
  document.querySelectorAll(".dpad-btn").forEach((b) => (b.disabled = !value));
}

/* ---------------- formatting ---------------- */

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function fmtUptime(sec) {
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

function fmtClock(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
}

function setTag(el, text, kind) {
  el.textContent = text;
  el.classList.toggle("is-ok", kind === "ok");
  el.classList.toggle("is-warn", kind === "warn");
}

/* ---------------- render ---------------- */

function render(s) {
  latest = s;

  // top bar
  const pill = $("mode-pill");
  pill.textContent = s.mode === "simulation" ? "Simulation" : "Hardware";
  pill.dataset.mode = s.mode;
  $("uptime").textContent = fmtUptime(s.uptime);

  renderStatus(s);
  renderDrive(s);
  renderDistance(s);
  renderSonars(s);
  renderEdges(s);
  renderSim(s);
  renderConfig(s);
  renderLog(s);
  if (!pinsRendered) {
    PHYSICAL_PIN = s.physical_pins || {};
    renderPins(s.pins);
  }
}

function renderStatus(s) {
  const dot = $("status-dot");
  dot.dataset.state = s.state;
  let word = "Idle";
  let sub = "Ready for a command.";

  if (s.state === "moving") {
    word = `Moving ${s.direction}`;
    sub = `${Math.round(s.settings.speed * 100)}% speed · checking sensors every ${s.settings.check_interval * 1000} ms`;
  } else if (s.state === "blocked") {
    word = "Safety stop";
    sub = `${s.reason} while moving ${s.direction}.`;
  } else if (s.state === "error") {
    word = "Error";
    sub = s.reason || "Something went wrong.";
  }
  $("status-word").textContent = word;
  $("status-sub").textContent = sub;

  const fill = $("progress-fill");
  if (s.state === "moving" && s.duration > 0) {
    const elapsed = s.duration - s.remaining;
    fill.style.width = `${Math.min(100, (elapsed / s.duration) * 100)}%`;
    $("progress-label").textContent = `${elapsed.toFixed(1)} / ${s.duration.toFixed(1)} s`;
  } else {
    fill.style.width = "0";
    $("progress-label").innerHTML = "&nbsp;";
  }

  if (s.sonars) {
    const why = { forward: "front IR + sonar", backward: "rear IR + sonar", left: "both IR + sides", right: "both IR + sides" };
    document.querySelectorAll("#clear-grid li").forEach((li) => (li.querySelector(".clear-why").textContent = why[li.dataset.dir]));
  }
  document.querySelectorAll("#clear-grid li").forEach((li) => {
    const ok = s.clear ? s.clear[li.dataset.dir] : null;
    li.classList.toggle("is-ok", ok === true);
    li.classList.toggle("is-warn", ok === false);
  });

  $("move-count").textContent = s.stats.moves ? `move #${s.stats.moves}` : "no moves yet";
  $("stat-moves").textContent = s.stats.moves;
  $("stat-completed").textContent = s.stats.completed;
  $("stat-safety").textContent = s.stats.safety_stops;
  $("stat-user").textContent = s.stats.user_stops;
}

function renderDrive(s) {
  document.querySelectorAll(".dpad-btn[data-dir]").forEach((b) => {
    b.classList.toggle("is-active", s.state === "moving" && b.dataset.dir === s.direction);
  });
}

function renderDistance(s) {
  const d = s.sensors.distance;
  const stopCm = s.settings.stop_distance * 100;
  const maxCm = s.settings.max_distance * 100;

  if (d == null) {
    $("distance-value").textContent = "—";
    setTag($("distance-tag"), "No reading", null);
  } else {
    const cm = d * 100;
    $("distance-value").textContent = cm >= maxCm - 0.5 ? `>${maxCm.toFixed(0)}` : cm.toFixed(1);
    if (cm <= stopCm) setTag($("distance-tag"), "In stop zone", "warn");
    else setTag($("distance-tag"), "Clear", "ok");
  }

  // sparkline: fixed window, newest sample on the right
  const W = 300, H = 96;
  const y = (cm) => H - (Math.min(cm, SPARK_MAX_CM) / SPARK_MAX_CM) * H;
  const n = s.history_len;
  const hist = s.history;
  const offset = n - hist.length;
  let line = "";
  hist.forEach((cm, i) => {
    const x = ((offset + i) / (n - 1)) * W;
    line += `${i ? "L" : "M"}${x.toFixed(1)} ${y(cm).toFixed(1)}`;
  });
  $("spark-line").setAttribute("d", line);
  if (hist.length > 1) {
    const x0 = (offset / (n - 1)) * W;
    $("spark-area").setAttribute("d", `${line}L${W} ${H}L${x0.toFixed(1)} ${H}Z`);
  } else {
    $("spark-area").setAttribute("d", "");
  }
  const ty = y(stopCm);
  $("spark-threshold").setAttribute("y1", ty);
  $("spark-threshold").setAttribute("y2", ty);
  $("spark-zone").setAttribute("y", ty);
  $("spark-zone").setAttribute("height", Math.max(0, H - ty));
  $("spark-scale").textContent = `0–${SPARK_MAX_CM} cm · stop ${stopCm.toFixed(0)} cm`;

  const fmtCm = (cm) => (cm >= maxCm - 0.5 ? `>${maxCm.toFixed(0)}` : cm.toFixed(1));
  if (hist.length) {
    $("us-min").textContent = `${fmtCm(Math.min(...hist))} cm`;
    $("us-avg").textContent = `${fmtCm(hist.reduce((a, b) => a + b, 0) / hist.length)} cm`;
  }
  $("us-stops").textContent = s.stop_counts.obstacle;
}

const SONAR_PX_PER_M = 300;   // sensor mount positions in the top view
const SONAR_BEAM_MAX_M = 1.0;  // beams longer than this are drawn at full length
let sonarListBuilt = false;

function renderSonars(s) {
  const card = $("sonar-card");
  if (!s.sonars) {
    card.hidden = true;
    return;
  }
  card.hidden = false;

  const beams = $("sonar-beams");
  const list = $("sonar-list");
  if (!sonarListBuilt) {
    for (const so of s.sonars) {
      const g = document.createElementNS(SVG_NS, "g");
      for (const cls of ["sonar-beam", "sonar-beam-edge"]) {
        const p = document.createElementNS(SVG_NS, "path");
        p.setAttribute("class", cls);
        g.appendChild(p);
      }
      const t = document.createElementNS(SVG_NS, "text");
      t.setAttribute("class", "sonar-label");
      g.appendChild(t);
      beams.appendChild(g);

      const li = document.createElement("li");
      const info = document.createElement("div");
      const name = document.createElement("div");
      name.className = "sensor-name";
      name.textContent = cap(so.name);
      const pin = document.createElement("div");
      pin.className = "sensor-pin mono";
      pin.textContent = `GPIO ${so.trigger}/${so.echo}`;
      pin.title = `TRIG GPIO ${so.trigger}, ECHO GPIO ${so.echo}; checked when moving ${so.used_for}`;
      info.append(name, pin);
      const tag = document.createElement("span");
      tag.className = "tag";
      li.append(info, tag);
      list.appendChild(li);
    }
    sonarListBuilt = true;
  }

  const maxCm = s.settings.max_distance * 100;
  let closest = null;
  s.sonars.forEach((so, i) => {
    const warn = so.distance != null && so.distance <= so.stop;
    // top view, forward is up: robot frame (x fwd, y left) -> svg (-y, -x)
    const ox = -so.y * SONAR_PX_PER_M, oy = -so.x * SONAR_PX_PER_M;
    const a = (so.angle * Math.PI) / 180;
    const dir = (ang) => [-Math.sin(ang), -Math.cos(ang)];
    const len = so.distance == null ? 0 : 16 + (Math.min(so.distance, SONAR_BEAM_MAX_M) / SONAR_BEAM_MAX_M) * 48;
    const half = (7.5 * Math.PI) / 180;
    const [lx, ly] = dir(a + half), [rx, ry] = dir(a - half), [cx, cy] = dir(a);
    const arc = `${ox + lx * len} ${oy + ly * len}A${len} ${len} 0 0 0 ${ox + rx * len} ${oy + ry * len}`;
    const g = beams.children[i];
    g.children[0].setAttribute("d", `M${ox} ${oy}L${arc}Z`);
    g.children[1].setAttribute("d", `M${arc}`);
    g.children[0].setAttribute("class", `sonar-beam${warn ? " is-warn" : ""}`);
    g.children[1].setAttribute("class", `sonar-beam-edge${warn ? " is-warn" : ""}`);

    const cm = so.distance == null ? null : so.distance * 100;
    const text = cm == null ? "—" : cm >= maxCm - 0.5 ? `>${maxCm.toFixed(0)}` : cm.toFixed(0);
    const label = g.children[2];
    label.setAttribute("x", ox + cx * (len + 14));
    label.setAttribute("y", oy + cy * (len + 9));
    label.textContent = text;

    const tag = list.children[i].querySelector(".tag");
    if (cm == null) setTag(tag, "No reading", null);
    else setTag(tag, `${text} cm`, warn ? "warn" : "ok");
    if (cm != null && (closest == null || cm < closest.cm)) closest = { cm, name: so.name };
  });

  $("sonar-closest").textContent = closest ? `${closest.cm.toFixed(0)} cm ${closest.name}` : "—";
  $("sonar-rear-stops").textContent = s.stop_counts.rear_obstacle ?? 0;
  $("sonar-side-stops").textContent = s.stop_counts.side_obstacle ?? 0;
}

function renderEdges(s) {
  const pairs = [
    [s.sensors.front_floor, "ir-front-dot", "ir-front-tag"],
    [s.sensors.back_floor, "ir-back-dot", "ir-back-tag"],
  ];
  for (const [floor, dotId, tagId] of pairs) {
    const dot = $(dotId);
    if (floor == null) {
      dot.setAttribute("class", "rt-ir");
      setTag($(tagId), "No reading", null);
      continue;
    }
    dot.setAttribute("class", `rt-ir ${floor ? "is-ok" : "is-warn"}`);
    setTag($(tagId), floor ? "Floor" : "Edge", floor ? "ok" : "warn");
  }
  $("edge-front").textContent = s.stop_counts.front_edge;
  $("edge-rear").textContent = s.stop_counts.rear_edge;
  $("edge-turn").textContent = s.stop_counts.turn_edge;
}

let obstaclesDrawn = false;

function renderSim(s) {
  const card = $("sim-card");
  if (!s.sim) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  const sim = s.sim;
  const k = 1000; // metres -> svg units (mm)
  const H = sim.desk.h * k;
  const sx = (x) => x * k;
  const sy = (yy) => H - yy * k;

  if (!obstaclesDrawn) {
    const g = $("desk-obstacles");
    for (const ob of sim.obstacles) {
      let shape;
      let cx, cy;
      if (ob.kind === "circle") {
        shape = document.createElementNS(SVG_NS, "circle");
        shape.setAttribute("cx", sx(ob.x));
        shape.setAttribute("cy", sy(ob.y));
        shape.setAttribute("r", ob.r * k);
        cx = sx(ob.x);
        cy = sy(ob.y) + ob.r * k + 30;
      } else {
        shape = document.createElementNS(SVG_NS, "rect");
        shape.setAttribute("x", sx(ob.x));
        shape.setAttribute("y", sy(ob.y + ob.h));
        shape.setAttribute("width", ob.w * k);
        shape.setAttribute("height", ob.h * k);
        shape.setAttribute("rx", 8);
        cx = sx(ob.x + ob.w / 2);
        cy = sy(ob.y + ob.h / 2);
      }
      shape.setAttribute("class", "desk-ob");
      g.appendChild(shape);
      const label = document.createElementNS(SVG_NS, "text");
      label.setAttribute("class", "desk-ob-label");
      label.setAttribute("x", cx);
      label.setAttribute("y", cy);
      label.textContent = ob.label;
      g.appendChild(label);
    }
    obstaclesDrawn = true;
  }

  const deg = (sim.theta * 180) / Math.PI;
  $("desk-robot").setAttribute("transform", `translate(${sx(sim.x).toFixed(1)} ${sy(sim.y).toFixed(1)}) rotate(${(-deg).toFixed(1)})`);

  // one dashed ray per ultrasonic sensor, drawn to where it hit
  const sources = s.sonars
    ? s.sonars.map((so) => ({ x: so.x, y: so.y, a: (so.angle * Math.PI) / 180, d: so.distance }))
    : [{ x: sim.sonar_offset, y: 0, a: 0, d: s.sensors.distance }];
  const rays = $("desk-rays");
  while (rays.childElementCount < sources.length) {
    const line = document.createElementNS(SVG_NS, "line");
    line.setAttribute("class", "desk-ray");
    rays.appendChild(line);
  }
  const c = Math.cos(sim.theta), sn = Math.sin(sim.theta);
  sources.forEach((src, i) => {
    const line = rays.children[i];
    if (src.d == null || src.d >= s.settings.max_distance - 0.005) {
      line.style.display = "none";
      return;
    }
    const ox = sim.x + src.x * c - src.y * sn;
    const oy = sim.y + src.x * sn + src.y * c;
    const a = sim.theta + src.a;
    line.setAttribute("x1", sx(ox));
    line.setAttribute("y1", sy(oy));
    line.setAttribute("x2", sx(ox + src.d * Math.cos(a)));
    line.setAttribute("y2", sy(oy + src.d * Math.sin(a)));
    line.style.display = "";
  });

  $("desk-ir-front").setAttribute("class", `desk-ir ${s.sensors.front_floor === false ? "is-warn" : ""}`);
  $("desk-ir-back").setAttribute("class", `desk-ir ${s.sensors.back_floor === false ? "is-warn" : ""}`);
  const heading = ((90 - deg) % 360 + 360) % 360; // compass-style: 0 = towards the wall
  $("desk-pose").textContent = `x ${(sim.x * 100).toFixed(0)} cm · y ${(sim.y * 100).toFixed(0)} cm · ${heading.toFixed(0)}°`;
}

function renderConfig(s) {
  const speedPct = Math.round(s.settings.speed * 100);
  const stopCm = Math.round(s.settings.stop_distance * 100);
  if (!draggingSlider) {
    $("speed-input").value = speedPct;
    $("stopdist-input").value = stopCm;
    $("speed-value").textContent = `${speedPct}%`;
    $("stopdist-value").textContent = `${stopCm} cm`;
  }
  $("cfg-interval").textContent = `${s.settings.check_interval * 1000} ms`;
  $("cfg-floor").textContent = s.settings.floor_value === 0 ? "LOW (0)" : "HIGH (1)";
  $("cfg-range").textContent = `${s.settings.max_distance * 100} cm`;
  $("cfg-maxdur").textContent = `${s.settings.max_duration} s`;
  $("duration-input").max = s.settings.max_duration;
}

function renderLog(s) {
  const events = s.events;
  const newest = events.length ? events[events.length - 1].id : 0;
  if (newest === lastEventId) return;
  lastEventId = newest;

  const list = $("log");
  list.replaceChildren();
  if (!events.length) {
    const li = document.createElement("li");
    li.className = "log-empty";
    li.textContent = "Nothing yet.";
    list.appendChild(li);
  }
  for (const ev of [...events].reverse()) {
    const li = document.createElement("li");
    const time = document.createElement("span");
    time.className = "log-time mono";
    time.textContent = fmtClock(ev.t);
    const level = document.createElement("span");
    level.className = "log-level";
    level.dataset.level = ev.level;
    level.textContent = ev.level;
    const msg = document.createElement("span");
    msg.className = "log-msg";
    msg.textContent = ev.msg;
    li.append(time, level, msg);
    list.appendChild(li);
  }
  $("log-count").textContent = `${events.length} recent`;
}

function renderPins(pins) {
  const body = $("pins-body");
  const groups = pins.us_left_trigger !== undefined
    ? PIN_GROUPS.map(([g, r]) => [g === "Ultrasonic" ? "Front ultrasonic" : g, r]).concat(EXTRA_SONAR_GROUPS)
    : PIN_GROUPS;
  for (const [group, rows] of groups) {
    const gr = document.createElement("tr");
    gr.className = "group";
    const gtd = document.createElement("td");
    gtd.colSpan = 3;
    gtd.textContent = group;
    gr.appendChild(gtd);
    body.appendChild(gr);
    for (const [label, key] of rows) {
      const tr = document.createElement("tr");
      const bcm = pins[key];
      for (const text of [label, bcm, PHYSICAL_PIN[bcm] ?? "—"]) {
        const td = document.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      }
      body.appendChild(tr);
    }
  }
  pinsRendered = true;
}

/* ---------------- controls ---------------- */

function move(direction) {
  if (!online) return;
  command("/api/move", { direction, duration });
}

function stop() {
  command("/api/stop", {});
}

function setDuration(value, fromPreset) {
  const max = latest ? latest.settings.max_duration : 10;
  if (!Number.isFinite(value) || value <= 0) return;
  duration = Math.min(value, max);
  document.querySelectorAll("#duration-presets button").forEach((b) => {
    b.classList.toggle("is-selected", Number(b.dataset.duration) === duration);
  });
  if (fromPreset) $("duration-input").value = duration;
}

document.querySelectorAll(".dpad-btn[data-dir]").forEach((btn) => {
  btn.addEventListener("click", () => move(btn.dataset.dir));
});
$("stop-btn").addEventListener("click", stop);

document.querySelectorAll("#duration-presets button").forEach((btn) => {
  btn.addEventListener("click", () => setDuration(Number(btn.dataset.duration), true));
});
$("duration-input").addEventListener("input", (e) => setDuration(parseFloat(e.target.value), false));

function bindSlider(inputId, valueId, format, toBody) {
  const input = $(inputId);
  input.addEventListener("pointerdown", () => (draggingSlider = true));
  input.addEventListener("input", () => {
    draggingSlider = true;
    $(valueId).textContent = format(Number(input.value));
  });
  input.addEventListener("change", async () => {
    await command("/api/settings", toBody(Number(input.value)));
    draggingSlider = false;
  });
}
bindSlider("speed-input", "speed-value", (v) => `${v}%`, (v) => ({ speed: v / 100 }));
bindSlider("stopdist-input", "stopdist-value", (v) => `${v} cm`, (v) => ({ stop_distance: v / 100 }));

$("sim-reset").addEventListener("click", () => command("/api/sim/reset", {}));

const KEYS = {
  ArrowUp: "forward", w: "forward", W: "forward",
  ArrowDown: "backward", s: "backward", S: "backward",
  ArrowLeft: "left", a: "left", A: "left",
  ArrowRight: "right", d: "right", D: "right",
};

document.addEventListener("keydown", (e) => {
  if (e.target.closest("input, textarea, select")) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === " " || e.key === "Escape") {
    e.preventDefault();
    stop();
    return;
  }
  const dir = KEYS[e.key];
  if (dir && !e.repeat) {
    e.preventDefault();
    move(dir);
  }
});

/* ---------------- occupancy map (only with server_mapping.py) ---------------- */

const MAP_POLL_MS = 400;
const map = { version: 0, epoch: -1, size: 0, res: 0.05, cells: null, info: null };

async function pollMap() {
  try {
    const res = await fetch(`/api/map?since=${map.version}&epoch=${map.epoch}`);
    if (res.status === 404) return; // plain server.py: no mapping, card stays hidden
    const data = await res.json();
    applyMap(data);
    $("map-card").hidden = false;
  } catch {
    /* connection state is shown by the main poll */
  }
  setTimeout(pollMap, MAP_POLL_MS);
}

function applyMap(d) {
  if (d.full || !map.cells || d.size !== map.size || d.epoch !== map.epoch) {
    map.size = d.size;
    map.cells = new Uint8Array(d.size * d.size);
    if (d.full) for (let i = 0; i < d.cells.length; i++) map.cells[i] = d.cells.charCodeAt(i) - 48;
  }
  if (!d.full) for (const [i, code] of d.cells) map.cells[i] = code;
  map.version = d.version;
  map.epoch = d.epoch;
  map.res = d.resolution;
  map.info = d;
  drawMap();
}

function drawMap() {
  const canvas = $("map-canvas");
  const ctx = canvas.getContext("2d");
  const n = map.size;
  const scale = canvas.width / n;
  const css = getComputedStyle(document.documentElement);
  const color = (name) => css.getPropertyValue(name).trim();
  const palette = [color("--map-unknown"), color("--map-free"), color("--ink"), color("--warn")];

  // cells: row 0 of the grid is the bottom of the map (y up), canvas y goes down
  ctx.fillStyle = palette[0];
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      const code = map.cells[r * n + c];
      if (!code) continue;
      ctx.fillStyle = palette[code];
      ctx.fillRect(c * scale, (n - 1 - r) * scale, scale, scale);
    }
  }

  // 1 m grid lines + origin cross
  const perMetre = Math.round(1 / map.res);
  ctx.strokeStyle = color("--border-strong");
  ctx.globalAlpha = 0.6;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let k = n / 2 % perMetre; k <= n; k += perMetre) {
    const p = Math.round(k * scale) + 0.5;
    ctx.moveTo(p, 0); ctx.lineTo(p, canvas.height);
    ctx.moveTo(0, p); ctx.lineTo(canvas.width, p);
  }
  ctx.stroke();
  ctx.globalAlpha = 1;

  const px = (x) => (x / map.res + n / 2) * scale;
  const py = (y) => (n / 2 - y / map.res) * scale;

  // trail
  const trail = map.info.trail;
  if (trail.length > 1) {
    ctx.strokeStyle = color("--move");
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.beginPath();
    trail.forEach(([x, y], i) => (i ? ctx.lineTo(px(x), py(y)) : ctx.moveTo(px(x), py(y))));
    ctx.stroke();
  }

  // robot pose
  const { x, y, theta } = map.info.pose;
  ctx.save();
  ctx.translate(px(x), py(y));
  ctx.rotate(-theta);
  ctx.fillStyle = color("--move");
  ctx.strokeStyle = color("--card");
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(14, 0);
  ctx.lineTo(-9, 9);
  ctx.lineTo(-4, 0);
  ctx.lineTo(-9, -9);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.restore();

  // text
  const info = map.info;
  const cellArea = map.res * map.res;
  const known = info.counts.free + info.counts.occupied + info.counts.edge;
  $("map-area").textContent = `${(known * cellArea).toFixed(2)} m²`;
  $("map-occ").textContent = `${info.counts.occupied} / ${info.counts.edge}`;
  $("map-rate").textContent = `${info.rate_hz.toFixed(1)} Hz`;
  const heading = ((((theta * 180) / Math.PI) % 360) + 360) % 360; // 0° = start heading, CCW positive
  $("map-pose").textContent = `${(x * 100).toFixed(0)}, ${(y * 100).toFixed(0)} cm · ${heading.toFixed(0)}°`;
  $("map-grid").textContent = `${n}×${n} · ${(map.res * 100).toFixed(0)} cm`;
}

$("map-reset").addEventListener("click", async () => {
  try {
    await api("/api/map/reset", {});
  } catch (err) {
    showMessage(err.message);
  }
});

// redraw with the new palette when the OS theme flips
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => map.info && drawMap());
window.addEventListener("deskbot-theme", () => map.info && drawMap());   // pro dashboard theme switch (20 Nov 2026)

poll();
pollMap();
