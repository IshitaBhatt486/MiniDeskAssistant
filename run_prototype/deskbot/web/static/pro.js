/* Pro cards (20 Nov 2026): voice studio, touch & headpats, motion sense, AI brain, APIs in use, accounts.
   Polls /api/pro every second (live touch/IMU), /api/pro/apis every 5 s and /api/pro/accounts every 20 s.
   Hidden cards (layout.js) aren't polled. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const visible = (id) => { const el = $(id); return el && !el.classList.contains("lm-hidden"); };

  async function api(path, body) {
    const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const r = await fetch(path, opt);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }
  const ago = (t) => {
    if (!t) return "—";
    const s = Math.max(0, Date.now() / 1000 - t);
    return s < 60 ? `${Math.round(s)} s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
  };
  const flash = (el, text, ok = true) => {
    el.textContent = text;
    el.classList.toggle("is-ok", ok);
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.textContent = ""; }, 3500);
  };

  // ---------------- voice studio ----------------
  const pv = { loaded: false, profiles: [], editing: false };
  const sliders = {
    "pv-pitch": ["voice_pitch", (v) => `${v > 0 ? "+" : ""}${v} st`],
    "pv-speed": ["voice_speed", (v) => `${(+v).toFixed(2)}×`],
    "pv-volume": ["volume", (v) => `${Math.round(v * 100)}%`],
    "pv-factor": ["chipmunk_factor", (v) => (+v).toFixed(1)],
  };

  async function loadVoice() {
    const s = await api("/api/assistant").then((a) => a.settings);
    const fill = (sel, map, val) => {
      sel.innerHTML = Object.entries(map).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("");
      sel.value = val;
    };
    fill($("pv-style"), s.voice_styles, s.voice_style);
    fill($("pv-gender"), s.voice_genders, s.voice_gender);
    for (const [id, [key, fmt]] of Object.entries(sliders)) {
      $(id).value = s[key];
      $(id + "-v").textContent = fmt(s[key]);
    }
    pv.loaded = true;
    api("/api/pro/voices").then((v) => {
      $("pv-engine").textContent = v.engine || "no speech engine";
      $("pv-name").innerHTML = '<option value="">Default</option>' +
        (v.voices || []).map((x) => `<option value="${esc(x.id)}">${esc(x.label)}</option>`).join("");
      $("pv-name").value = s.voice_name || "";
    }).catch(() => {});
  }

  let saveTimer = null;
  function saveVoice(changes) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      try {
        await api("/api/assistant/settings", changes);
        flash($("pv-msg"), "Saved");
      } catch (e) { flash($("pv-msg"), e.message, false); }
    }, 250);
  }
  for (const [id, [key, fmt]] of Object.entries(sliders)) {
    $(id).addEventListener("input", (e) => { $(id + "-v").textContent = fmt(e.target.value); });
    $(id).addEventListener("change", (e) => saveVoice({ [key]: +e.target.value }));
  }
  $("pv-style").addEventListener("change", (e) => saveVoice({ voice_style: e.target.value }));
  $("pv-gender").addEventListener("change", (e) => saveVoice({ voice_gender: e.target.value }));
  $("pv-name").addEventListener("change", (e) => saveVoice({ voice_name: e.target.value }));
  $("pv-test").addEventListener("click", async () => {
    try {
      await api("/api/assistant/say", { text: $("pv-text").value || "Hello!" });
      flash($("pv-msg"), "Speaking…");
    } catch (e) { flash($("pv-msg"), e.message, false); }
  });

  function renderProfiles(p) {
    pv.profiles = p.profiles;
    const sel = $("pv-profile");
    if (document.activeElement !== sel && !pv.dirty) {   // don't undo a choice that hasn't been applied yet
      sel.innerHTML = (p.active ? "" : '<option value="">Custom (unsaved)</option>') +
        p.profiles.map((x) => `<option value="${esc(x.name)}">${esc(x.name)}${x.builtin ? "" : " ★"}</option>`).join("");
      sel.value = p.active || "";
    }
    const cur = p.profiles.find((x) => x.name === sel.value);
    $("pv-profile-text").textContent = cur ? cur.personality : "";
    $("pv-delete").hidden = !cur || cur.builtin;
  }
  $("pv-profile").addEventListener("change", () => {
    pv.dirty = true;
    const cur = pv.profiles.find((x) => x.name === $("pv-profile").value);
    $("pv-profile-text").textContent = cur ? cur.personality : "";
  });
  $("pv-apply").addEventListener("click", async () => {
    try {
      pv.dirty = false;
      renderProfiles(await api("/api/pro/profiles", { apply: $("pv-profile").value }));
      await loadVoice();
      flash($("pv-msg"), `Now: ${$("pv-profile").value}`);
    } catch (e) { flash($("pv-msg"), e.message, false); }
  });
  $("pv-save").addEventListener("click", async () => {
    const name = prompt("Save the current personality and voice as profile:", $("pv-profile").value || "My profile");
    if (!name) return;
    try { renderProfiles(await api("/api/pro/profiles", { save: name })); flash($("pv-msg"), `Saved ${name}`); }
    catch (e) { flash($("pv-msg"), e.message, false); }
  });
  $("pv-delete").addEventListener("click", async () => {
    const name = $("pv-profile").value;
    if (!name || !confirm(`Delete the profile "${name}"?`)) return;
    try { renderProfiles(await api("/api/pro/profiles", { delete: name })); flash($("pv-msg"), "Deleted"); }
    catch (e) { flash($("pv-msg"), e.message, false); }
  });

  // ---------------- touch ----------------
  const NAMES = { touch: "touch", pat: "headpat", hold: "long pat", pats: "pat streak!", stroke: "stroke",
    knock: "knock", double_knock: "double knock", bump: "bump", shake: "shake", tipped: "tipped over",
    righted: "stood up", drop: "dropped" };
  const eventList = (ul, events, empty, withPad) => {
    const rows = (events || []).filter((e) => e.kind !== "touch").slice(0, 6);
    ul.innerHTML = rows.length ? rows.map((e) =>
      `<li><b>${esc(NAMES[e.kind] || e.kind)}</b>${withPad && e.pad ? ` <span class="muted">${esc(e.pad)}</span>` : ""}` +
      `<span class="mono muted">${esc(ago(e.t))}</span></li>`).join("") : `<li class="muted">${esc(empty)}</li>`;
  };
  document.querySelectorAll(".pt-pad").forEach((b) => {
    let down = 0;
    const start = (e) => { e.preventDefault(); down = performance.now(); b.classList.add("is-down"); };
    const end = async () => {
      if (!down) return;
      const hold = (performance.now() - down) / 1000;
      down = 0;
      b.classList.remove("is-down");
      try { await api("/api/pro/touch/test", { pad: b.dataset.pad, hold_s: Math.max(0.12, hold) }); } catch (e) { /* shown in status */ }
    };
    b.addEventListener("pointerdown", start);
    b.addEventListener("pointerup", end);
    b.addEventListener("pointerleave", end);
  });

  // ---------------- motion ----------------
  $("pm-test").addEventListener("click", async (e) => {
    const ev = e.target.closest("button")?.dataset.ev;
    if (!ev) return;
    try { await api("/api/pro/motion/test", { event: ev }); } catch (err) { /* ignore */ }
  });

  // ---------------- pro settings (data-pro="section.key") ----------------
  const proInputs = [...document.querySelectorAll("[data-pro]")];
  function fillSettings(s) {
    for (const el of proInputs) {
      if (el === document.activeElement) continue;
      const [sec, key] = el.dataset.pro.split(".");
      const v = s[sec]?.[key];
      if (el.type === "checkbox") el.checked = !!v; else el.value = v ?? "";
    }
  }
  proInputs.forEach((el) => el.addEventListener("change", async () => {
    const [sec, key] = el.dataset.pro.split(".");
    const v = el.type === "checkbox" ? el.checked : el.type === "number" ? +el.value : el.value;
    try { fillSettings(await api("/api/pro/settings", { [sec]: { [key]: v } })); }
    catch (e) { alert(e.message); }
  }));

  // ---------------- AI brain ----------------
  function renderBrain(st, brain) {
    const order = brain.order || [];
    const label = { groq: "Groq", claude: "Claude", local: "Local AI (Ollama)", offline: "Offline rules" };
    $("pb-order").innerHTML = order.map((n, i) => `<li class="${i === 0 ? "is-now" : ""}">${esc(label[n] || n)}` +
      `${n === "groq" ? ` <span class="mono muted">${esc(st.groq.model)}</span>` : ""}</li>`).join("");
    $("pb-now").textContent = label[order[0]] || "—";
    $("pb-now").className = "tag " + (order[0] === "offline" ? "is-warn" : "is-ok");
    const g = st.groq;
    $("pb-why").textContent = g.available ? (g.last_error ? `Last Groq error: ${g.last_error}` : "")
      : `Groq is not used: ${g.why}.`;
  }

  // ---------------- APIs + accounts ----------------
  const STATE = { active: ["is-ok", "in use"], fallback: ["", "fallback"], standby: ["", "ready"], off: ["is-off", "off"] };
  async function pollApis() {
    if (!visible("pro-apis-card") && !visible("pro-brain-card")) return;
    try {
      const d = await api("/api/pro/apis");
      let group = "";
      $("pa-rows").innerHTML = d.rows.map((r) => {
        const head = r.group !== group ? `<tr class="pro-group"><td colspan="5">${esc((group = r.group))}</td></tr>` : "";
        const [cls, text] = STATE[r.state] || ["", r.state];
        return head + `<tr><td>${esc(r.name)}</td><td><span class="tag ${cls}">${esc(text)}</span></td>` +
          `<td class="muted">${esc(r.detail || "")}</td><td class="num mono">${r.count ?? ""}</td><td class="mono muted">${esc(r.last ? ago(r.last) : "")}</td></tr>`;
      }).join("");
      $("pa-updated").textContent = new Date().toLocaleTimeString();
    } catch (e) { /* offline: keep the last table */ }
  }
  async function pollAccounts() {
    if (!visible("pro-accounts-card")) return;
    try {
      const d = await api("/api/pro/accounts");
      $("pc-linked").innerHTML = d.linked.length ? d.linked.map((a) =>
        `<li><b>${esc(a.provider)}</b> <span class="tag ${a.connected ? "is-ok" : a.configured ? "" : "is-off"}">` +
        `${a.connected ? "connected" : a.configured ? "not signed in" : "not set up"}</span>` +
        `${a.account ? ` <span class="muted">${esc(a.account)}</span>` : ""}` +
        `${a.scopes && a.scopes.length ? `<div class="mono muted pro-scopes">${esc(a.scopes.join(" · "))}</div>` : ""}` +
        `${a.error ? `<div class="pro-err">${esc(a.error)}</div>` : ""}</li>`).join("") : '<li class="muted">None.</li>';
      $("pc-keys").innerHTML = d.keys.map((k) => `<tr><td>${esc(k.service)}<div class="mono muted">${esc(k.env)}</div></td>` +
        `<td class="muted">${esc(k.used_for)}</td><td>${k.set ? `<span class="mono">${esc(k.shown)}</span>` : '<span class="tag is-off">not set</span>'}</td></tr>`).join("");
      $("pc-how").textContent = d.how_to_change;
    } catch (e) { /* keep */ }
  }

  // ---------------- main poll ----------------
  async function poll() {
    try {
      const [st, as] = await Promise.all([api("/api/pro"), api("/api/assistant")]);
      fillSettings(st.settings);
      renderProfiles(st.profiles);
      renderBrain(st, as.brain);
      const t = st.touch;
      $("pt-backend").textContent = t.backend === "gpio" ? "GPIO" : t.error ? "no GPIO" : "simulated";
      $("pt-backend").className = "tag " + (t.backend === "gpio" ? "is-ok" : "");
      $("pt-today").textContent = t.today.pats;
      const last = (t.events || []).find((e) => e.kind !== "touch");
      $("pt-last").textContent = last ? NAMES[last.kind] || last.kind : "—";
      document.querySelectorAll(".pt-pad").forEach((b) => b.classList.toggle("is-touched", t.pressed.includes(b.dataset.pad)));
      eventList($("pt-events"), t.events, "No touches yet.", true);
      const m = st.motion, l = m.latest;
      const deg = (r) => (r == null ? "—" : String(Math.round(r * 180 / Math.PI) + 0));   // + 0 turns -0 into 0
      $("pm-roll").textContent = l ? deg(l.roll) : "—";
      $("pm-pitch").textContent = l ? deg(l.pitch) : "—";
      $("pm-tilt").textContent = l ? deg(l.tilt) : "—";
      $("pm-gyro").textContent = l ? l.gyro_norm.toFixed(2) : "—";
      $("pm-state").textContent = m.tipped ? "tipped over" : l ? "live" : "no IMU data";
      $("pm-state").className = "tag " + (m.tipped ? "is-warn" : l ? "is-ok" : "");
      eventList($("pm-events"), m.events, "Nothing yet.", false);
    } catch (e) { /* the base dashboard shows the connection state */ }
  }

  loadVoice().catch(() => {});
  poll(); setInterval(poll, 1000);
  pollApis(); setInterval(pollApis, 5000);
  pollAccounts(); setInterval(pollAccounts, 20000);
  window.addEventListener("deskbot-card-shown", () => { pollApis(); pollAccounts(); });
})();
