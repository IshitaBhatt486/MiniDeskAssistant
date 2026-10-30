/* Assistant, presence, personality and warnings cards (deskbot/assistant/app.py). Polls /api/assistant at 1 Hz. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const time = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  let state = null;
  let renderedChat = "";
  let settingsLoaded = false;
  let busy = false;

  // ---------------- conversation ----------------

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function renderChat(log) {
    const key = log.map((e) => e.id).join(",");
    if (key === renderedChat) return;
    renderedChat = key;
    const chat = $("chat");
    if (!log.length) {
      chat.replaceChildren(el("li", "empty", "Say or type something. Try “what can you see?”, “what's the weather?”, “spin around” or “find my phone”."));
      return;
    }
    chat.replaceChildren(...log.map((e) => {
      const li = el("li", "turn");
      if (e.user) {
        li.appendChild(el("div", "bubble user", e.user));
        li.appendChild(el("div", "turn-meta user", `${e.source} · ${time(e.t)}`));
      }
      li.appendChild(el("div", "bubble bot" + (e.error ? " err" : ""), e.speech || "…"));
      const meta = el("div", "turn-meta");
      meta.appendChild(el("span", null, `${e.backend}${e.ms ? ` · ${(e.ms / 1000).toFixed(1)} s` : ""}${e.image ? " · saw camera" : ""}`));
      for (const t of e.tools || []) meta.appendChild(el("span", "chip" + (t.error ? " bad" : ""), `🔧 ${t.name}`));
      for (const c of e.commands || []) meta.appendChild(el("span", "chip", c.amount ? `${c.action} ${+c.amount.toFixed(2)}` : c.action));
      for (const p of e.problems || []) meta.appendChild(el("span", "chip bad", p));
      li.appendChild(meta);
      const det = el("details");
      det.appendChild(el("summary", null, "JSON"));
      det.appendChild(el("pre", null, JSON.stringify({ speech: e.speech, mood: e.mood, commands: e.commands }, null, 2)));
      li.appendChild(det);
      return li;
    }));
    chat.scrollTop = chat.scrollHeight;
  }

  async function send(url, init) {
    if (busy) return;
    busy = true;
    $("as-send").disabled = true;
    try {
      const r = await fetch(url, init);
      const j = await r.json().catch(() => ({}));
      if (!r.ok) toast(j.error || `Error ${r.status}`);
    } catch {
      toast("The robot didn't answer. Is it still running?");
    } finally {
      busy = false;
      $("as-send").disabled = false;
      poll();
    }
  }

  function toast(msg) {
    const chat = $("chat");
    const li = el("li", "turn");
    li.appendChild(el("div", "bubble bot err", msg));
    chat.appendChild(li);
    chat.scrollTop = chat.scrollHeight;
  }

  $("as-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const text = $("as-text").value.trim();
    if (!text) return;
    $("as-text").value = "";
    send("/api/assistant/text", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
  });
  $("as-stop").addEventListener("click", () => post("/api/assistant/stop"));
  $("robot-mic-btn").addEventListener("click", () =>
    send("/api/assistant/listen", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ seconds: 5 }) }));

  // ---------------- push to talk ----------------

  const talk = $("talk-btn");
  let rec = null;
  async function startTalk(ev) {
    ev.preventDefault();
    if (rec || busy) return;
    const why = VoiceRecorder.whyUnsupported();
    if (why) {
      $("as-insecure").hidden = false;
      if (why === "nomic") toast("This browser has no microphone access.");
      return;
    }
    rec = new VoiceRecorder.Recorder((p) => { $("talk-level").style.width = `${Math.min(100, p * 180)}%`; });
    try {
      await rec.start();
      talk.classList.add("is-recording");
      $("talk-label").textContent = "Listening… release to send";
    } catch (e) {
      rec = null;
      toast(e && e.name === "NotAllowedError" ? "Microphone permission was denied." : `Microphone error: ${e && e.message}`);
    }
  }
  async function endTalk() {
    if (!rec) return;
    const r = rec;
    rec = null;
    talk.classList.remove("is-recording");
    $("talk-label").textContent = "Hold to talk";
    $("talk-level").style.width = "0";
    const out = await r.stop();
    if (!out || out.seconds < 0.4) return toast("Hold the button while you talk.");
    send("/api/assistant/audio", { method: "POST", headers: { "Content-Type": "audio/wav", "X-Source": "dashboard mic" }, body: out.blob });
  }
  talk.addEventListener("pointerdown", startTalk);
  talk.addEventListener("pointerup", endTalk);
  talk.addEventListener("pointerleave", endTalk);
  talk.addEventListener("pointercancel", endTalk);
  talk.addEventListener("keydown", (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) startTalk(e); });
  talk.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") endTalk(); });

  // ---------------- presence ----------------

  function spark(canvas, values, lo, hi) {
    const ctx = canvas.getContext("2d");
    const w = (canvas.width = canvas.clientWidth * devicePixelRatio), h = (canvas.height = canvas.clientHeight * devicePixelRatio);
    ctx.clearRect(0, 0, w, h);
    if (values.length < 2) return;
    ctx.strokeStyle = css("--move");
    ctx.lineWidth = 1.5 * devicePixelRatio;
    ctx.beginPath();
    values.forEach((v, i) => {
      const x = (i / (values.length - 1)) * w, y = h - ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * (h - 4) - 2;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  }

  function polar(canvas, scan, bestDeg) {
    const ctx = canvas.getContext("2d");
    const s = (canvas.width = canvas.height = canvas.clientWidth * devicePixelRatio);
    const c = s / 2, R = s / 2 - 8;
    ctx.clearRect(0, 0, s, s);
    ctx.strokeStyle = css("--border-strong");
    ctx.beginPath(); ctx.arc(c, c, R, 0, 2 * Math.PI); ctx.stroke();
    const valid = scan.filter((v) => v != null);
    if (!valid.length) return;
    const lo = Math.min(...valid) - 3, hi = Math.max(...valid);
    // heading 0 = straight up (where the robot faced when the scan began), positive = to the left (CCW)
    ctx.fillStyle = css("--move");
    scan.forEach((v, i) => {
      if (v == null) return;
      const a = -Math.PI / 2 - (i * 30 * Math.PI) / 180;
      const r = 6 + ((v - lo) / Math.max(1, hi - lo)) * (R - 6);
      ctx.beginPath(); ctx.arc(c + Math.cos(a) * r, c + Math.sin(a) * r, 3.5 * devicePixelRatio, 0, 2 * Math.PI); ctx.fill();
    });
    if (bestDeg != null) {
      const a = -Math.PI / 2 - (bestDeg * Math.PI) / 180;
      ctx.strokeStyle = css("--ok"); ctx.lineWidth = 2 * devicePixelRatio;
      ctx.beginPath(); ctx.moveTo(c, c); ctx.lineTo(c + Math.cos(a) * R, c + Math.sin(a) * R); ctx.stroke();
    }
  }

  function renderPresence(p, lift, map, sim) {
    if (!p) {
      $("pr-awake").textContent = "Bluetooth off";
      return;
    }
    $("pr-awake").textContent = p.awake ? "awake" : `asleep (${p.sleep_reason})`;
    $("pr-awake").className = "tag " + (p.awake ? "is-ok" : "");
    const t = p.tracker;
    $("pr-phone").textContent = t.state;
    $("pr-rssi").textContent = t.rssi == null ? "—" : `${Math.round(t.rssi)} dBm`;
    $("pr-dist").textContent = t.distance_m == null || t.state === "away" ? "—" : `~${t.distance_m} m`;
    spark($("pr-spark"), t.history || [], -100, -35);
    const f = p.find || {};
    $("pr-find-box").hidden = !f.phase || f.phase === "idle";
    if (f.scan) polar($("pr-polar"), f.scan, f.best_deg);
    const lines = [`${f.phase || ""}${f.phase === "scanning" ? ` ${(f.step || 0) + 1}/12` : ""}`];
    if (f.best_deg != null) lines.push(`best heading ${f.best_deg}° left (spread ${f.spread_db} dB)`);
    if (f.hops) lines.push(`hops ${f.hops}${f.rssi != null ? ` · ${f.rssi} dBm` : ""}`);
    if (f.result) lines.push(`result: ${f.result}`);
    $("pr-find-text").textContent = lines.join("\n");
    const src = p.source || {};
    $("pr-match").textContent = src.error ? `(${src.error})` : `(${src.backend || "?"})`;
    const devs = p.devices || [];
    $("pr-devices").replaceChildren(...(devs.length ? devs.map((d) => {
      const li = el("li", d.match ? "is-match" : "");
      li.appendChild(el("span", "dev-name", `${d.name || "(no name)"} ${d.ibeacon ? "· iBeacon" : ""}`));
      li.appendChild(el("span", "mono muted", `${d.rssi} dBm`));
      if (!d.match) {
        const b = el("button", "btn-ghost", "This is mine");
        b.title = d.address + (d.ibeacon ? ` · ${d.ibeacon}` : "");
        b.addEventListener("click", () => post("/api/presence", { use_device: d }).then(poll));
        li.appendChild(b);
      } else li.appendChild(el("span", "tag is-ok", "tracking"));
      return li;
    }) : [el("li", "muted", "Nothing heard yet.")]));
    $("pr-lift").textContent = lift.lifted ? `LIFTED ${lift.since_s}s` : "yes";
    $("pr-lift").className = "tag " + (lift.lifted ? "is-warn" : "is-ok");
    if (map) $("pr-map").textContent = map.paused ? "map paused" : `map ${map.rate_hz} Hz · ${lift.map_resets} resets`;
    $("pr-sim").hidden = !sim;
    if (sim && src.present != null && document.activeElement !== $("sim-phone")) $("sim-phone").checked = src.present;
    if (sim && document.activeElement !== $("sim-lift")) $("sim-lift").checked = lift.lifted;
  }

  $("pr-find").addEventListener("click", () => post("/api/presence", { find_phone: true }).then(poll));
  $("pr-sleep").addEventListener("click", () => post("/api/presence", { awake: false }).then(poll));
  $("pr-wake").addEventListener("click", () => post("/api/presence", { awake: true }).then(poll));
  $("sim-lift").addEventListener("change", (e) => post("/api/sim/lift", { lifted: e.target.checked }));
  $("sim-phone").addEventListener("change", (e) => post("/api/sim/phone", { present: e.target.checked }));

  // ---------------- personality ----------------

  function loadSettings(s) {
    const sel = $("ps-preset");
    if (sel.options.length === 1) {
      for (const name of Object.keys(s.presets)) sel.appendChild(new Option(name, name));
    }
    sel.value = Object.keys(s.presets).find((k) => s.presets[k] === s.personality) || "";
    $("ps-personality").value = s.personality;
    $("ps-name").value = s.robot_name;
    $("ps-location").value = s.location;
    $("ps-speak").checked = s.speak;
    for (const [id, options] of [["ps-voice", s.voice_styles], ["ps-gender", s.voice_genders]]) {
      if (!$(id).options.length) for (const [value, label] of Object.entries(options)) $(id).appendChild(new Option(label, value));
    }
    $("ps-voice").value = s.voice_style === "chipmunk" && !s.chipmunk ? "natural" : s.voice_style;
    $("ps-gender").value = s.voice_gender;
    $("ps-image").checked = s.send_image;
    $("ps-exec").checked = s.execute_commands;
    $("ps-alerts").checked = s.speak_alerts;
    $("ps-factor").value = s.chipmunk_factor;
    $("ps-volume").value = s.volume;
    sliders();
  }
  function sliders() {
    $("ps-factor-v").textContent = `×${(+$("ps-factor").value).toFixed(1)}`;
    $("ps-volume-v").textContent = `${Math.round($("ps-volume").value * 100)}%`;
  }
  $("ps-factor").addEventListener("input", sliders);
  $("ps-volume").addEventListener("input", sliders);
  $("ps-preset").addEventListener("change", (e) => {
    if (e.target.value && state) $("ps-personality").value = state.settings.presets[e.target.value];
  });
  $("ps-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const body = {
      personality: $("ps-personality").value, robot_name: $("ps-name").value, location: $("ps-location").value,
      speak: $("ps-speak").checked, voice_style: $("ps-voice").value, voice_gender: $("ps-gender").value,
      chipmunk: $("ps-voice").value === "chipmunk", send_image: $("ps-image").checked,
      execute_commands: $("ps-exec").checked, speak_alerts: $("ps-alerts").checked,
      chipmunk_factor: +$("ps-factor").value, volume: +$("ps-volume").value,
    };
    const r = await post("/api/assistant/settings", body);
    const j = await r.json().catch(() => ({}));
    $("ps-msg").textContent = r.ok ? "Saved." : j.error || "Not saved";
    $("ps-msg").classList.toggle("is-ok", r.ok);
  });
  $("ps-test").addEventListener("click", async () => {
    await post("/api/assistant/settings", { voice_style: $("ps-voice").value, voice_gender: $("ps-gender").value,
      chipmunk: $("ps-voice").value === "chipmunk", chipmunk_factor: +$("ps-factor").value, volume: +$("ps-volume").value });
    post("/api/assistant/say", { text: `Hi! I'm ${$("ps-name").value || "your robot"}. How do I sound?` });
  });

  // ---------------- warnings ----------------

  function alertItem(a) {
    const li = el("li", a.level);
    li.appendChild(el("span", "when", time(a.t)));
    li.appendChild(document.createTextNode(a.msg));
    if (a.detail) li.appendChild(el("span", "detail", a.detail));
    return li;
  }
  function renderAlerts(al) {
    $("al-count").textContent = al.active.length ? `${al.active.length} active` : "none";
    $("al-active").replaceChildren(...(al.active.length ? al.active.map(alertItem) : [el("li", "muted", "All good.")]));
    $("al-history").replaceChildren(...al.history.slice().reverse().map(alertItem));
  }

  // ---------------- poll ----------------

  function tag(id, text, ok) {
    $(id).textContent = text;
    $(id).className = "tag " + (ok ? "is-ok" : "is-warn");
  }

  async function poll() {
    try {
      state = await (await fetch("/api/assistant")).json();
      const s = state;
      tag("as-brain", s.brain.backend === "claude" ? `brain ${s.brain.model}` : "brain offline", s.brain.backend === "claude");
      $("as-brain").title = s.brain.why_offline || `effort ${s.brain.effort}`;
      tag("as-stt", s.stt.available.length ? `speech ${s.stt.available[0]}` : "speech none", s.stt.available.length > 0);
      $("as-stt").title = s.stt.available.length ? `order: ${s.stt.available.join(" → ")}` : "Add GROQ_API_KEY to secrets.env or install faster-whisper";
      tag("as-voice", s.speaker.engine ? `voice ${s.speaker.engine}` : "voice none", !!s.speaker.engine && !s.speaker.error);
      $("as-voice").title = s.speaker.error || `player ${s.speaker.player}${s.speaker.device ? " · " + s.speaker.device : ""}`;
      const face = $("as-face");
      const last = s.assistant.log[s.assistant.log.length - 1];
      face.dataset.mood = s.presence && !s.presence.awake ? "sleepy" : last ? last.mood : "neutral";
      face.dataset.phase = s.assistant.phase;
      $("as-phase").textContent = s.speaker.speaking ? "speaking" : s.assistant.phase;
      renderChat(s.assistant.log);
      renderPresence(s.presence, s.lift, s.map, s.sim);
      renderAlerts(s.alerts);
      const k = s.settings.keys;
      $("ps-keys").textContent = `keys: Anthropic ${k.ANTHROPIC_API_KEY ? "✓" : "✗"} · Groq ${k.GROQ_API_KEY ? "✓" : "✗"}`;
      $("ps-keys").title = "API keys live in secrets.env on the robot (never sent from the browser)";
      if (!settingsLoaded) { loadSettings(s.settings); settingsLoaded = true; }
      if (!window.isSecureContext && s.urls.https && s.urls.https.length) {
        const host = location.hostname;
        const match = s.urls.https.find((u) => u.includes(host)) || s.urls.https[0];
        $("as-https-link").href = match.replace(/https:\/\/[^:/]+/, `https://${host}`);
        $("as-insecure").hidden = false;
      }
    } catch { /* offline: the main dashboard shows the connection state */ }
  }
  poll();
  setInterval(poll, 1000);
})();
