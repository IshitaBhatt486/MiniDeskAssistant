/* Buddy cards: the task list (add, tick off, remove, confetti on completion) and phone notifications. */
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
  const say = (msg) => { const t = $("bd-task-count"); if (t) { t.textContent = msg; } };
  const ago = (t) => {
    const s = Math.max(0, Date.now() / 1000 - t);
    return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
  };
  let state = null, lastCelebration = null, justDone = null, formsFilled = false;

  /* ---- confetti ---- */
  const COLORS = ["#e8590c", "#1864ab", "#2b8a3e", "#f59f00", "#c2255c", "#7048e8"];
  function confetti(big) {
    const box = $("bd-confetti");
    if (!box || STILL) return;
    const n = big ? 90 : 45;
    for (let i = 0; i < n; i++) {
      const p = make("i");
      p.style.left = `${Math.random() * 100}%`;
      p.style.background = COLORS[i % COLORS.length];
      p.style.setProperty("--dx", `${(Math.random() - 0.5) * 160}px`);
      p.style.setProperty("--r", `${(Math.random() - 0.5) * 1080}deg`);
      p.style.setProperty("--d", `${1.2 + Math.random() * 1.2}s`);
      p.style.animationDelay = `${Math.random() * 0.25}s`;
      if (i % 3 === 0) { p.style.width = "6px"; p.style.height = "6px"; p.style.borderRadius = "50%"; }
      box.appendChild(p);
    }
    setTimeout(() => box.replaceChildren(), 3000);
  }

  /* ---- tasks ---- */
  function taskRow(t, done) {
    const li = make("li");
    if (justDone === t.id && done) li.classList.add("just-done");
    const box = make("input");
    box.type = "checkbox";
    box.checked = done;
    box.setAttribute("aria-label", `${done ? "Reopen" : "Done:"} ${t.title}`);
    box.addEventListener("change", async () => {
      box.disabled = true;
      try {
        if (!done) justDone = t.id;
        render(await post("/api/buddy/tasks", done ? { reopen: t.id } : { complete: t.id }), null);
        poll();     // picks up the new celebration right away (confetti)
      } catch (e) { say(e.message); box.disabled = false; }
    });
    const body = make("div");
    body.appendChild(make("span", "bd-title", t.title));
    if (t.due_text) body.appendChild(make("span", "bd-due" + (t.overdue ? " late" : ""), (t.overdue ? "overdue · was due " : "due ") + t.due_text));
    else if (!done) body.appendChild(make("span", "bd-due", "no deadline"));
    const x = make("button", "bd-x", "×");
    x.type = "button";
    x.title = "Remove";
    x.setAttribute("aria-label", `Remove ${t.title}`);
    x.addEventListener("click", async () => {
      try { render(await post("/api/buddy/tasks", { remove: t.id }), null); } catch (e) { say(e.message); }
    });
    li.append(box, body, x);
    return li;
  }

  function render(tasks, buddy) {
    if (tasks) {
      const open = tasks.open || [], done = tasks.done || [];
      $("bd-task-count").textContent = open.length ? `${open.length} to do` : "all done";
      $("bd-open").replaceChildren(...(open.length ? open.map((t) => taskRow(t, false)) : [make("li", "bd-empty", "Nothing to do. Tell me when something comes up!")]));
      $("bd-done").replaceChildren(...done.map((t) => taskRow(t, true)));
      $("bd-done-sum").textContent = `Done (${done.length})`;
    }
    if (buddy) {
      const c = buddy.last_celebration;
      if (c && lastCelebration !== null && c.seq !== lastCelebration) confetti(c.all_done);
      lastCelebration = c ? c.seq : 0;
    }
  }

  $("bd-add").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const input = $("bd-add-text");
    const text = input.value.trim();
    if (!text) return;
    try { render(await post("/api/buddy/tasks", { add: text }), null); input.value = ""; } catch (e) { say(e.message); }
  });
  $("bd-party").addEventListener("click", () => post("/api/buddy/celebrate").catch((e) => say(e.message)));

  /* ---- notifications ---- */
  const BADGE = { spoken: "read aloud", waiting: "waiting", skipped: "not important", blocked: "private, hidden",
                  duplicate: "repeat", triaging: "deciding…", expired: "expired", error: "error", dropped: "dropped" };
  function renderNotes(n, settings, phone) {
    const s = settings.notify;
    $("bd-notify-state").textContent = !s.enabled ? "off" : n.waiting ? `${n.waiting} waiting` : (n.ai ? "rules + AI" : "rules");
    const items = n.history || [];
    $("bd-notes").replaceChildren(...(items.length ? items.slice(0, 12).map((e) => {
      const li = make("li");
      li.appendChild(make("span", "bd-badge " + e.status, BADGE[e.status] || e.status));
      const body = make("div");
      const who = e.status === "blocked" ? `${e.app} (hidden)` : `${e.app}${e.title ? " · " + e.title : ""}`;
      body.appendChild(make("span", "bd-title", e.speech && e.status !== "skipped" ? e.speech : `${who}${e.text ? ": " + e.text : ""}`));
      const why = [ago(e.t), e.decided_by ? `by ${e.decided_by}` : null, e.score != null ? `score ${e.score}` : null, ...(e.reasons || [])]
        .filter(Boolean).join(" · ");
      body.appendChild(make("span", "bd-why", why));
      li.appendChild(body);
      return li;
    }) : [make("li", "bd-empty", "Nothing yet. Connect your phone below, or send a test.")]));
    $("bd-url").textContent = phone.url;
    $("bd-token").textContent = phone.token;
    $("bd-new-token").hidden = phone.token_from_env;
    $("bd-example").textContent = JSON.stringify({ token: phone.token, app: "<app name>", title: "<notification title>", text: "<notification text>" }, null, 2);
  }

  const SAMPLES = [
    { label: "Mom (urgent)", app: "WhatsApp", title: "Mom", text: "Call me when you're free, it's urgent" },
    { label: "Sale", app: "Myntra", title: "Big sale!", text: "Up to 70% off, today only" },
    { label: "OTP", app: "Messages", title: "VK-BANK", text: "123456 is your OTP. Do not share it." },
    { label: "Friend", app: "Telegram", title: "Arjun", text: "Are we still meeting at 6?" },
    { label: "Calendar", app: "Calendar", title: "Physics lab", text: "Starts in 15 minutes, room 204", category: "event" },
  ];
  $("bd-samples").replaceChildren(...SAMPLES.map((s) => {
    const b = make("button", "btn-ghost", s.label);
    b.type = "button";
    b.addEventListener("click", () => post("/api/buddy/notifications/test", s).then(poll).catch((e) => say(e.message)));
    return b;
  }));
  $("bd-test").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    try { await post("/api/buddy/notifications/test", Object.fromEntries(f)); poll(); } catch (e) { say(e.message); }
  });
  $("bd-new-token").addEventListener("click", async () => {
    if (!confirm("Make a new token? The phone will need the new one.")) return;
    try { await post("/api/buddy/token"); poll(); } catch (e) { say(e.message); }
  });

  /* ---- settings forms ---- */
  function fill(form, values) {
    for (const el of form.elements) {
      if (!el.name || !(el.name in values)) continue;
      const v = values[el.name];
      if (el.type === "checkbox") el.checked = !!v;
      else el.value = Array.isArray(v) ? v.join(", ") : v;
    }
  }
  function read(form) {
    const out = {};
    for (const el of form.elements) {
      if (!el.name) continue;
      out[el.name] = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value;
    }
    return out;
  }
  for (const [id, section] of [["bd-task-settings", "tasks"], ["bd-notify-settings", "notify"]]) {
    $(id).addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const btn = ev.target.querySelector("button[type=submit]");
      try {
        const saved = await post("/api/buddy/settings", { [section]: read(ev.target) });
        fill(ev.target, saved[section]);
        btn.textContent = "Saved";
        setTimeout(() => (btn.textContent = "Save"), 1500);
      } catch (e) { btn.textContent = e.message; setTimeout(() => (btn.textContent = "Save"), 3000); }
    });
  }

  /* ---- polling ---- */
  async function poll() {
    try {
      state = await (await fetch("/api/buddy")).json();
      render(state.tasks, state.buddy);
      renderNotes(state.notifications, state.settings, state.phone);
      if (!formsFilled) {
        fill($("bd-task-settings"), state.settings.tasks);
        fill($("bd-notify-settings"), state.settings.notify);
        formsFilled = true;
      }
    } catch { /* robot offline: keep the last view */ }
  }
  poll();
  if (!STILL) setInterval(poll, 1500);
})();
