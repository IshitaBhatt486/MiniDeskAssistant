/* The laptop as the robot's speaker (21 Nov 2026; server side: deskbot/assistant/laptop_speaker.py).
   Adds a small "Speaker" box (bottom right of every dashboard, full size on /speaker). Once turned on, it long-polls
   /api/speaker/clips and plays every new clip (replies, alerts, chatter, chimes) in order with Web Audio.
   - Browsers only play sound after a click, so the box has a "Turn on" button. The choice is remembered: after a
     reload the next click anywhere on the page turns it back on.
   - Only one tab plays: turning it on in one tab turns it off in the others (BroadcastChannel), so nothing doubles.
   - "Stop all" on the robot clears the queue here too (the server's interrupt counter changes).
   - The output menu writes the assistant setting speaker_output (laptop | robot | both). */
(() => {
  const KEY = "deskbot-laptop-speaker";
  const tab = Math.random().toString(36).slice(2, 10);
  const chan = "BroadcastChannel" in window ? new BroadcastChannel("deskbot-laptop-speaker") : null;
  const page = document.getElementById("laptop-speaker-page");     // only on /speaker
  const st = { on: false, ctx: null, after: -1, interrupt: -1, queue: [], src: null, busy: false, loop: 0,
               output: "laptop", listeners: 0, failures: 0, played: 0 };

  const css = document.createElement("style");
  css.textContent = `
    #lsp { position: fixed; right: 14px; bottom: 14px; z-index: 50; width: 250px; font: 13px/1.35 system-ui, sans-serif;
      background: var(--card, #fff); color: var(--ink, #111); border: 1px solid var(--border, #ccc);
      border-radius: var(--radius, 10px); box-shadow: 0 4px 16px rgba(0,0,0,.18); padding: 10px 12px; }
    #lsp.big { position: static; width: auto; max-width: 460px; margin: 0 auto; font-size: 15px; box-shadow: none; }
    #lsp .lsp-row { display: flex; align-items: center; gap: 8px; }
    #lsp .lsp-title { font-weight: 600; flex: 1; }
    #lsp .lsp-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--ink-3, #999); flex: none; }
    #lsp .lsp-dot.on { background: #1baf7a; } #lsp .lsp-dot.warn { background: #eda100; } #lsp .lsp-dot.bad { background: #e34948; }
    #lsp .lsp-msg { color: var(--ink-2, #555); margin-top: 6px; min-height: 1.35em; overflow-wrap: anywhere; }
    #lsp .lsp-now { margin-top: 4px; font-style: italic; overflow-wrap: anywhere; }
    #lsp button, #lsp select { font: inherit; padding: 4px 9px; border-radius: 7px; border: 1px solid var(--border, #ccc);
      background: var(--bg, transparent); color: inherit; cursor: pointer; }
    #lsp button.primary { background: #2a78d6; border-color: #2a78d6; color: #fff; }
    #lsp .lsp-hide { border: none; padding: 0 4px; background: none; color: var(--ink-3, #999); }
    #lsp.min .lsp-body { display: none; }
    @media (max-width: 520px) { #lsp:not(.big) { left: 16px; right: 16px; width: auto; } }`;
  document.head.appendChild(css);

  const box = document.createElement("div");
  box.id = "lsp";
  box.innerHTML = `
    <div class="lsp-row"><span class="lsp-dot" id="lsp-dot"></span><span class="lsp-title">🔊 Speaker</span>
      <button type="button" id="lsp-toggle" class="primary">Turn on</button>
      ${page ? "" : '<button type="button" class="lsp-hide" id="lsp-min" title="Minimise">–</button>'}</div>
    <div class="lsp-body">
      <div class="lsp-row" style="margin-top:8px"><label for="lsp-out">Sound plays on</label>
        <select id="lsp-out"><option value="laptop">this laptop</option><option value="robot">the robot</option>
          <option value="both">both</option></select></div>
      <div class="lsp-msg" id="lsp-msg">Off. Click "Turn on" to hear the robot here.</div>
      <div class="lsp-now" id="lsp-now"></div>
    </div>`;
  (page || document.body).appendChild(box);
  if (page) box.classList.add("big");
  const $ = (id) => document.getElementById(id);

  function show(msg, dot) {
    $("lsp-msg").textContent = msg;
    $("lsp-dot").className = "lsp-dot" + (dot ? " " + dot : "");
  }
  function describe() {
    if (!st.on) return show(st.output === "robot" ? "Off. Sound plays on the robot's own speaker." :
                            'Off. Click "Turn on" to hear the robot here.', st.output === "robot" ? "" : "warn");
    if (st.failures) return show(`Can't reach the robot (try ${st.failures}); retrying…`, "bad");
    if (st.output === "robot") return show("On, but the robot is set to play sound itself. Choose 'this laptop'.", "warn");
    const others = Math.max(0, st.listeners - 1);
    show(`Listening${st.played ? ` · ${st.played} played` : ""}${others ? ` · ${others} other listener(s)` : ""}`, "on");
  }

  async function turnOn() {
    try {
      st.ctx = st.ctx || new (window.AudioContext || window.webkitAudioContext)();
      await st.ctx.resume();
    } catch (e) {
      return show("This browser can't play audio here: " + e.message, "bad");
    }
    st.on = true;
    try { localStorage.setItem(KEY, "on"); } catch {}
    if (chan) chan.postMessage({ takeover: tab });
    $("lsp-toggle").textContent = "Turn off";
    $("lsp-toggle").classList.remove("primary");
    st.after = -1;                    // don't replay what was said before
    describe();
    poll(++st.loop);
  }
  function turnOff(note, remember = true) {
    st.on = false;
    st.loop++;
    stopAll();
    if (remember) { try { localStorage.setItem(KEY, "off"); } catch {} }
    $("lsp-toggle").textContent = "Turn on";
    $("lsp-toggle").classList.add("primary");
    describe();
    if (note) show(note, "");
  }
  function stopAll() {
    st.queue = [];
    if (st.src) { try { st.src.stop(); } catch {} st.src = null; }
    $("lsp-now").textContent = "";
  }

  async function poll(loop) {
    while (st.on && loop === st.loop) {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 32000);
      try {
        const r = await fetch(`/api/speaker/clips?after=${st.after}&wait=20&listener=${tab}&interrupt=${st.interrupt}`,
                              { cache: "no-store", signal: ctl.signal });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (!st.on || loop !== st.loop) return;
        st.failures = 0;
        st.output = d.output; st.listeners = d.listeners;
        $("lsp-out").value = d.output;
        if (st.interrupt >= 0 && d.interrupt !== st.interrupt) stopAll();      // "Stop all" on the robot
        st.interrupt = d.interrupt;
        if (st.after < 0) st.after = d.latest;
        for (const c of d.clips) { st.queue.push(c); st.after = Math.max(st.after, c.id); }
        describe();
        pump();
      } catch (e) {
        if (!st.on || loop !== st.loop) return;
        st.failures++;
        describe();
        await new Promise((res) => setTimeout(res, Math.min(10, st.failures) * 1000));
      } finally {
        clearTimeout(timer);
      }
    }
  }

  async function pump() {
    if (st.busy) return;
    st.busy = true;
    try {
      while (st.on && st.queue.length) {
        const c = st.queue.shift();
        let buf;
        try {
          const r = await fetch(`/api/speaker/clip/${c.id}.wav`, { cache: "no-store" });
          if (!r.ok) continue;                                     // too old: the robot only keeps the newest
          buf = await st.ctx.decodeAudioData(await r.arrayBuffer());
        } catch { continue; }
        if (!st.on) break;
        $("lsp-now").textContent = c.kind === "motif" ? `♪ ${c.text}` : c.text ? `“${c.text}”` : "";
        await new Promise((res) => {
          const src = st.ctx.createBufferSource();
          src.buffer = buf;
          src.connect(st.ctx.destination);
          src.onended = res;
          st.src = src;
          src.start();
        });
        st.src = null;
        st.played++;
        $("lsp-now").textContent = "";
        describe();
      }
    } finally {
      st.busy = false;
    }
  }

  $("lsp-toggle").addEventListener("click", () => (st.on ? turnOff() : turnOn()));
  $("lsp-min")?.addEventListener("click", () => {
    box.classList.toggle("min");
    $("lsp-min").textContent = box.classList.contains("min") ? "+" : "–";
  });
  $("lsp-out").addEventListener("change", async (e) => {
    const value = e.target.value;
    try {
      const r = await fetch("/api/assistant/settings", { method: "POST", headers: { "Content-Type": "application/json" },
                                                         body: JSON.stringify({ speaker_output: value }) });
      if (!r.ok) throw new Error((await r.json()).error || `HTTP ${r.status}`);
      st.output = value;
      if (value !== "robot" && !st.on) turnOn();
      describe();
    } catch (err) {
      show("Couldn't change it: " + err.message, "bad");
    }
  });
  if (chan) chan.onmessage = (e) => {
    if (e.data && e.data.takeover && e.data.takeover !== tab && st.on) turnOff("Playing in another tab instead.", false);
  };

  // Remembered "on": browsers need a click before sound, so the first click/key anywhere turns it back on.
  let remembered = false;
  try { remembered = localStorage.getItem(KEY) === "on"; } catch {}
  if (remembered) {
    show("Click anywhere on the page to turn the speaker back on.", "warn");
    const resume = (e) => {
      if (e.target && e.target.closest && e.target.closest("#lsp")) return;    // the box's own buttons handle it
      window.removeEventListener("pointerdown", resume, true);
      window.removeEventListener("keydown", resume, true);
      if (!st.on) turnOn();
    };
    window.addEventListener("pointerdown", resume, true);
    window.addEventListener("keydown", resume, true);
  }
  // Show where sound goes before it's turned on.
  fetch("/api/speaker/clips?after=-1&wait=0", { cache: "no-store" }).then((r) => r.json()).then((d) => {
    st.output = d.output; $("lsp-out").value = d.output;
    if (!st.on && !remembered) describe();
  }).catch(() => {});
})();
