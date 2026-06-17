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

// "Send this page": ask the content script for {title, url, selection} and
// ship it as goal context alongside whatever is in the chat box.
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
