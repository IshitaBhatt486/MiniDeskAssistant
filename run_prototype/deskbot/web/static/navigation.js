/* Navigation card: live map, no-go zones (drag to draw, click to remove), home. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const canvas = $("nav-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const HALF = 1.2;                         // metres shown each side of the map origin
  let data = null, drawing = false, drag = null;

  const toPx = (x, y) => [(x + HALF) / (2 * HALF) * canvas.width, (HALF - y) / (2 * HALF) * canvas.height];
  const toWorld = (e) => {
    const r = canvas.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
    return [px * 2 * HALF - HALF, HALF - py * 2 * HALF];
  };

  function cells(list, size, color) {
    ctx.fillStyle = color;
    const s = size / (2 * HALF) * canvas.width;
    for (const [x, y] of list) { const [a, b] = toPx(x, y); ctx.fillRect(a - s / 2, b - s / 2, s, s); }
  }
  function poly(points) {
    ctx.beginPath();
    points.forEach(([x, y], i) => { const [a, b] = toPx(x, y); i ? ctx.lineTo(a, b) : ctx.moveTo(a, b); });
    ctx.closePath();
  }
  function inside(p, pts) {
    let hit = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const [xi, yi] = pts[i], [xj, yj] = pts[j];
      if ((yi > p[1]) !== (yj > p[1]) && p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi) hit = !hit;
    }
    return hit;
  }
  const rect = (a, b) => [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]];

  function draw() {
    ctx.fillStyle = "#20242b"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (!data) return;
    cells(data.corridor, 0.05, "rgba(70,170,120,.35)");
    cells(data.occupied, 0.05, "#c9ccd2");
    cells(data.edges, 0.05, "#e0b03c");
    cells(data.memory.avoid, 0.06, "rgba(235,140,50,.8)");
    for (const z of data.memory.zones) {
      poly(z.points); ctx.fillStyle = "rgba(220,60,60,.3)"; ctx.fill();
      ctx.strokeStyle = "#e05050"; ctx.lineWidth = 2; ctx.stroke();
    }
    if (drag) { poly(rect(drag[0], drag[1])); ctx.strokeStyle = "#ff8080"; ctx.setLineDash([5, 4]); ctx.stroke(); ctx.setLineDash([]); }
    ctx.font = "11px system-ui, sans-serif";
    for (const o of data.objects) {
      const [a, b] = toPx(o.x, o.y), r = Math.max(3, o.radius / (2 * HALF) * canvas.width);
      ctx.beginPath(); ctx.arc(a, b, r, 0, 7); ctx.fillStyle = "#5a8cff"; ctx.fill();
      ctx.fillStyle = "#fff"; ctx.fillText(o.label, a + r + 2, b + 3);
    }
    if (data.path && data.path.length > 1) {
      ctx.beginPath();
      data.path.forEach(([x, y], i) => { const [a, b] = toPx(x, y); i ? ctx.lineTo(a, b) : ctx.moveTo(a, b); });
      ctx.strokeStyle = "#6fd0ff"; ctx.lineWidth = 2; ctx.stroke();
    }
    if (data.memory.home) {
      const [a, b] = toPx(data.memory.home[0], data.memory.home[1]);
      ctx.fillStyle = "#7be07b"; ctx.beginPath(); ctx.moveTo(a, b - 9); ctx.lineTo(a + 8, b); ctx.lineTo(a + 5, b);
      ctx.lineTo(a + 5, b + 7); ctx.lineTo(a - 5, b + 7); ctx.lineTo(a - 5, b); ctx.lineTo(a - 8, b); ctx.closePath(); ctx.fill();
    }
    const [x, y, th] = data.pose, [a, b] = toPx(x, y);
    ctx.beginPath(); ctx.arc(a, b, 6, 0, 7); ctx.fillStyle = "#00dc78"; ctx.fill();
    ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(a + 13 * Math.cos(th), b - 13 * Math.sin(th)); ctx.strokeStyle = "#00dc78"; ctx.lineWidth = 2; ctx.stroke();
  }

  async function post(body, path = "/api/nav/memory") {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const out = await r.json().catch(() => ({}));
    $("nav-note").textContent = r.ok ? "" : (out.error || "That didn't work");
    poll(false);
  }

  async function poll(again = true) {
    try {
      data = await (await fetch("/api/nav/map")).json();
      const n = data.navigation, m = data.memory;
      $("nav-state").textContent = n.phase + (n.target ? ` · ${n.target}` : "") + (n.planner ? ` · ${n.planner}` : "")
        + (n.confidence != null ? ` · confidence ${Math.round(n.confidence * 100)}%` : "");
      $("nav-align").hidden = m.aligned;
      draw();
    } catch { /* the main poll shows the connection state */ }
    if (again) setTimeout(poll, 700);
  }

  canvas.addEventListener("pointerdown", (e) => {
    const p = toWorld(e);
    if (drawing) { drag = [p, p]; canvas.setPointerCapture(e.pointerId); return; }
    const z = data && data.memory.zones.find((zone) => inside(p, zone.points));
    if (z && confirm("Remove this no-go zone?")) post({ remove: z.id });
  });
  canvas.addEventListener("pointermove", (e) => { if (drag) { drag[1] = toWorld(e); draw(); } });
  canvas.addEventListener("pointerup", () => {
    if (!drag) return;
    const pts = rect(drag[0], drag[1]); drag = null;
    post({ add: pts });
  });
  $("nav-draw").addEventListener("click", () => {
    drawing = !drawing;
    $("nav-draw").textContent = drawing ? "Done drawing" : "Draw no-go zone";
    canvas.style.cursor = drawing ? "crosshair" : "default";
  });
  $("nav-clear").addEventListener("click", () => { if (confirm("Remove all no-go zones?")) post({ clear_zones: true }); });
  $("nav-home-set").addEventListener("click", () => post({ home: true }));
  $("nav-home-go").addEventListener("click", () => post({ commands: [{ action: "navigate", from_object: "", to_object: "home" }] }, "/api/assistant/commands"));
  $("nav-accept").addEventListener("click", () => post({ accept: true }));
  poll();
})();
