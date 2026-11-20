"use strict";
/* deskbot: camera card + geometric / semantic / confidence-heatmap maps.
   Data: GET /api/fusion (uint8 layers, base64, row 0 = bottom of the map), GET /api/vision. */

(() => {
  const FUSION_POLL_MS = 400;
  const VISION_POLL_MS = 500;
  const el = (id) => document.getElementById(id);

  let fusion = null;          // newest /api/fusion payload
  let layers = null;          // decoded Uint8Arrays
  let lut = null;             // colour tables for the current theme
  const labelSlot = new Map(); // object label -> categorical slot; colour follows the label, never its rank

  /* ---------------- colour ---------------- */

  const css = () => getComputedStyle(document.documentElement);
  const hex = (h) => {
    h = h.trim().replace("#", "");
    if (h.length === 3) h = [...h].map((c) => c + c).join("");
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  };
  // sRGB <-> OKLab, so the diverging ramp is perceptually even on both arms
  const toLin = (c) => ((c /= 255) <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const toSrgb = (c) => 255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
  function oklab([r, g, b]) {
    [r, g, b] = [r, g, b].map(toLin);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
  }
  function fromOklab([L, a, b]) {
    const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
    const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
    const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
    return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s].map((c) => Math.max(0, Math.min(255, Math.round(toSrgb(c)))));
  }
  const mixLab = (a, b, t) => fromOklab(a.map((v, i) => v + (b[i] - v) * t));
  const mixRgb = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

  function buildLut() {
    const c = css();
    const v = (n) => hex(c.getPropertyValue(n));
    const free = oklab(v("--heat-free")), mid = oklab(v("--heat-mid")), occ = oklab(v("--heat-occ"));
    const heat = new Uint8ClampedArray(256 * 3);
    const geo = new Uint8ClampedArray(256 * 3);
    const gFree = v("--map-free"), gUnk = v("--map-unknown"), gOcc = v("--ink");
    for (let i = 0; i < 256; i++) {
      const p = i / 255;
      const h = p < 0.5 ? mixLab(free, mid, p / 0.5) : mixLab(mid, occ, (p - 0.5) / 0.5);
      const g = p < 0.5 ? mixRgb(gFree, gUnk, p / 0.5) : mixRgb(gUnk, gOcc, (p - 0.5) / 0.5);
      heat.set(h, i * 3);
      geo.set(g, i * 3);
    }
    const cats = [1, 2, 3, 4, 5, 6, 7, 8].map((k) => c.getPropertyValue(`--cat-${k}`).trim());
    lut = {
      heat, geo, cats,
      unknown: gUnk, free: gFree, ink: c.getPropertyValue("--ink").trim(),
      edge: v("--warn"), move: c.getPropertyValue("--move").trim(), card: c.getPropertyValue("--card").trim(),
      grid: c.getPropertyValue("--border-strong").trim(), ink3: c.getPropertyValue("--ink-3").trim(),
    };
    const stops = [];
    for (let i = 0; i <= 10; i++) {
      const k = Math.round((i / 10) * 255) * 3;
      stops.push(`rgb(${heat[k]} ${heat[k + 1]} ${heat[k + 2]}) ${i * 10}%`);
    }
    el("heat-bar").style.background = `linear-gradient(90deg, ${stops.join(", ")})`;
  }

  function colorFor(label) {
    if (!labelSlot.has(label)) labelSlot.set(label, labelSlot.size % 8);
    return lut.cats[labelSlot.get(label)];
  }

  /* ---------------- decoding ---------------- */

  function b64(s) {
    const bin = atob(s);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  /* ---------------- drawing ---------------- */

  const off = document.createElement("canvas");

  // paint n x n cells (row 0 = bottom) through `pixel(i) -> [r,g,b,a]`, scaled up without smoothing
  function paintCells(ctx, n, pixel) {
    off.width = off.height = n;
    const octx = off.getContext("2d");
    const img = octx.createImageData(n, n);
    const d = img.data;
    for (let r = 0; r < n; r++) {
      const y = n - 1 - r;
      for (let c = 0; c < n; c++) {
        const px = pixel(r * n + c);
        const o = (y * n + c) * 4;
        d[o] = px[0]; d[o + 1] = px[1]; d[o + 2] = px[2]; d[o + 3] = px[3];
      }
    }
    octx.putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(off, 0, 0, ctx.canvas.width, ctx.canvas.height);
  }

  function geom(canvas) {
    const n = fusion.size, res = fusion.resolution, W = canvas.width;
    const s = W / n;
    return { n, res, s, px: (x) => (x / res + n / 2) * s, py: (y) => (n / 2 - y / res) * s };
  }

  function overlays(ctx, g, { robotColor, trail = true, fov = false }) {
    // 1 m grid
    const per = Math.round(1 / g.res);
    ctx.save();
    ctx.strokeStyle = lut.grid;
    ctx.globalAlpha = 0.55;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let k = (g.n / 2) % per; k <= g.n; k += per) {
      const p = Math.round(k * g.s) + 0.5;
      ctx.moveTo(p, 0); ctx.lineTo(p, g.n * g.s);
      ctx.moveTo(0, p); ctx.lineTo(g.n * g.s, p);
    }
    ctx.stroke();
    ctx.restore();

    const { x, y, theta } = fusion.pose;
    if (fov && fusion.vision) {
      const half = (fusion.camera.hfov * Math.PI) / 360;
      const r = (fusion.camera.range / g.res) * g.s;
      const cx = g.px(x + fusion.camera.x * Math.cos(theta)), cy = g.py(y + fusion.camera.x * Math.sin(theta));
      ctx.save();
      ctx.fillStyle = robotColor;
      ctx.globalAlpha = 0.08;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, r, -theta - half, -theta + half);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }
    if (trail && fusion.trail.length > 1) {
      ctx.save();
      ctx.strokeStyle = robotColor;
      ctx.globalAlpha = 0.6;
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.beginPath();
      fusion.trail.forEach(([tx, ty], i) => (i ? ctx.lineTo(g.px(tx), g.py(ty)) : ctx.moveTo(g.px(tx), g.py(ty))));
      ctx.stroke();
      ctx.restore();
    }
    ctx.save();
    ctx.translate(g.px(x), g.py(y));
    ctx.rotate(-theta);
    ctx.fillStyle = robotColor;
    ctx.strokeStyle = lut.card;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(11, 0); ctx.lineTo(-7, 7); ctx.lineTo(-3, 0); ctx.lineTo(-7, -7);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  function drawGeo() {
    const canvas = el("geo-canvas"), ctx = canvas.getContext("2d"), g = geom(canvas);
    const geo = layers.geo, edges = layers.edges, L = lut.geo;
    paintCells(ctx, g.n, (i) => (edges.has(i)
      ? [...lut.edge, 255]
      : [L[geo[i] * 3], L[geo[i] * 3 + 1], L[geo[i] * 3 + 2], 255]));
    overlays(ctx, g, { robotColor: lut.move });
  }

  function drawSem() {
    const canvas = el("sem-canvas"), ctx = canvas.getContext("2d"), g = geom(canvas);
    const { geo, sem_label: lab, sem_p: sp } = layers;
    const unk = lut.unknown, free = lut.free, ink = hex(lut.ink); // unknown/free are already [r,g,b]
    const cat = fusion.labels.map((name) => hex(colorFor(name)));
    // sonar says "something", the camera looked and could not name it (wall, glass, unknown object):
    // hatched in ink, so it reads as "obstacle, no label" rather than as another category colour
    const unrec = new Set(fusion.unrecognised || []);
    paintCells(ctx, g.n, (i) => {
      if (unrec.has(i)) {
        const c = i % g.n, r = Math.floor(i / g.n);
        return [...mixRgb(unk, ink, (c + r) % 2 ? 0.55 : 0.3), 255];
      }
      // context: faint geometry underneath
      const p = geo[i] / 255;
      let base = p < 0.4 ? mixRgb(unk, free, Math.min(1, (0.5 - p) * 3)) : p > 0.65 ? mixRgb(unk, ink, 0.22) : unk;
      if (lab[i]) {
        const a = Math.max(0, Math.min(1, (sp[i] / 255 - 0.5) * 2)) * 0.9; // existence confidence -> opacity
        base = mixRgb(base, cat[lab[i] - 1], a);
      }
      return [...base, 255];
    });
    overlays(ctx, g, { robotColor: lut.move, trail: false, fov: true });

    // direct labels + uncertainty ring (grows while an object goes unseen)
    ctx.save();
    ctx.font = '600 11px "Inter", system-ui, "Segoe UI", sans-serif'; // canvas fonts can't read CSS vars
    ctx.textAlign = "center";
    const placed = []; // label boxes already drawn, to avoid collisions
    const hits = (b) => placed.some((p) => b.x0 < p.x1 && b.x1 > p.x0 && b.y0 < p.y1 && b.y1 > p.y0);
    for (const o of fusion.objects) {
      if (o.p < 0.5) continue;
      const cx = g.px(o.x), cy = g.py(o.y);
      const r = ((o.radius + 2 * o.sigma) / g.res) * g.s;
      ctx.strokeStyle = colorFor(o.label);
      ctx.globalAlpha = 0.35 + 0.65 * o.confidence;
      ctx.setLineDash(o.age > 3 ? [3, 3] : []);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(cx, cy, Math.max(4, r), 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      const text = `${o.label} ${Math.round(o.p * 100)}%`;
      const w = ctx.measureText(text).width;
      const rr = Math.max(4, r);
      // above the ring, else below it, else skip the label (the legend + list still name it)
      const ty = [cy - rr - 5, cy + rr + 14].find((y) => !hits({ x0: cx - w / 2 - 2, x1: cx + w / 2 + 2, y0: y - 11, y1: y + 3 }));
      if (ty === undefined) continue;
      placed.push({ x0: cx - w / 2 - 2, x1: cx + w / 2 + 2, y0: ty - 11, y1: ty + 3 });
      ctx.lineWidth = 3;
      ctx.strokeStyle = lut.card;
      ctx.strokeText(text, cx, ty);
      ctx.fillStyle = lut.ink;
      ctx.fillText(text, cx, ty);
    }
    ctx.restore();
  }

  function drawHeat() {
    const canvas = el("heat-canvas"), ctx = canvas.getContext("2d"), g = geom(canvas);
    const heat = layers.heat, L = lut.heat;
    paintCells(ctx, g.n, (i) => [L[heat[i] * 3], L[heat[i] * 3 + 1], L[heat[i] * 3 + 2], 255]);
    // desk edges as an outline (they are a drop, not an object)
    ctx.save();
    ctx.strokeStyle = lut.ink;
    ctx.lineWidth = 1.5;
    for (const i of layers.edges) {
      const c = i % g.n, r = Math.floor(i / g.n);
      ctx.strokeRect(c * g.s + 1, (g.n - 1 - r) * g.s + 1, g.s - 2, g.s - 2);
    }
    ctx.restore();
    overlays(ctx, g, { robotColor: lut.ink, trail: false });
  }

  /* ---------------- text ---------------- */

  const fmtAge = (s) => (s < 1 ? "now" : s < 60 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} m ${Math.round(s % 60)} s`);

  function renderText() {
    const st = fusion.stats;
    el("geo-area").textContent = `${st.observed_m2.toFixed(2)} m²`;
    el("geo-age").textContent = st.median_age_s == null ? "—" : fmtAge(st.median_age_s);
    el("geo-hl").textContent = `${st.geo_half_life_s}/${st.sem_half_life_s} s`;
    el("geo-hl").title = "Evidence halves after this long unseen: geometry / objects";
    el("heat-conf-area").textContent = `${st.confident_m2.toFixed(2)} m²`;
    el("heat-mean").textContent = `${Math.round(st.mean_conf * 100)}%`;
    el("heat-rate").textContent = `${st.rate_hz.toFixed(1)} Hz`;

    const legend = el("sem-legend");
    legend.replaceChildren();
    const names = [...new Set(fusion.objects.map((o) => o.label))];
    if (!names.length) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = fusion.vision ? "No objects yet" : "Camera off: no semantic data";
      legend.appendChild(li);
    }
    for (const name of names) {
      const li = document.createElement("li");
      const sw = document.createElement("i");
      sw.className = "sw";
      sw.style.background = colorFor(name);
      li.append(sw, name);
      legend.appendChild(li);
    }
    if ((fusion.unrecognised || []).length) {
      const li = document.createElement("li");
      const sw = document.createElement("i");
      sw.className = "sw sw-unrec";
      li.title = "The sonar hears an obstacle here, the camera looked and recognised nothing: a wall, glass/acrylic, or an object YOLO can't name";
      li.append(sw, "unrecognised (wall / glass)");
      legend.appendChild(li);
    }

    const list = el("obj-list");
    list.replaceChildren();
    for (const o of fusion.objects) {
      const li = document.createElement("li");
      const dot = document.createElement("i");
      dot.style.background = colorFor(o.label);
      const name = document.createElement("span");
      name.className = "obj-name";
      name.textContent = o.label;
      const pos = document.createElement("small");
      pos.textContent = `${Math.round(o.x * 100)}, ${Math.round(o.y * 100)} cm ±${Math.round(o.sigma * 100)}`;
      name.appendChild(pos);
      const bar = document.createElement("span");
      bar.className = "obj-bar";
      bar.title = `P(still there) ${Math.round(o.p * 100)}% · ${o.hits} sightings, ${o.misses} misses · range from ${o.source}`;
      const fill = document.createElement("b");
      fill.style.width = `${Math.round(o.p * 100)}%`;
      bar.appendChild(fill);
      const age = document.createElement("span");
      age.className = "obj-age";
      age.textContent = fmtAge(o.age);
      li.append(dot, name, bar, age);
      list.appendChild(li);
    }
  }

  function render() {
    if (!fusion) return;
    if (!lut) buildLut();
    layers = {
      geo: b64(fusion.geo), heat: b64(fusion.heat), sem_label: b64(fusion.sem_label), sem_p: b64(fusion.sem_p),
      edges: new Set(fusion.edges),
    };
    drawGeo();
    drawSem();
    drawHeat();
    renderText();
  }

  /* ---------------- hover tooltip ---------------- */

  const tip = el("fmap-tip");
  function onMove(ev) {
    if (!fusion || !layers) return;
    const rect = ev.currentTarget.getBoundingClientRect();
    const n = fusion.size;
    const c = Math.floor(((ev.clientX - rect.left) / rect.width) * n);
    const row = Math.floor(((ev.clientY - rect.top) / rect.height) * n);
    if (c < 0 || c >= n || row < 0 || row >= n) return onLeave();
    const r = n - 1 - row, i = r * n + c;
    const x = (c - n / 2 + 0.5) * fusion.resolution, y = (r - n / 2 + 0.5) * fusion.resolution;
    const p = layers.heat[i] / 255, conf = Math.abs(2 * p - 1);
    const lab = layers.sem_label[i] ? fusion.labels[layers.sem_label[i] - 1] : null;
    const verdict = conf < 0.2 ? "unknown / stale" : p > 0.5 ? "object" : "empty";
    tip.innerHTML = "";
    const lines = [
      [`${Math.round(x * 100)}, ${Math.round(y * 100)} cm`, "tip-muted"],
      [`P(object) ${p.toFixed(2)} · ${verdict}`, ""],
      [`confidence ${Math.round(conf * 100)}%`, ""],
      [`geometry P ${(layers.geo[i] / 255).toFixed(2)}${layers.edges.has(i) ? " · desk edge" : ""}`, "tip-muted"],
    ];
    if (lab) lines.splice(1, 0, [lab, "b"]);
    for (const [text, cls] of lines) {
      const d = document.createElement(cls === "b" ? "b" : "div");
      if (cls && cls !== "b") d.className = cls;
      d.textContent = text;
      tip.appendChild(d);
      if (cls === "b") tip.appendChild(document.createElement("br"));
    }
    tip.hidden = false;
    const tx = Math.min(window.innerWidth - tip.offsetWidth - 8, ev.clientX + 14);
    const ty = Math.min(window.innerHeight - tip.offsetHeight - 8, ev.clientY + 14);
    tip.style.left = `${tx}px`;
    tip.style.top = `${ty}px`;
  }
  function onLeave() {
    tip.hidden = true;
  }
  for (const id of ["geo-canvas", "sem-canvas", "heat-canvas"]) {
    el(id).addEventListener("pointermove", onMove);
    el(id).addEventListener("pointerleave", onLeave);
  }

  /* ---------------- polling ---------------- */

  async function pollFusion() {
    try {
      const res = await fetch("/api/fusion");
      if (res.ok) {
        fusion = await res.json();
        render();
      }
    } catch { /* the main poll shows the connection state */ }
    setTimeout(pollFusion, FUSION_POLL_MS);
  }

  let camStarted = false;
  // ?still=1 -> refresh single JPEGs instead of an MJPEG stream (slow links, screenshots)
  const STILL = new URLSearchParams(location.search).has("still");
  function startCamera() {
    const img = el("cam-img");
    camStarted = true;
    if (STILL) {
      img.onload = () => { img.hidden = false; el("cam-off").hidden = true; setTimeout(() => (img.src = `/camera.jpg?t=${Date.now()}`), 500); };
      img.onerror = () => setTimeout(() => (img.src = `/camera.jpg?t=${Date.now()}`), 2000);
      img.src = "/camera.jpg";
      return;
    }
    img.onload = () => { img.hidden = false; el("cam-off").hidden = true; };
    img.onerror = () => {
      img.hidden = true;
      el("cam-off").hidden = false;
      el("cam-off").textContent = "Camera stream interrupted, retrying…";
      setTimeout(() => (img.src = `/camera.mjpg?t=${Date.now()}`), 2000);
    };
    img.src = "/camera.mjpg";
  }

  async function pollVision() {
    try {
      const v = await (await fetch("/api/vision")).json();
      if (!v.enabled) {
        el("cam-off").hidden = false;
        el("cam-off").textContent = v.starting ? `Camera ${v.reason}` : `Camera off${v.reason ? `: ${v.reason}` : ""}`;
        el("vision-meta").textContent = v.starting ? "starting" : "disabled";
      } else {
        if (!camStarted) startCamera();
        el("vision-meta").textContent = `${v.camera} · ${v.detector} · ${v.imgsz}px`;
        el("vis-fps").textContent = `${v.detect_fps.toFixed(1)} fps`;
        el("vis-infer").textContent = v.infer_ms == null ? "—" : `${Math.round(v.infer_ms)} ms`;
        el("vis-latency").textContent = v.latency_ms == null ? "—" : `${Math.round(v.latency_ms)} ms`;
        el("vis-latency").title = `capture → detections ready. Newest result is ${v.frame_age_ms ?? "?"} ms old.`;
        if (v.error) {
          el("cam-off").hidden = false;
          el("cam-off").textContent = v.error;
        }
        const list = el("det-list");
        list.replaceChildren();
        if (!v.detections.length) {
          const li = document.createElement("li");
          li.className = "muted";
          li.textContent = "Nothing detected";
          list.appendChild(li);
        }
        for (const d of v.detections) {
          const li = document.createElement("li");
          const dot = document.createElement("i");
          dot.style.background = lut ? colorFor(d.label) : "currentColor";
          li.append(dot, `${d.label} ${Math.round(d.score * 100)}%${d.track_id != null ? ` · #${d.track_id}` : ""}`);
          list.appendChild(li);
        }
      }
    } catch { /* offline */ }
    setTimeout(pollVision, VISION_POLL_MS);
  }

  /* ---------------- controls ---------------- */

  async function post(path) {
    const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.status);
  }
  el("fusion-reset").addEventListener("click", () => post("/api/fusion/reset").catch(() => {}));
  el("sim-shuffle").addEventListener("click", () => post("/api/sim/shuffle").catch(() => {}));

  // show the sim-only button once we know the mode (the main dashboard poll fills the mode pill)
  const modeTimer = setInterval(() => {
    const mode = el("mode-pill").dataset.mode;
    if (mode) {
      el("sim-shuffle").hidden = mode !== "simulation";
      clearInterval(modeTimer);
    }
  }, 300);

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    lut = null;
    render();
  });
  // the pro dashboard's theme switch (layout.js, 20 Nov 2026)
  window.addEventListener("deskbot-theme", () => {
    lut = null;
    render();
  });

  pollFusion();
  pollVision();
})();
