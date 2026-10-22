/* Processes card + face-the-user switch (multi-process runtime only). */
(() => {
  "use strict";
  const el = (id) => document.getElementById(id);
  const ms = (v) => (v == null ? "—" : v < 1 ? `${v.toFixed(2)} ms` : `${Math.round(v)} ms`);
  const prio = (p) => (p.policy !== "other" ? `${p.policy.toUpperCase()} ${p.priority}` : p.nice == null ? "default" : `nice ${p.nice}`);
  let toggling = false;

  function row(p) {
    const tr = document.createElement("tr");
    const cells = [
      p.role + (p.alive === false ? " ✕" : ""),
      p.core == null ? "any" : String(p.core),
      prio(p),
      p.loop_hz == null ? "—" : `${p.loop_hz.toFixed(0)} Hz`,
      p.cpu_pct == null ? "—" : `${p.cpu_pct.toFixed(0)} %`,
    ];
    for (const c of cells) {
      const td = document.createElement("td");
      td.textContent = c;
      tr.appendChild(td);
    }
    if (p.alive === false) tr.className = "proc-dead";
    tr.title = `pid ${p.pid} · worst loop iteration ${ms(p.loop_max_ms)}`;
    return tr;
  }

  async function poll() {
    try {
      const r = await (await fetch("/api/runtime")).json();
      el("proc-rows").replaceChildren(...r.processes.map(row));
      const m = r.motor;
      el("rt-cmd").textContent = ms(m.cmd_latency_p50);
      el("rt-cmd").title = `p95 ${ms(m.cmd_latency_p95)} · max ${ms(m.cmd_latency_max)}`;
      el("rt-age").textContent = ms(m.sensor_age_p50);
      el("rt-age").title = `p95 ${ms(m.sensor_age_p95)} · max ${ms(m.sensor_age_max)}: how old the newest sensor sample was when a safety check ran`;
      el("rt-pre").textContent = m.preempted == null ? "—" : String(m.preempted);
      el("rt-pre").title = "Moves replaced by a newer command before they finished";
      const b = r.behaviour;
      if (!toggling) el("face-user").checked = !!b.enabled;
      el("face-user").disabled = !b.available;
      el("face-state").textContent = b.state + (b.bearing_deg != null && b.state.includes("user") ? ` · ${b.bearing_deg}°` : "");
    } catch { /* offline */ }
    setTimeout(poll, 1000);
  }

  el("face-user").addEventListener("change", async (ev) => {
    toggling = true;
    try {
      await fetch("/api/behaviour", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ face_user: ev.target.checked }) });
    } finally { toggling = false; }
  });
  el("sim-move-user").addEventListener("click", () =>
    fetch("/api/sim/shuffle", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ label: "User" }) }));

  const modeTimer = setInterval(() => {
    const mode = el("mode-pill") && el("mode-pill").dataset.mode;
    if (mode) {
      el("sim-move-user").hidden = mode !== "simulation";
      clearInterval(modeTimer);
    }
  }, 300);
  poll();
})();
