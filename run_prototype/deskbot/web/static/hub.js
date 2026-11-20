/* Hub cards: focus mode, ideas, music, connected accounts (PIN-protected changes), API costs. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const STILL = new URLSearchParams(location.search).has("still");
  const post = async (url, body = {}) => {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(data.error || r.statusText); e.status = r.status; throw e; }
    return data;
  };
  const make = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const when = (t) => (t ? new Date(t * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—");
  const money = (usd, inr) => `$${usd.toFixed(usd < 0.01 ? 4 : 2)} · ₹${inr.toFixed(inr < 1 ? 2 : 0)}`;
  let state = null, pin = null, capFilled = false, ideaFilter = "";

  /* ---- PIN: asked once per page load, kept only in this page's memory ---- */
  async function withPin(body) {
    if (!pin) {
      pin = prompt("Admin PIN (ADMIN_PIN in secrets.env)");
      if (!pin) throw new Error("PIN needed");
    }
    try { return await post("/api/hub/accounts", { ...body, pin }); }
    catch (e) { if (e.status === 403) pin = null; throw e; }
  }

  /* ---- focus ---- */
  const OBS = { focused: "focused", away: "looking away", down: "looking down", phone: "on the phone", absent: "not at the desk",
                unknown: "can't see your face", starting: "starting…", "no camera": "no camera: timer only" };
  function renderFocus(f) {
    const card = $("hb-focus-card");
    card.dataset.obs = f.observation || "";
    $("hb-focus-state").textContent = f.state === "focusing" ? "focusing" : f.state === "break" ? "break" : "off";
    $("hb-focus-today").textContent = `${f.today_focused_min} min`;
    if (f.state === "focusing") {
      $("hb-focus-clock").textContent = mmss(f.left_s);
      $("hb-focus-obs").textContent = (f.calibrated ? "" : "learning your focused pose · ") + (OBS[f.observation] || f.observation);
      $("hb-focus-pct").textContent = f.focused_pct == null ? "—" : `${f.focused_pct}%`;
      $("hb-focus-dist").textContent = f.distractions;
      $("hb-focus-bar").style.width = `${100 - (100 * f.left_s) / (f.minutes * 60)}%`;
    } else if (f.state === "break") {
      $("hb-focus-clock").textContent = mmss(f.break_left_s);
      $("hb-focus-obs").textContent = "Break. Stretch, drink some water.";
      $("hb-focus-bar").style.width = "0";
    } else {
      $("hb-focus-clock").textContent = "—";
      const last = f.history[0];
      $("hb-focus-obs").textContent = last ? `Last: ${last.minutes} min, ${last.focused_pct ?? "?"}% focused, ${last.distractions} distractions` : "Say “start focus mode” or press a button.";
      $("hb-focus-pct").textContent = "—"; $("hb-focus-dist").textContent = "—";
      $("hb-focus-bar").style.width = "0";
    }
    $("hb-focus-note").textContent = !f.camera ? "No camera: focus mode is a timer only." :
      f.face_model && f.face_model !== "ready" && f.face_model !== "not loaded" ? `Face direction off (${f.face_model}); phone and presence checks still work.` :
      "Put the robot by your screen, facing you. Nothing is recorded or sent anywhere.";
  }
  $("hb-focus-25").addEventListener("click", () => post("/api/hub/focus", { start: 25 }).then(poll).catch((e) => alert(e.message)));
  $("hb-focus-50").addEventListener("click", () => post("/api/hub/focus", { start: 50, break: 10 }).then(poll).catch((e) => alert(e.message)));
  $("hb-focus-stop").addEventListener("click", () => post("/api/hub/focus", { stop: true }).then(poll).catch((e) => alert(e.message)));

  /* ---- ideas ---- */
  function renderIdeas(i) {
    $("hb-ideas-count").textContent = `${i.count} saved` + (i.capturing ? " · listening…" : "");
    const list = i.ideas.filter((x) => !ideaFilter || x.text.toLowerCase().includes(ideaFilter));
    $("hb-ideas").replaceChildren(...(list.length ? list.map((x) => {
      const li = make("li");
      li.appendChild(make("span", "bd-badge", x.created.slice(5, 16).replace("T", " ")));
      li.appendChild(make("span", "bd-title", x.text));
      const del = make("button", "bd-x", "×");
      del.type = "button"; del.setAttribute("aria-label", `Delete idea: ${x.text}`);
      del.addEventListener("click", () => post("/api/hub/ideas", { remove: x.id }).then(poll).catch((e) => alert(e.message)));
      li.appendChild(del);
      return li;
    }) : [make("li", "bd-empty", i.count ? "No idea matches." : "No ideas yet. Say “remember this idea…”")]));
  }
  $("hb-idea-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const t = $("hb-idea-text").value.trim();
    if (!t) return;
    try { await post("/api/hub/ideas", { add: t }); $("hb-idea-text").value = ""; poll(); } catch (e) { alert(e.message); }
  });
  $("hb-idea-search").addEventListener("input", (ev) => { ideaFilter = ev.target.value.trim().toLowerCase(); if (state) renderIdeas(state.ideas); });

  /* ---- music ---- */
  function renderMusic(acc, sp) {
    const a = acc.spotify;
    $("hb-music-state").textContent = a.connected ? `Spotify · ${a.account}${a.premium === false ? " (not Premium)" : ""}` : "Spotify not connected";
    const last = sp.last;
    $("hb-now").textContent = !a.connected ? "Connect Spotify under Connected accounts. Playback control needs Spotify Premium." :
      last && last.action === "play" ? `Last: ${last.name}${last.by ? " · " + last.by : ""} on ${last.device}` : "Say “play lo-fi beats”, or type below.";
  }
  const spot = (body) => post("/api/hub/spotify", body).then(poll).catch((e) => alert(e.message));
  $("hb-play-form").addEventListener("submit", (ev) => { ev.preventDefault(); const q = $("hb-play-text").value.trim(); if (q) spot({ play: q }); });
  document.querySelectorAll("[data-sp]").forEach((b) => b.addEventListener("click", () => spot({ action: b.dataset.sp })));
  $("hb-vol").addEventListener("change", (ev) => spot({ action: "volume", volume: Number(ev.target.value) }));

  /* ---- connected accounts ---- */
  function renderAccounts(s) {
    $("hb-acc-lock").textContent = s.pin_set ? "PIN protected" : "locked: set ADMIN_PIN";
    $("hb-accounts").replaceChildren(...Object.entries(s.accounts).map(([name, a]) => {
      const li = make("li");
      const info = make("div");
      info.appendChild(make("b", null, a.title));
      if (a.connected) {
        info.appendChild(make("span", "hb-sub", `as ${a.account} · since ${when(a.connected_at)} · last used ${when(a.last_used)}`));
        info.appendChild(make("span", "hb-sub", `access: ${(a.scopes || []).map((x) => x.replace("https://www.googleapis.com/auth/", "")).join(", ")}`));
      } else if (!a.configured) {
        info.appendChild(make("span", "hb-sub", `Not set up: add ${a.client_id_env} to secrets.env. Redirect URI to register: ${a.redirect_uri}`));
      } else {
        info.appendChild(make("span", "hb-sub", `Not connected. Redirect URI: ${a.redirect_uri}`));
      }
      if (a.error) info.appendChild(make("span", "hb-sub hb-err", a.error));
      const btn = make("button", a.connected ? "btn-ghost" : "btn-primary", a.connected ? "Disconnect" : "Connect");
      btn.type = "button";
      btn.disabled = !a.configured || !s.pin_set;
      btn.addEventListener("click", async () => {
        try {
          if (a.connected) {
            if (!confirm(`Disconnect ${a.title}? The robot forgets the sign-in${name === "google" ? " and revokes it at Google" : ""}.`)) return;
            const r = await withPin({ action: "disconnect", provider: name });
            if (!r.revoked) alert(`Also remove the robot's access at ${r.manage_url}`);
          } else {
            const r = await withPin({ action: "start", provider: name });
            window.open(r.url, "_blank", "noopener");
            $("hb-finish-box").open = true;
          }
          poll();
        } catch (e) { alert(e.message); }
      });
      li.append(info, btn);
      return li;
    }));
    const enc = s.encryption === "fernet" ? "Tokens are encrypted on the robot (ACCOUNTS_KEY)." :
      `Tokens are stored on the robot without encryption (${s.encryption}); set ACCOUNTS_KEY to encrypt them.`;
    $("hb-acc-security").textContent = `${enc} No token ever leaves the robot or appears on this page.`;
  }
  $("hb-finish").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const url = ev.target.elements.url.value.trim();
    if (!url) return;
    try { const r = await withPin({ action: "finish", url }); ev.target.reset(); alert(`Connected ${r.title} as ${r.account}`); poll(); }
    catch (e) { alert(e.message); }
  });
  async function renderKeys() {
    try {
      const a = await (await fetch("/api/assistant")).json();
      const keys = a.settings.keys || {};
      const label = { ANTHROPIC_API_KEY: "Anthropic (Claude) API key", GROQ_API_KEY: "Groq speech-to-text key", OPENAI_API_KEY: "OpenAI key (paid, blocked unless allowed)" };
      $("hb-keys").replaceChildren(...Object.entries(keys).map(([k, on]) => {
        const li = make("li");
        li.append(make("span", null, label[k] || k), make("span", on ? "hb-ok" : "co-note", on ? "set" : "not set"));
        return li;
      }));
    } catch { /* offline */ }
  }

  /* ---- costs ---- */
  function renderCosts(c) {
    $("hb-cost-today").textContent = money(c.today.usd, c.today_inr);
    $("hb-cost-month").textContent = money(c.month_usd, c.month_inr);
    $("hb-cost-calls").textContent = c.today.calls;
    $("hb-cost-state").textContent = c.over_cap ? "cap reached: simple mode" : c.cap_usd ? `cap $${c.cap_usd.toFixed(2)}/day` : "no cap";
    $("hb-cost-note").textContent = `Estimate from token counts (${c.today.input + c.today.cache_read} in, ${c.today.output} out today) at $1 = ₹${c.usd_to_inr}. ` +
      "Your real bill and a hard spend limit are in the Anthropic Console.";
    $("hb-services").replaceChildren(...c.services.map((s) => {
      const li = make("li");
      li.appendChild(make("b", null, `${s.name}: ${s.cost}`));
      li.appendChild(make("span", null, `${s.used_for}. ${s.note}`));
      return li;
    }));
  }
  $("hb-cap-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try { await post("/api/hub/settings", { costs: { daily_cap_usd: Number(ev.target.elements.daily_cap_usd.value) } }); poll(); }
    catch (e) { alert(e.message); }
  });

  async function poll() {
    try {
      state = await (await fetch("/api/hub")).json();
      renderFocus(state.focus);
      renderIdeas(state.ideas);
      renderMusic(state.accounts, state.spotify);
      renderAccounts(state);
      renderCosts(state.costs);
      if (!capFilled) { $("hb-cap-form").elements.daily_cap_usd.value = state.settings.costs.daily_cap_usd; capFilled = true; }
    } catch { /* robot offline */ }
  }
  poll();
  renderKeys();
  if (!STILL) { setInterval(poll, 1000); setInterval(renderKeys, 15000); }
})();
