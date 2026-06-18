// Maverick popup chat. Thin UI: every network call is delegated to the
// background service worker (see background.js), which talks only to the
// local dashboard. Plain JS, no build step.

const $ = (id) => document.getElementById(id);

let pollTimer = null;
let goalId = null;
let sinceId = 0;
let polling = false; // in-flight guard: skip overlapping ticks (shared sinceId)

function setStatus(text, isError) {
  const el = $("status");
  el.textContent = text || "";
  el.className = isError ? "err" : "hint";
}

function appendEvent(agent, content) {
  const p = document.createElement("p");
  p.className = "evt";
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = agent + ": ";
  p.appendChild(who);
  // textContent only — agent output is untrusted text, never HTML.
  p.appendChild(document.createTextNode(content));
  $("log").appendChild(p);
  $("log").scrollTop = $("log").scrollHeight;
}

function ask(msg) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, (resp) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
      } else {
        resolve(resp || { ok: false, error: "no response" });
      }
    });
  });
}

const TERMINAL = ["done", "failed", "cancelled", "blocked", "error"];

async function poll() {
  if (goalId === null || polling) return;
  // A slow round-trip must not let the next interval tick start a second,
  // concurrent poll: both would read the same sinceId and append the same
  // events twice. Serialize ticks with an in-flight guard.
  polling = true;
  try {
    const resp = await ask({ type: "events", goalId: goalId, since: sinceId });
    if (!resp.ok) {
      setStatus(resp.error, true);
      return; // transient: keep the timer running and retry
    }
    const data = resp.data;
    for (const e of data.events || []) {
      sinceId = Math.max(sinceId, e.id);
      appendEvent(e.agent || "agent", e.content || "");
    }
    setStatus("goal #" + goalId + " — " + data.status);
    if (TERMINAL.indexOf(data.status) !== -1) {
      if (data.result) appendEvent("result", data.result);
      clearInterval(pollTimer);
      pollTimer = null;
    }
  } finally {
    polling = false;
  }
}

async function startGoal(title, description) {
  setStatus("starting…");
  const resp = await ask({ type: "chat", title: title, description: description });
  if (!resp.ok) {
    setStatus(resp.error, true);
    return;
  }
  goalId = resp.goal.id;
  sinceId = 0;
  $("log").textContent = "";
  appendEvent("you", title);
  setStatus("goal #" + goalId + " — " + resp.goal.status);
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(poll, 2000);
}

async function sendChat() {
  const text = $("prompt").value.trim();
  if (!text) return;
  // First line becomes the goal title; the full text is the brief.
  const title = text.split("\n", 1)[0].slice(0, 200);
  await startGoal(title, text);
}

// Render the bounded, observe-only accessibility/DOM snapshot the content
// script returns into compact lines for the goal brief. Read-only formatting:
// the structured context is already capped by content.js; we keep it tight.
function renderStructured(structured) {
  if (!structured) return "";
  let out = "\n\n--- structured page context (observe-only) ---";
  if (structured.lang) out += "\nlang: " + structured.lang;
  const c = structured.counts || {};
  out += "\ncounts: " + (c.elements || 0) + " interactive, " + (c.landmarks || 0) + " landmarks";
  if (structured.truncated) out += " (truncated)";
  const landmarks = structured.landmarks || [];
  if (landmarks.length) {
    out += "\nlandmarks/headings:";
    for (const l of landmarks) {
      out += "\n  - " + l.tag + (l.role && l.role !== l.tag ? " [" + l.role + "]" : "") +
             (l.name ? ": " + l.name : "");
    }
  }
  const elements = structured.elements || [];
  if (elements.length) {
    out += "\ninteractive elements:";
    for (const e of elements) {
      let line = "\n  - " + (e.role || e.tag);
      if (e.name) line += ' "' + e.name + '"';
      if (e.type) line += " type=" + e.type;
      if (e.value) line += " value=" + JSON.stringify(e.value);
      if (e.disabled) line += " (disabled)";
      if (e.selector) line += "  @ " + e.selector;
      out += line;
    }
  }
  return out;
}

// "Send this page": ask the content script for {title, url, selection,
// structured} and ship it as goal context alongside whatever is in the chat
// box. Same user-triggered, localhost-only, bearer-gated path as before.
async function sendPage() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs && tabs[0];
  if (!tab || tab.id === undefined) {
    setStatus("no active tab", true);
    return;
  }
  chrome.tabs.sendMessage(tab.id, { type: "getPageContext" }, async (ctx) => {
    if (chrome.runtime.lastError || !ctx) {
      setStatus("cannot read this page (browser-internal pages are off limits)", true);
      return;
    }
    const ask_ = $("prompt").value.trim();
    const title = (ask_ ? ask_.split("\n", 1)[0] : "Look at page: " + ctx.title).slice(0, 200);
    let description = (ask_ || "Review this page.") + "\n\n--- page context ---";
    description += "\ntitle: " + ctx.title + "\nurl: " + ctx.url;
    if (ctx.selection) description += "\nselection:\n" + ctx.selection;
    description += renderStructured(ctx.structured);
    await startGoal(title, description);
  });
}

async function loadSettings() {
  const s = await chrome.storage.local.get({ base: "http://127.0.0.1:8765", token: "" });
  $("base").value = s.base;
  $("token").value = s.token;
}

async function saveSettings() {
  let base = $("base").value.trim() || "http://127.0.0.1:8765";
  // Local-only by policy AND by manifest: host_permissions stop anything
  // beyond 127.0.0.1, so refuse other hosts here with a clear message.
  if (!/^http:\/\/127\.0\.0\.1(:\d+)?$/.test(base.replace(/\/+$/, ""))) {
    setStatus("dashboard URL must be http://127.0.0.1[:port]", true);
    return;
  }
  base = base.replace(/\/+$/, "");
  await chrome.storage.local.set({ base: base, token: $("token").value.trim() });
  setStatus("settings saved");
}

document.addEventListener("DOMContentLoaded", () => {
  loadSettings();
  $("send").addEventListener("click", sendChat);
  $("send-page").addEventListener("click", sendPage);
  $("save").addEventListener("click", saveSettings);
  $("prompt").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) sendChat();
  });
});
