/* Phone remote (/remote). Hold-to-drive: while a direction is held, a 0.5 s move is re-sent every 250 ms
   (the motor process always runs the NEWEST command, so this is smooth); releasing sends stop. If the
   phone loses Wi-Fi mid-drive, the last move simply ends after 0.5 s - it can never run away. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const RESEND_MS = 250;   // the server sends a 0.5 s move each time
  let driveTimer = null, activeBtn = null, busy = false, lastId = null, lastWav = null, awake = true;

  try { $("r-play").checked = localStorage.getItem("deskbot-remote-play") === "1"; } catch { /* private mode */ }
  $("r-play").addEventListener("change", (e) => { try { localStorage.setItem("deskbot-remote-play", e.target.checked ? "1" : "0"); } catch { /* ignore */ } });

  // ---------- drive ----------
  function startDrive(btn) {
    stopDrive(false);
    activeBtn = btn;
    btn.classList.add("is-active");
    const send = () => post("/api/drive", { direction: btn.dataset.dir }).catch(() => {});
    send();
    driveTimer = setInterval(send, RESEND_MS);
    if (navigator.vibrate) navigator.vibrate(10);
  }
  function stopDrive(sendStop = true) {
    if (driveTimer) clearInterval(driveTimer);
    driveTimer = null;
    if (activeBtn) activeBtn.classList.remove("is-active");
    const was = activeBtn;
    activeBtn = null;
    if (sendStop && was) post("/api/stop").catch(() => {});
  }
  document.querySelectorAll(".r-pad [data-dir]").forEach((b) => {
    b.addEventListener("pointerdown", (e) => { e.preventDefault(); b.setPointerCapture(e.pointerId); startDrive(b); });
    b.addEventListener("pointerup", () => stopDrive());
    b.addEventListener("pointercancel", () => stopDrive());
    b.addEventListener("contextmenu", (e) => e.preventDefault());
  });
  $("r-stop").addEventListener("click", () => { stopDrive(false); post("/api/assistant/stop"); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) stopDrive(); });

  // ---------- quick actions ----------
  document.querySelectorAll(".r-actions [data-cmd]").forEach((b) => b.addEventListener("click", () => {
    let action = b.dataset.cmd;
    if (action === "sleep" && !awake) action = "wake";
    post("/api/assistant/commands", { commands: [{ action, amount: 0 }], source: "remote" });
  }));

  // ---------- talk + type ----------
  async function sendTurn(url, init) {
    if (busy) return;
    busy = true;
    $("r-bot").textContent = "…";
    try {
      const r = await fetch(url, init);
      const j = await r.json().catch(() => ({}));
      if (!r.ok) $("r-bot").textContent = j.error || `Error ${r.status}`;
    } catch { $("r-bot").textContent = "The robot didn't answer."; }
    finally { busy = false; poll(); }
  }
  $("as-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("as-text").value.trim();
    if (!text) return;
    $("as-text").value = "";
    sendTurn("/api/assistant/text", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, source: "remote" }) });
  });

  const talk = $("talk-btn");
  let rec = null;
  talk.addEventListener("pointerdown", async (e) => {
    e.preventDefault();
    if (rec || busy) return;
    if (VoiceRecorder.whyUnsupported()) { $("as-insecure").hidden = false; return; }
    rec = new VoiceRecorder.Recorder((p) => { $("talk-level").style.width = `${Math.min(100, p * 180)}%`; });
    try {
      await rec.start();
      talk.classList.add("is-recording");
      $("talk-label").textContent = "Listening…";
    } catch (err) { rec = null; $("r-bot").textContent = `Microphone: ${err && err.name === "NotAllowedError" ? "permission denied" : err && err.message}`; }
  });
  const end = async () => {
    if (!rec) return;
    const r = rec; rec = null;
    talk.classList.remove("is-recording");
    $("talk-label").textContent = "Hold to talk";
    $("talk-level").style.width = "0";
    const out = await r.stop();
    if (!out || out.seconds < 0.4) { $("r-bot").textContent = "Hold the button while you talk."; return; }
    sendTurn("/api/assistant/audio", { method: "POST", headers: { "Content-Type": "audio/wav", "X-Source": "remote mic" }, body: out.blob });
  };
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => talk.addEventListener(ev, end));
  talk.addEventListener("contextmenu", (e) => e.preventDefault());

  // ---------- state ----------
  async function poll() {
    try {
      const s = await (await fetch("/api/assistant")).json();
      const st = await (await fetch("/api/state")).json();
      awake = !s.presence || s.presence.awake;
      $("r-sleep").textContent = awake ? "😴 Sleep" : "☀️ Wake";
      const last = s.assistant.log[s.assistant.log.length - 1];
      $("r-face").dataset.mood = !awake ? "sleepy" : last ? last.mood : "neutral";
      $("r-face").dataset.phase = s.assistant.phase;
      const phase = s.speaker.speaking ? "speaking" : s.assistant.phase;
      $("r-status").innerHTML = "";
      const b = document.createElement("b");
      b.textContent = `${s.settings.robot_name} · ${!awake ? "asleep" : phase === "idle" ? st.state : phase}`;
      $("r-status").append(b, document.createElement("br"),
        `brain ${s.brain.backend} · phone ${s.presence ? s.presence.tracker.state : "—"}${s.lift.lifted ? " · LIFTED" : ""}`);
      const act = s.alerts.active[0];
      $("r-alert").hidden = !act;
      if (act) $("r-alert").textContent = act.msg;
      if (last && last.id !== lastId && !busy) {
        lastId = last.id;
        $("r-you").textContent = last.user ? `“${last.user}”` : "";
        $("r-bot").textContent = last.speech;
        $("r-meta").replaceChildren(...(last.commands || []).map((c) => {
          const chip = document.createElement("span");
          chip.className = "chip";
          chip.textContent = c.action;
          return chip;
        }));
      }
      if ($("r-play").checked && s.speaker.last_wav_id && s.speaker.last_wav_id !== lastWav) {
        if (lastWav !== null) new Audio(`/api/assistant/speech.wav?id=${s.speaker.last_wav_id}`).play().catch(() => {});
        lastWav = s.speaker.last_wav_id;
      } else if (lastWav === null) lastWav = s.speaker.last_wav_id;
      if (!window.isSecureContext && s.urls.https && s.urls.https.length) {
        $("as-https-link").href = `https://${location.hostname}:${s.urls.https[0].split(":").pop()}/remote`;
      }
    } catch { $("r-status").textContent = "Robot not reachable…"; }
  }
  poll();
  setInterval(poll, 1000);
})();
