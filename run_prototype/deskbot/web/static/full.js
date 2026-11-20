/* Full cards. The admin PIN is asked once when needed and kept only in this page's memory. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const STILL = new URLSearchParams(location.search).has("still");
  const make = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const post = async (url, body = {}) => {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(data.error || r.statusText); e.status = r.status; throw e; }
    return data;
  };
  let pin = null, S = null, formsFilled = false, editing = null;
  const shown = {};   // guard photos opened with the PIN (this page only)
  async function withPin(url, body) {
    if (!pin) { pin = prompt("Admin PIN (ADMIN_PIN in secrets.env)"); if (!pin) throw new Error("PIN needed"); }
    try { return await post(url, { ...body, pin }); } catch (e) { if (e.status === 403) pin = null; throw e; }
  }
  const act = (p) => p.then(poll).catch((e) => alert(e.message));
  const ago = (t) => { const s = Date.now() / 1000 - t; return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`; };
  const PROTECTED = new Set(["guard", "owner_recognition", "telegram"]);

  /* ---- features ---- */
  function renderFeatures(f) {
    $("fu-local-only").checked = f.local_only;
    const groups = {};
    for (const x of f.features) (groups[x.group] ||= []).push(x);
    $("fu-features").replaceChildren(...Object.entries(groups).map(([g, items]) => {
      const box = make("div", "fu-group");
      box.appendChild(make("h3", null, g));
      for (const x of items) {
        const row = make("label", "fu-feature" + (x.switched_on && !x.on ? " blocked" : ""));
        const cb = make("input"); cb.type = "checkbox"; cb.checked = x.switched_on;
        cb.addEventListener("change", () => {
          const body = { key: x.key, on: cb.checked };
          act(PROTECTED.has(x.key) ? withPin("/api/full/features", body) : post("/api/full/features", body));
        });
        row.append(cb, make("b", null, x.title + (x.internet ? " 🌐" : "")),
          make("span", null, x.what + (x.examples[0] && !x.examples[0].startsWith("(") ? ` Say: “${x.examples[0]}”` : "") +
            (x.switched_on && !x.on ? " (off: local-only mode)" : "")));
        box.appendChild(row);
      }
      return box;
    }));
  }
  $("fu-local-only").addEventListener("change", (ev) => act(withPin("/api/full/features", { local_only: ev.target.checked })));

  /* ---- wake word ---- */
  function renderWake(w) {
    $("fu-wake-phrase").textContent = `“${w.phrase.replace(/\b\w/g, (c) => c.toUpperCase())}”`;
    $("fu-wake-state").textContent = !w.enabled ? "off" : w.error ? "not listening" : w.mic ? `listening (${w.backend})` : "starting…";
    $("fu-wake-note").textContent = w.error ? `Not listening: ${w.error}` :
      `${w.count} times${w.last ? `, last ${ago(w.last.t)}${w.last.said ? `: “${w.last.said}”` : ""}` : ""}. Recognised on the robot; nothing is streamed.`;
  }
  $("fu-wake-form").addEventListener("submit", (ev) => { ev.preventDefault(); act(post("/api/full/wake", { text: $("fu-wake-text").value })); $("fu-wake-text").value = ""; });

  /* ---- briefings ---- */
  function renderBrief(b) {
    $("fu-brief-state").textContent = b.settings.auto ? `auto ${b.settings.morning_time} / ${b.settings.evening_time}` : "manual";
    if (b.last) $("fu-brief-text").textContent = b.last.text;
  }
  document.querySelectorAll("[data-brief]").forEach((btn) => btn.addEventListener("click", () => act(post("/api/full/briefing", { kind: btn.dataset.brief }))));

  /* ---- routines ---- */
  function renderRoutines(r) {
    $("fu-rt-folder").textContent = r.folder;
    $("fu-rt-state").textContent = r.running ? `running ${r.running}` : `${r.routines.length} saved`;
    $("fu-rt-steps").textContent = `Step types: ${r.step_types.join(", ")}. Events: arrive, leave, focus_end, time:HH:MM.`;
    const rows = r.routines.map((x) => {
      const li = make("li", "fu-rt-row");
      const cb = make("input"); cb.type = "checkbox"; cb.checked = x.enabled; cb.setAttribute("aria-label", `Enable ${x.name}`);
      cb.addEventListener("change", () => act(post("/api/full/routines", { enable: x.key, on: cb.checked })));
      const info = make("div");
      info.appendChild(make("span", "bd-title", x.name));
      info.appendChild(make("span", "bd-due", `say “${x.triggers.join("”, “") || "—"}”${x.events.length ? " · on " + x.events.join(", ") : ""} · ${x.steps.length} steps`));
      const btns = make("div", "fu-actions");
      for (const [label, fn] of [["Run", () => act(post("/api/full/routines", { run: x.key }))],
        ["Edit", () => openEditor(x.key, x)],
        ["Delete", () => confirm(`Delete ${x.name}?`) && act(post("/api/full/routines", { delete: x.key }))]]) {
        const b = make("button", "btn-ghost", label); b.type = "button"; b.addEventListener("click", fn); btns.appendChild(b);
      }
      li.append(cb, info, btns);
      return li;
    });
    for (const [k, err] of Object.entries(r.errors)) rows.push(make("li", "fu-err", `${k}.json: ${err}`));
    if (r.last_run) rows.push(make("li", "bd-empty", `Last run: ${r.last_run.name} (${r.last_run.why}) — ` + r.last_run.steps.map((s) => `${s.do}: ${s.result}`).join(" · ")));
    $("fu-routines").replaceChildren(...rows);
  }
  function openEditor(key, data) {
    editing = key;
    const { key: _k, ...clean } = data || {};
    $("fu-rt-editor-title").textContent = key ? `Edit ${data.name}` : "New routine";
    $("fu-rt-form").elements.json.value = JSON.stringify(Object.keys(clean).length ? clean :
      { name: "My routine", triggers: ["my routine"], events: [], enabled: true, description: "", steps: [{ do: "say", text: "Hello!" }] }, null, 2);
    $("fu-rt-editor").open = true;
    $("fu-rt-msg").textContent = "";
  }
  $("fu-rt-new").addEventListener("click", () => openEditor(null, null));
  $("fu-rt-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const data = JSON.parse(ev.target.elements.json.value);
      await post("/api/full/routines", { save: data, key: editing });
      $("fu-rt-msg").textContent = "Saved."; poll();
    } catch (e) { $("fu-rt-msg").textContent = e.message; }
  });

  /* ---- smart home ---- */
  function renderHome(h) {
    $("fu-home-state").textContent = h.home_assistant ? "Home Assistant ✓" : `${h.devices.length} devices`;
    $("fu-devices").replaceChildren(...(h.devices.length ? h.devices.map((d) => {
      const li = make("li", "fu-rt-row");
      li.appendChild(make("span", "bd-badge", d.type));
      li.appendChild(make("span", "bd-title", d.name + (d.aliases.length ? ` (${d.aliases.join(", ")})` : "")));
      const btns = make("div", "fu-actions");
      for (const a of ["on", "off"]) {
        const b = make("button", "btn-ghost", a); b.type = "button";
        b.addEventListener("click", () => act(post("/api/full/smarthome", { control: { device: d.name, action: a } })));
        btns.appendChild(b);
      }
      const x = make("button", "bd-x", "×"); x.type = "button"; x.setAttribute("aria-label", `Remove ${d.name}`);
      x.addEventListener("click", () => confirm(`Remove ${d.name}?`) && act(post("/api/full/smarthome", { remove: d.name })));
      btns.appendChild(x);
      li.appendChild(btns);
      return li;
    }) : [make("li", "bd-empty", "No devices yet. Add one below, then say “turn on the desk lamp”.")]));
  }
  $("fu-home-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = Object.fromEntries(new FormData(ev.target));
    const dev = { name: f.name, type: f.type, ...(f.type === "homeassistant" ? { entity_id: f.entity_id } : { host: f.host }) };
    act(post("/api/full/smarthome", { add: dev }).then(() => ev.target.reset()));
  });
  $("fu-discover").addEventListener("click", async () => {
    try {
      const r = await post("/api/full/smarthome", { discover: true });
      $("fu-found").replaceChildren(...r.found.map((d) => { const li = make("li"); li.append(make("b", null, d.name), make("span", null, `${d.entity_id} · ${d.state}`)); return li; }));
    } catch (e) { alert(e.message); }
  });

  /* ---- reader ---- */
  function renderReader(r) {
    $("fu-read-state").textContent = r.busy ? "reading…" : r.ocr_order[0] ? `first: ${r.ocr_order[0]}` : "—";
    const have = [r.ollama_vision ? "local vision model ✓" : "local vision model ✗", r.tesseract ? "Tesseract ✓" : "Tesseract ✗"];
    $("fu-read-note").textContent = (r.last ? `Last: ${r.last.chars} characters with ${r.last.backend} in ${(r.last.ms / 1000).toFixed(0)} s. ` : "") + have.join(" · ");
    $("fu-reads").replaceChildren(...r.files.slice(0, 10).map((f) => {
      const li = make("li"); const a = make("a", null, f.name); a.href = `/api/full/reads/${encodeURIComponent(f.name)}`; a.target = "_blank";
      li.append(a, make("span", "mono", `${f.kb} kB`)); return li;
    }));
  }
  $("fu-read-file").addEventListener("change", async (ev) => {
    const file = ev.target.files[0]; if (!file) return;
    const extra = $("fu-read-extra").value;
    try {
      const r = await fetch(`/api/full/read${extra ? `?extra=${extra}` : ""}`, { method: "POST", headers: { "Content-Type": file.type || "image/jpeg" }, body: file });
      const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); poll();
    } catch (e) { alert(e.message); }
    ev.target.value = "";
  });
  $("fu-read-camera").addEventListener("click", () => act(post("/api/full/read", { camera: true, extra: $("fu-read-extra").value || null })));

  /* ---- hydration ---- */
  function renderWater(h) {
    $("fu-water-count").textContent = `${h.today} / ${h.goal}`;
    $("fu-water-note").textContent = h.minutes_since == null ? "drinks today" : `drinks today · last ${h.minutes_since} min ago`;
    const max = Math.max(h.goal, ...h.week.map((d) => d.drinks));
    $("fu-water-week").replaceChildren(...h.week.map((d) => {
      const col = make("div"); const bar = make("i"); bar.style.height = `${(100 * d.drinks) / max}%`; bar.title = `${d.date}: ${d.drinks}`;
      col.append(bar, make("span", null, new Date(d.date + "T12:00").toLocaleDateString([], { weekday: "narrow" }))); return col;
    }));
  }
  $("fu-drink").addEventListener("click", () => act(post("/api/full/hydration", { drink: true })));

  /* ---- games ---- */
  function renderRps(g) {
    $("fu-rps-state").textContent = g.state;
    $("fu-rps-score").textContent = `You ${g.score.you} · Pip ${g.score.robot}${g.score.draws ? ` · ${g.score.draws} draws` : ""}`;
    const last = g.rounds[g.rounds.length - 1];
    $("fu-rps-note").textContent = last ? `Last round: you ${last.you}, Pip ${last.robot} → ${last.winner}` : "Fist = rock, flat hand = paper, peace sign = scissors. Or say it.";
  }
  $("fu-rps-start").addEventListener("click", () => act(post("/api/full/rps", { start: true })));
  $("fu-rps-stop").addEventListener("click", () => act(post("/api/full/rps", { stop: true })));
  document.querySelectorAll("[data-rps]").forEach((b) => b.addEventListener("click", () => act(post("/api/full/rps", { move: b.dataset.rps }))));

  /* ---- people ---- */
  function renderPeople(p) {
    $("fu-people-state").textContent = p.enrolling ? `learning… ${p.enrolling.samples}` : p.ready ? `${p.people.length} known` : (p.error ? "not ready" : "—");
    const here = new Set(p.here.filter((h) => h.name).map((h) => h.name));
    $("fu-people").replaceChildren(...(p.people.length ? p.people.map((x) => {
      const li = make("li", "fu-rt-row");
      li.appendChild(make("span", "bd-badge" + (here.has(x.name) ? " spoken" : ""), here.has(x.name) ? "here" : x.role));
      li.appendChild(make("span", "bd-title", `${x.name} (${x.role}, ${x.samples} samples)`));
      const b = make("button", "btn-ghost", "Forget"); b.type = "button";
      b.addEventListener("click", () => confirm(`Forget ${x.name}'s face?`) && act(withPin("/api/full/faces", { forget: x.name })));
      li.appendChild(b); return li;
    }) : [make("li", "bd-empty", p.error ? `Face recognition: ${p.error}` : "Nobody yet. Say “learn my face”, or use the form.")]));
  }
  $("fu-learn").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = Object.fromEntries(new FormData(ev.target));
    try {
      if (f.owner_name !== S.settings.owner.name) await post("/api/full/settings", { owner: { name: f.owner_name } });
      if (f.name) await withPin("/api/full/faces", { learn: { name: f.name, role: f.role } });
      poll();
    } catch (e) { alert(e.message); }
  });

  /* ---- guard ---- */
  function renderGuard(g) {
    $("fu-guard-state").textContent = g.state + (g.armed_by ? ` (${g.armed_by})` : "");
    $("fu-guard-events").replaceChildren(...g.events.slice(0, 6).map((e) => {
      const li = make("li"); li.appendChild(make("span", "bd-badge", e.event));
      li.appendChild(make("span", "bd-title", `${e.t.replace("T", " ")}${e.heard ? ` — said “${e.heard}”` : ""}${e.why ? ` — ${e.why}` : ""}`)); return li;
    }));
    $("fu-guard-photos").replaceChildren(...g.photos.map((name) => {
      if (shown[name]) { const img = make("img"); img.alt = `Snapshot ${name}`; img.src = shown[name]; return img; }
      const b = make("button", "btn-ghost", name.slice(5, 16).replace("_", " ")); b.type = "button";
      b.addEventListener("click", async () => {
        try { const r = await withPin("/api/full/guard", { photo: name }); shown[name] = `data:image/jpeg;base64,${r.jpeg}`; poll(); }
        catch (e) { alert(e.message); }
      });
      return b;
    }));
  }
  $("fu-arm").addEventListener("click", () => act(post("/api/full/guard", { arm: true })));
  $("fu-disarm").addEventListener("click", () => act(withPin("/api/full/guard", { disarm: true })));
  $("fu-guard-del").addEventListener("click", () => confirm("Delete every guard photo?") && act(withPin("/api/full/guard", { delete_photos: true })));
  $("fu-guard-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = ev.target.elements;
    const guard = { auto_arm: f.auto_arm.checked };
    if (f.passphrase.value) guard.passphrase = f.passphrase.value;
    act(withPin("/api/full/settings", { guard }).then(() => { f.passphrase.value = ""; }));
  });

  /* ---- Telegram ---- */
  function renderTelegram(t) {
    $("fu-tg-state").textContent = !t.configured ? "not set up" : !t.enabled ? "off" : t.bot ? `@${t.bot}` : "connecting…";
    $("fu-tg-note").textContent = !t.configured ? "Message @BotFather in Telegram → /newbot, put the token in secrets.env as TELEGRAM_BOT_TOKEN, restart, then pair." :
      `${t.paired} chat${t.paired === 1 ? "" : "s"} paired · ${t.received} received · ${t.sent} sent${t.error ? ` · ${t.error}` : ""}`;
    const code = $("fu-tg-code");
    code.hidden = !t.pair_code;
    if (t.pair_code) code.textContent = `Send “/pair ${t.pair_code}” to ${t.bot ? "@" + t.bot : "your bot"} (${Math.ceil(t.pair_left_s / 60)} min left)`;
  }
  $("fu-tg-pair").addEventListener("click", () => act(withPin("/api/full/telegram", { pair: true })));
  $("fu-tg-unpair").addEventListener("click", () => confirm("Unpair every chat?") && act(withPin("/api/full/telegram", { unpair: true })));
  $("fu-tg-test").addEventListener("click", () => act(post("/api/full/telegram", { test: true })));

  /* ---- local AI ---- */
  function renderLlm(l) {
    $("fu-llm-state").textContent = l.available ? "ready" : l.models.length ? "model missing" : "Ollama not found";
    $("fu-llm-note").textContent = l.models.length ? `Ollama at ${l.url}: ${l.models.join(", ")}` :
      `No Ollama at ${l.url}. Install it from ollama.com, run “ollama pull llama3.2:3b”, or point OLLAMA_URL at a laptop on your Wi-Fi.`;
  }
  $("fu-llm-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = Object.fromEntries(new FormData(ev.target));
    act(post("/api/full/settings", { local_llm: { text_model: f.text_model, vision_model: f.vision_model }, reader: { ocr: f.ocr } }));
  });
  $("fu-brief-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const e = ev.target.elements;
    act(post("/api/full/settings", { briefing: { auto: e.auto.checked, morning_time: e.morning_time.value, evening_time: e.evening_time.value, telegram: e.telegram.checked } }));
  });

  function fillForms(s) {
    const b = $("fu-brief-form").elements;
    b.auto.checked = s.briefing.auto; b.morning_time.value = s.briefing.morning_time; b.evening_time.value = s.briefing.evening_time; b.telegram.checked = s.briefing.telegram;
    const l = $("fu-llm-form").elements;
    l.text_model.value = s.local_llm.text_model; l.vision_model.value = s.local_llm.vision_model; l.ocr.value = s.reader.ocr;
    $("fu-learn").elements.owner_name.value = s.owner.name;
    $("fu-guard-form").elements.auto_arm.checked = s.guard.auto_arm;
    $("fu-guard-form").elements.passphrase.placeholder = s.guard.passphrase ? "(set: type to change)" : "";
  }

  async function poll() {
    try {
      S = await (await fetch("/api/full")).json();
      renderFeatures(S.features); renderWake(S.wake); renderBrief(S.briefing); renderRoutines(S.routines); renderHome(S.smarthome);
      renderReader(S.reader); renderWater(S.hydration); renderRps(S.rps); renderPeople(S.faces); renderGuard(S.guard);
      renderTelegram(S.telegram); renderLlm(S.local_llm);
      if (!formsFilled) { fillForms(S.settings); formsFilled = true; }
    } catch { /* robot offline */ }
  }
  poll();
  if (!STILL) setInterval(poll, 1500);
})();
