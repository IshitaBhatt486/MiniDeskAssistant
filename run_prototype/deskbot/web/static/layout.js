/* Dashboard layout manager + theme (20 Nov 2026, pro runtime).

   Every <section class="card"> in <main class="grid"> becomes a movable card with a key (its id, or "c-" + its
   title). A toolbar under the top bar has:
     - "Add a card"    a dropdown of the hidden cards, by group; picking one shows it at the top and scrolls to it
     - "Customize"     edit mode: every card shows a drag handle and a remove (×) button
     - "Reset"         back to the default set and order
     - theme           Auto (follows the system) / Light / Dark
   Removing a card shows "Removed X · Undo" for 6 s. Dragging uses pointer events (mouse, touch and pen alike):
   the card follows the pointer as a ghost and a placeholder shows where it will land (before or after the card
   under the pointer, by which half the pointer is in). Escape cancels a drag.

   Saved per browser in localStorage ("deskbot.layout.v1": {order, hidden, known}, "deskbot.theme"), so a phone and
   a laptop can have different layouts. Cards added in a later version follow the defaults below. Without storage
   (private window) everything still works for the session.
   Hidden cards keep running but get the class "lm-hidden"; pro.js skips polling hidden cards. */
(() => {
  "use strict";
  const KEY = "deskbot.layout.v1", THEME_KEY = "deskbot.theme";
  const DEFAULT_VISIBLE = ["assistant-card", "pro-voice-card", "pro-touch-card", "pro-brain-card", "vision-card", "c-status",
    "c-drive", "alerts-card", "pro-motion-card", "presence-card", "co-face-card", "bd-tasks-card", "pro-apis-card", "pro-accounts-card"];
  const GROUPS = [["pro-", "Pro"], ["fu-", "Full robot"], ["hb-", "Hub"], ["bd-", "Buddy"], ["co-", "Companion"]];
  const grid = document.querySelector("main.grid");
  if (!grid) return;

  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, typeof v === "string" ? v : JSON.stringify(v)); } catch (e) { /* private mode */ } },
  };
  const slug = (s) => s.toLowerCase().replace(/&amp;|&/g, "and").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const titleOf = (c) => (c.querySelector(".card-head h2, h2")?.textContent || "Card").trim();

  // ---- keys and state ----
  const cards = [...grid.querySelectorAll(":scope > section.card")];
  const byKey = new Map();
  for (const c of cards) {
    let k = c.id || "c-" + slug(titleOf(c));
    while (byKey.has(k)) k += "-2";
    c.dataset.cardKey = k;
    byKey.set(k, c);
  }
  const allKeys = [...byKey.keys()];
  const defaults = () => ({
    order: [...DEFAULT_VISIBLE.filter((k) => byKey.has(k)), ...allKeys.filter((k) => !DEFAULT_VISIBLE.includes(k))],
    hidden: allKeys.filter((k) => !DEFAULT_VISIBLE.includes(k)),
    known: allKeys,
  });
  let state = store.get(KEY);
  if (!state || !Array.isArray(state.order)) state = defaults();
  // cards that appeared since the layout was saved: follow the defaults
  for (const k of allKeys) {
    if (!(state.known || []).includes(k)) {
      if (DEFAULT_VISIBLE.includes(k)) state.order.unshift(k); else { state.order.push(k); state.hidden.push(k); }
    }
  }
  state.order = state.order.filter((k) => byKey.has(k));
  for (const k of allKeys) if (!state.order.includes(k)) state.order.push(k);
  state.hidden = state.hidden.filter((k) => byKey.has(k));
  state.known = allKeys;
  const save = () => store.set(KEY, state);

  function apply() {
    for (const k of state.order) grid.appendChild(byKey.get(k));
    for (const [k, c] of byKey) c.classList.toggle("lm-hidden", state.hidden.includes(k));
    refreshPicker();
    const n = allKeys.length - state.hidden.length;
    countEl.textContent = `${n} of ${allKeys.length} cards`;
  }

  // ---- toolbar ----
  const bar = document.createElement("div");
  bar.className = "lm-bar";
  bar.innerHTML = `
    <div class="lm-left">
      <label class="lm-add"><span class="lm-plus" aria-hidden="true">＋</span>
        <select id="lm-picker" aria-label="Add a card"></select></label>
      <button type="button" class="lm-btn" id="lm-edit" aria-pressed="false">Customize</button>
      <button type="button" class="lm-btn lm-quiet" id="lm-reset">Reset</button>
      <span class="lm-count" id="lm-count"></span>
    </div>
    <div class="lm-theme" role="radiogroup" aria-label="Theme">
      <button type="button" role="radio" data-theme-set="auto" title="Follow the system">Auto</button>
      <button type="button" role="radio" data-theme-set="light" title="Light">☀︎ Light</button>
      <button type="button" role="radio" data-theme-set="dark" title="Dark">☾ Dark</button>
    </div>`;
  const topbar = document.querySelector(".topbar");
  (topbar ? topbar.after(bar) : grid.before(bar));
  const picker = bar.querySelector("#lm-picker"), countEl = bar.querySelector("#lm-count");

  function refreshPicker() {
    const hidden = state.hidden.map((k) => [k, titleOf(byKey.get(k))]);
    const groupOf = (k) => (GROUPS.find(([p]) => k.startsWith(p)) || [null, "Robot"])[1];
    const groups = {};
    for (const [k, t] of hidden) (groups[groupOf(k)] ||= []).push([k, t]);
    picker.innerHTML = `<option value="">${hidden.length ? "Add a card…" : "All cards are shown"}</option>` +
      Object.entries(groups).map(([g, items]) => `<optgroup label="${g}">` +
        items.sort((a, b) => a[1].localeCompare(b[1])).map(([k, t]) => `<option value="${k}">${t.replace(/</g, "&lt;")}</option>`).join("") +
        "</optgroup>").join("");
    picker.disabled = !hidden.length;
  }
  picker.addEventListener("change", () => {
    const k = picker.value;
    if (!k) return;
    state.hidden = state.hidden.filter((x) => x !== k);
    state.order = [k, ...state.order.filter((x) => x !== k)];
    save(); apply();
    const c = byKey.get(k);
    c.scrollIntoView({ behavior: "smooth", block: "center" });
    c.classList.add("lm-flash");
    setTimeout(() => c.classList.remove("lm-flash"), 1600);
    window.dispatchEvent(new CustomEvent("deskbot-card-shown", { detail: k }));
    window.dispatchEvent(new Event("resize"));      // canvases size themselves on resize
  });

  const editBtn = bar.querySelector("#lm-edit");
  editBtn.addEventListener("click", () => {
    const on = !document.body.classList.contains("lm-editing");
    document.body.classList.toggle("lm-editing", on);
    editBtn.setAttribute("aria-pressed", String(on));
    editBtn.textContent = on ? "Done" : "Customize";
  });
  bar.querySelector("#lm-reset").addEventListener("click", () => {
    if (!confirm("Go back to the default cards and order?")) return;
    state = defaults(); save(); apply();
  });

  // ---- per-card controls ----
  let toast = null;
  function removeCard(k) {
    const prev = { order: [...state.order], hidden: [...state.hidden] };
    state.hidden.push(k);
    save(); apply();
    toast?.remove();
    toast = document.createElement("div");
    toast.className = "lm-toast";
    toast.innerHTML = `Removed <b></b><button type="button">Undo</button>`;
    toast.querySelector("b").textContent = titleOf(byKey.get(k));
    toast.querySelector("button").onclick = () => { state.order = prev.order; state.hidden = prev.hidden; save(); apply(); toast.remove(); };
    document.body.appendChild(toast);
    setTimeout(() => toast?.remove(), 6000);
  }
  for (const [k, c] of byKey) {
    const head = c.querySelector(".card-head") || c;
    const ctl = document.createElement("span");
    ctl.className = "lm-ctl";
    ctl.innerHTML = `<button type="button" class="lm-handle" title="Drag to move" aria-label="Move ${titleOf(c)}">⠿</button>` +
      `<button type="button" class="lm-x" title="Remove card" aria-label="Remove ${titleOf(c)}">×</button>`;
    head.appendChild(ctl);
    ctl.querySelector(".lm-x").addEventListener("click", () => removeCard(k));
    ctl.querySelector(".lm-handle").addEventListener("pointerdown", (e) => startDrag(e, c));
    ctl.querySelector(".lm-handle").addEventListener("keydown", (e) => {   // keyboard: arrows move the card
      const i = state.order.indexOf(k), visibleOrder = state.order.filter((x) => !state.hidden.includes(x));
      const vi = visibleOrder.indexOf(k);
      const to = e.key === "ArrowLeft" || e.key === "ArrowUp" ? visibleOrder[vi - 1] : e.key === "ArrowRight" || e.key === "ArrowDown" ? visibleOrder[vi + 1] : null;
      if (!to) return;
      e.preventDefault();
      state.order.splice(i, 1);
      const j = state.order.indexOf(to);
      state.order.splice(e.key === "ArrowLeft" || e.key === "ArrowUp" ? j : j + 1, 0, k);
      save(); apply();
      ctl.querySelector(".lm-handle").focus();
    });
  }

  // ---- drag and drop (pointer events) ----
  let drag = null;
  function startDrag(e, card) {
    if (e.button !== undefined && e.button !== 0) return;
    e.preventDefault();
    const r = card.getBoundingClientRect();
    const ph = document.createElement("div");
    ph.className = "lm-placeholder";
    ph.style.gridColumn = getComputedStyle(card).gridColumn;
    ph.style.height = r.height + "px";
    card.after(ph);
    card.classList.add("lm-dragging");
    Object.assign(card.style, { width: r.width + "px", height: r.height + "px", left: r.left + "px", top: r.top + "px" });
    drag = { card, ph, dx: e.clientX - r.left, dy: e.clientY - r.top, id: e.pointerId };
    document.body.classList.add("lm-drag-active");
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", cancelDrag);
    window.addEventListener("keydown", onKey);
  }
  function onMove(e) {
    if (!drag || e.pointerId !== drag.id) return;
    drag.card.style.left = e.clientX - drag.dx + "px";
    drag.card.style.top = e.clientY - drag.dy + "px";
    const edge = 60;           // scroll the page near the top/bottom
    if (e.clientY < edge) window.scrollBy(0, -12); else if (e.clientY > innerHeight - edge) window.scrollBy(0, 12);
    const under = document.elementsFromPoint(e.clientX, e.clientY).find((el) => el.matches?.("main.grid > section.card") && el !== drag.card);
    if (!under || under.classList.contains("lm-hidden")) return;
    const r = under.getBoundingClientRect();
    const after = r.width > r.height * 1.3 ? e.clientX > r.left + r.width / 2 : e.clientY > r.top + r.height / 2;
    if (after ? under.nextElementSibling !== drag.ph : under.previousElementSibling !== drag.ph) under[after ? "after" : "before"](drag.ph);
  }
  function finish(commit) {
    const { card, ph } = drag;
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", endDrag);
    window.removeEventListener("pointercancel", cancelDrag);
    window.removeEventListener("keydown", onKey);
    card.classList.remove("lm-dragging");
    card.removeAttribute("style");
    if (commit) ph.replaceWith(card); else ph.remove();
    document.body.classList.remove("lm-drag-active");
    drag = null;
    if (commit) {
      state.order = [...grid.querySelectorAll(":scope > section.card")].map((c) => c.dataset.cardKey);
      save();
    }
    apply();
  }
  const endDrag = (e) => drag && e.pointerId === drag.id && finish(true);
  const cancelDrag = () => drag && finish(false);
  const onKey = (e) => { if (e.key === "Escape" && drag) finish(false); };

  // ---- theme ----
  const themeBtns = [...bar.querySelectorAll("[data-theme-set]")];
  function setTheme(mode, persist = true) {
    if (mode === "light" || mode === "dark") document.documentElement.dataset.theme = mode;
    else delete document.documentElement.dataset.theme;
    themeBtns.forEach((b) => b.setAttribute("aria-checked", String(b.dataset.themeSet === mode)));
    if (persist) store.set(THEME_KEY, mode);
    window.dispatchEvent(new CustomEvent("deskbot-theme", { detail: mode }));   // canvases with cached colours redraw
  }
  themeBtns.forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.themeSet)));
  let savedTheme = null;
  try { savedTheme = localStorage.getItem(THEME_KEY); } catch (e) { /* private mode */ }
  setTheme(savedTheme === "light" || savedTheme === "dark" ? savedTheme : "auto", false);

  apply();
})();
