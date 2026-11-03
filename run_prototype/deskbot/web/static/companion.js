/* Companion cards: eyes, saved outputs, calibration, IMU, control plot, gestures + "Save" on every figure. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const STILL = new URLSearchParams(location.search).has("still");
  const post = async (url, body = {}) => {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || r.statusText);
    return data;
  };
  const make = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const stamp = () => new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  const label = (s) => s.replace(/_/g, " ");
  let state = null, gesturesDirty = false, plotRows = [];

  /* ---- save one figure from its dashboard card ---- */
  function download(href, name) {
    const a = make("a");
    a.href = href; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
  }
  function addSaver(cardId, name, getBlobUrl) {
    const head = document.querySelector(`#${cardId} .card-head`);
    if (!head) return;
    const b = make("button", "btn-ghost card-saver", "Save");
    b.title = `Download this figure as ${name}`;
    b.addEventListener("click", () => getBlobUrl((url, ext) => download(url, `${name}_${stamp()}.${ext}`)));
    head.appendChild(b);
  }
  const canvasSaver = (id) => (done) => $(id).toBlob((blob) => {
    const url = URL.createObjectURL(blob);
    done(url, "png");
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  });
  addSaver("vision-card", "camera", (done) => done("/camera.jpg", "jpg"));
  addSaver("geo-card", "geometric_map", canvasSaver("geo-canvas"));
  addSaver("sem-card", "semantic_map", canvasSaver("sem-canvas"));
  addSaver("heat-card", "confidence_heatmap", canvasSaver("heat-canvas"));
  addSaver("co-control-card", "control_loop", canvasSaver("co-plot"));
  addSaver("co-face-card", "eyes", (done) => done("/face.png", "png"));

  /* ---- rendering ---- */
  function renderOutputs(o) {
    $("co-folder").textContent = o.folder;
    $("co-save").disabled = o.saving;
    $("co-save").textContent = o.saving ? "Saving…" : "Save figures";
    $("co-save-state").textContent = o.last ? `Last save: ${o.last.files.length} files (${o.last.reason}, ${new Date(o.last.t * 1000).toLocaleTimeString()})` : "Figures also save automatically every few minutes.";
    $("co-files").replaceChildren(...o.files.slice(0, 14).map((f) => {
      const li = make("li");
      const a = make("a", null, f.name);
      a.href = "/outputs/" + f.path.split("/").map(encodeURIComponent).join("/");
      a.download = f.name;
      li.append(a, make("span", "mono", `${f.kb} kB`));
      return li;
    }));
  }

  function renderCalibration(c) {
    const run = c.run;
    const running = !!(run && run.running);
    $("co-cal").textContent = running ? "Cancel" : "Run full calibration";
    const v = c.values || {};
    $("co-cal-summary").textContent = running ? `Running: ${run.current || "…"} (${run.results.length + 1} of ${run.total})`
      : c.date ? `Last calibrated ${c.date.replace("T", " ")}` + (v.turn_deg_s ? ` · turns ${Math.round(v.turn_deg_s)}°/s` : "") + (v.forward_m_s ? ` · drives ${(v.forward_m_s * 100).toFixed(1)} cm/s` : "")
      : "Not calibrated yet. The robot will move a little: give it about 30 cm of clear desk all round.";
    $("co-cal-steps").replaceChildren(...(run ? run.results : []).map((r) => {
      const li = make("li", r.status);
      li.append(make("b", null, r.status.toUpperCase()), make("span", null, `${r.title}: ${r.message}`));
      return li;
    }));
  }

  function renderBody(s) {
    const i = s.imu;
    $("co-tilt").textContent = i ? `${i.tilt}°` : "no IMU";
    $("co-yaw").textContent = i ? `${i.yaw}°` : "—";
    $("co-gz").textContent = i ? `${i.gz} rad/s` : "—";
    const l = s.lift;
    $("co-lift").textContent = l.lifted ? `Picked up: ${l.trigger || "lifted"}.` : `On the desk${i && i.still ? ", still" : ""}. Picked up ${l.lifts} times, ${l.map_resets} new maps.`;
    $("co-sim-lift").hidden = !s.sim;
    $("co-sim-lift").textContent = l.lifted ? "Put down (simulation)" : "Pick up (simulation)";
    $("co-sim-lift").dataset.lifted = l.lifted ? "1" : "";
  }

  /* ---- lightweight 3D orientation view: plain canvas, no library ---- */
  const view = { az: -0.65, el: 0.42 };
  let pose3d = null;
  const BOX = (cx, cy, cz, dx, dy, dz, color) => {
    const v = [];
    for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) v.push([cx + sx * dx, cy + sy * dy, cz + sz * dz]);
    return [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]].map((f) => ({ pts: f.map((i) => v[i]), color }));
  };
  const ROBOT = [...BOX(0, 0, 0.42, 0.95, 0.68, 0.22, "--ink-3"), ...BOX(0.72, 0, 0.74, 0.16, 0.26, 0.11, "--cat-1"),
    ...BOX(0, 0.8, 0.28, 0.3, 0.09, 0.28, "--ink"), ...BOX(0, -0.8, 0.28, 0.3, 0.09, 0.28, "--ink")];
  function rotate(p, r, pi, y) {
    const [cr, sr, cp, sp, cy, sy] = [Math.cos(r), Math.sin(r), Math.cos(pi), Math.sin(pi), Math.cos(y), Math.sin(y)];
    const [a, b, c] = [p[0], cr * p[1] - sr * p[2], sr * p[1] + cr * p[2]];   // roll about x
    const [d, e, f] = [cp * a + sp * c, b, -sp * a + cp * c];                 // pitch about y
    return [cy * d - sy * e, sy * d + cy * e, f];                             // yaw about z
  }
  function project(p, w, h) {
    const [ca, sa, ce, se] = [Math.cos(view.az), Math.sin(view.az), Math.cos(view.el), Math.sin(view.el)];
    const x = ca * p[0] - sa * p[1], y = sa * p[0] + ca * p[1];
    const depth = ce * y - se * p[2], up = se * y + ce * p[2];
    const s = h * 1.75 / (depth + 4.2);
    return { x: w / 2 + x * s, y: h * 0.68 - up * s, depth };
  }
  function draw3d() {
    const cv = $("co-3d"), g = cv.getContext("2d"), css = getComputedStyle(document.documentElement);
    const color = (n) => css.getPropertyValue(n).trim(), box = cv.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1, w = Math.max(1, box.width), h = Math.max(1, box.height);
    if (cv.width !== Math.round(w * ratio) || cv.height !== Math.round(h * ratio)) {
      cv.width = Math.round(w * ratio); cv.height = Math.round(h * ratio);
    }
    g.setTransform(ratio, 0, 0, ratio, 0, 0);
    g.clearRect(0, 0, w, h);
    g.strokeStyle = color("--border"); g.lineWidth = 1; g.beginPath();
    for (let i = -2; i <= 2; i++) for (const [a, b] of [[[i, -2, 0], [i, 2, 0]], [[-2, i, 0], [2, i, 0]]]) {
      const p = project(a, w, h), q = project(b, w, h);
      g.moveTo(p.x, p.y); g.lineTo(q.x, q.y);
    }
    g.stroke();
    const o = pose3d && pose3d.imu;
    if (!o) { g.fillStyle = color("--ink-3"); g.font = "13px sans-serif"; g.textAlign = "center"; g.fillText("No IMU data", w / 2, 24); return; }
    const faces = ROBOT.map((f) => {
      const world = f.pts.map((p) => rotate(p, o.roll, o.pitch, o.yaw));
      const pts = world.map((p) => project(p, w, h));
      return { pts, color: f.color, depth: pts.reduce((s, p) => s + p.depth, 0) / pts.length };
    }).sort((a, b) => b.depth - a.depth);
    for (const f of faces) {
      const area = f.pts.reduce((s, p, i) => { const q = f.pts[(i + 1) % f.pts.length]; return s + p.x * q.y - q.x * p.y; }, 0);
      g.globalAlpha = area > 0 ? 1 : 0.8;
      g.fillStyle = color(f.color); g.strokeStyle = color("--card"); g.lineWidth = 1.5;
      g.beginPath(); f.pts.forEach((p, i) => (i ? g.lineTo(p.x, p.y) : g.moveTo(p.x, p.y))); g.closePath(); g.fill(); g.stroke();
    }
    g.globalAlpha = 1;
    const a = project(rotate([0.95, 0, 0.5], o.roll, o.pitch, o.yaw), w, h), b = project(rotate([1.75, 0, 0.5], o.roll, o.pitch, o.yaw), w, h);
    g.strokeStyle = color("--cat-2"); g.lineWidth = 3; g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke();
    g.fillStyle = color("--ink-3"); g.font = "12px sans-serif"; g.textAlign = "left";
    const deg = (v) => Math.round(v * 57.3) + 0;
    g.fillText(`roll ${deg(o.roll)}°  pitch ${deg(o.pitch)}°  orange = front`, 8, 16);
  }
  let dragging = null;
  $("co-3d").addEventListener("pointerdown", (e) => { dragging = [e.clientX, e.clientY]; e.target.setPointerCapture(e.pointerId); });
  $("co-3d").addEventListener("pointerup", () => { dragging = null; });
  $("co-3d").addEventListener("pointermove", (e) => {
    if (!dragging) return;
    view.az -= (e.clientX - dragging[0]) * 0.01;
    view.el = Math.max(0.05, Math.min(1.4, view.el + (e.clientY - dragging[1]) * 0.01));
    dragging = [e.clientX, e.clientY];
    draw3d();
  });
  async function poll3d() {
    if (!document.hidden) {
      try { pose3d = await (await fetch("/api/companion/pose")).json(); draw3d(); } catch { /* offline */ }
    }
    if (!STILL) setTimeout(poll3d, 100);
  }

  function renderEmotion(e) {
    $("co-emotion").textContent = `${e.emotion} · ${e.why}`;
    const box = $("co-emotions");
    if (!box.children.length) {
      for (const name of e.emotions) {
        const b = make("button", "btn-ghost", name);
        b.dataset.emotion = name;
        b.addEventListener("click", () => post("/api/companion/emotion", { emotion: name }));
        box.appendChild(b);
      }
    }
    for (const b of box.children) b.setAttribute("aria-pressed", String(b.dataset.emotion === e.emotion));
  }

  function renderControl(c) {
    const t = c.trim, f = c.face;
    $("co-mode").textContent = f && f.state === "tracking user" ? "tracking the user" : t.mode === "idle" ? (f ? f.state : "idle") : `${t.mode} · speed ×${t.scale}`;
    $("co-trim").checked = t.enabled;
    $("co-distance").checked = !!(f && f.keep_distance);
    $("co-distance").disabled = !f;
    plotRows = c.history;
    drawPlot();
  }

  function drawPlot(hoverX) {
    const cv = $("co-plot"), g = cv.getContext("2d"), css = getComputedStyle(document.documentElement);
    const w = cv.width, h = cv.height, pad = 6;
    g.clearRect(0, 0, w, h);
    const mode = plotRows.length ? plotRows[plotRows.length - 1][1] : null;
    const rows = plotRows.filter((r) => r[1] === mode);
    if (rows.length < 2) { $("co-readout").textContent = "No correction running"; return; }
    const ys = rows.flatMap((r) => [r[2], r[3]]);
    let lo = Math.min(...ys), hi = Math.max(...ys);
    if (hi - lo < 0.05) { hi += 0.05; lo -= 0.05; }
    const t0 = rows[0][0], t1 = rows[rows.length - 1][0] || 0.001;
    const X = (t) => pad + (w - 2 * pad) * (t - t0) / Math.max(0.001, t1 - t0);
    const Y = (v) => h - pad - (h - 2 * pad) * (v - lo) / (hi - lo);
    g.strokeStyle = css.getPropertyValue("--border"); g.lineWidth = 1;
    g.beginPath(); g.moveTo(pad, Y((lo + hi) / 2)); g.lineTo(w - pad, Y((lo + hi) / 2)); g.stroke();
    for (const [idx, color] of [[2, "--cat-2"], [3, "--cat-1"]]) {
      g.strokeStyle = css.getPropertyValue(color); g.lineWidth = 2; g.beginPath();
      rows.forEach((r, i) => (i && r[0] - rows[i - 1][0] <= 1 ? g.lineTo(X(r[0]), Y(r[idx])) : g.moveTo(X(r[0]), Y(r[idx]))));
      g.stroke();
    }
    let r = rows[rows.length - 1];
    if (hoverX != null) {
      r = rows.reduce((best, c) => (Math.abs(X(c[0]) - hoverX) < Math.abs(X(best[0]) - hoverX) ? c : best));
      g.strokeStyle = css.getPropertyValue("--ink-3"); g.lineWidth = 1;
      g.beginPath(); g.moveTo(X(r[0]), pad); g.lineTo(X(r[0]), h - pad); g.stroke();
    }
    $("co-readout").textContent = `${mode}: target ${r[2].toFixed(2)}, measured ${r[3].toFixed(2)}`;
  }
  $("co-plot").addEventListener("mousemove", (e) => {
    const box = e.target.getBoundingClientRect();
    drawPlot((e.clientX - box.left) * e.target.width / box.width);
  });
  $("co-plot").addEventListener("mouseleave", () => drawPlot());

  function gestureRow(name, rule, actions, sim) {
    const tr = make("tr");
    tr.dataset.gesture = name;
    tr.appendChild(make("td", null, label(name)));
    const sel = make("select");
    sel.setAttribute("aria-label", `Action for ${label(name)}`);
    for (const a of actions) {
      const o = make("option", null, label(a));
      o.value = a;
      sel.appendChild(o);
    }
    sel.value = rule.action; sel.dataset.f = "action";
    const num = (field, value, step) => {
      const i = make("input");
      i.type = "number"; i.min = "0"; i.step = step; i.value = value; i.dataset.f = field;
      i.setAttribute("aria-label", `${field} for ${label(name)}`);
      return i;
    };
    const on = make("input");
    on.type = "checkbox"; on.checked = rule.enabled; on.dataset.f = "enabled";
    on.setAttribute("aria-label", `Enable ${label(name)}`);
    for (const c of [sel, num("amount", rule.amount, "0.5"), num("hold_s", rule.hold_s, "0.1"), on]) {
      const td = make("td");
      td.appendChild(c);
      tr.appendChild(td);
    }
    const tryCell = make("td", "co-simcol");
    tryCell.hidden = !sim;
    const t = make("button", "btn-ghost", "Show");
    t.addEventListener("click", () => post("/api/sim/gesture", { gesture: name }));
    tryCell.appendChild(t);
    tr.appendChild(tryCell);
    tr.addEventListener("input", () => { gesturesDirty = true; });
    return tr;
  }

  function renderGestures(g, sim) {
    const last = g.last ? ` · last: ${label(g.last.gesture)} → ${label(g.last.action)}` : "";
    const engine = { mediapipe: "MediaPipe", simulated: "simulated", off: "unavailable", starting: "starting" }[g.backend];
    $("co-gesture-state").textContent = `${engine}${g.current !== "None" ? ` · sees ${label(g.current)}` : ""}${last}`;
    $("co-gesture-on").checked = g.enabled;
    document.querySelector("#co-gesture-card th.co-simcol").hidden = !sim;
    if (!gesturesDirty) {
      $("co-gesture-rows").replaceChildren(...g.gestures.map((n) => gestureRow(n, g.mapping[n], g.actions, sim)));
    }
  }

  async function poll() {
    if (!document.hidden) {
      try {
        state = await (await fetch("/api/companion")).json();
        renderOutputs(state.outputs);
        renderCalibration(state.calibration);
        renderBody(state);
        renderEmotion(state.emotion);
        $("co-dance-name").textContent = state.last_dance ? `Last dance: ${state.last_dance}` : "";
        renderControl(state.control);
        if (!document.activeElement || !document.activeElement.closest("#co-gesture-rows")) renderGestures(state.gestures, state.sim);
      } catch { /* offline */ }
    }
    if (!STILL) setTimeout(poll, 700);
  }

  function pollFace() {
    const img = $("co-face");
    if (!document.hidden) img.src = `/face.png?t=${Date.now()}`;
    if (!STILL) setTimeout(pollFace, 150);
  }

  /* ---- actions ---- */
  const guarded = (fn) => async (ev) => {
    try { await fn(ev); } catch (e) { alert(e.message); }
  };
  $("co-save").addEventListener("click", guarded(() => post("/api/companion/save")));
  $("co-dance").addEventListener("click", guarded(() => post("/api/assistant/commands", { commands: [{ action: "dance", amount: 0 }], source: "dashboard" })));
  addSaver("co-body-card", "orientation", canvasSaver("co-3d"));
  $("co-zero").addEventListener("click", guarded(() => post("/api/companion/zero-heading")));
  $("co-sim-lift").addEventListener("click", guarded((e) => post("/api/sim/lift", { lifted: !e.target.dataset.lifted })));
  $("co-trim").addEventListener("change", guarded((e) => post("/api/companion/control", { enabled: e.target.checked })));
  $("co-distance").addEventListener("change", guarded((e) => post("/api/companion/control", { keep_distance: e.target.checked })));
  $("co-gesture-on").addEventListener("change", guarded((e) => post("/api/companion/gestures", { enabled: e.target.checked })));
  $("co-cal").addEventListener("click", guarded(() => {
    const running = state && state.calibration.run && state.calibration.run.running;
    if (running) return post("/api/companion/calibrate", { action: "cancel" });
    if (!confirm("The robot will spin and drive short distances for about a minute. Is the desk around it clear?")) return null;
    return post("/api/companion/calibrate", { action: "start" });
  }));
  $("co-gesture-save").addEventListener("click", guarded(async () => {
    const mapping = {};
    for (const tr of $("co-gesture-rows").children) {
      const rule = { ...state.gestures.mapping[tr.dataset.gesture] };
      tr.querySelectorAll("[data-f]").forEach((c) => {
        rule[c.dataset.f] = c.type === "checkbox" ? c.checked : c.type === "number" ? Number(c.value) : c.value;
      });
      mapping[tr.dataset.gesture] = rule;
    }
    await post("/api/companion/gestures", { mapping });
    gesturesDirty = false;
  }));

  poll();
  pollFace();
  poll3d();
})();
