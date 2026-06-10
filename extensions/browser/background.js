// Maverick browser extension — background service worker (Manifest V3).
//
// All network I/O lives here so a request survives the popup closing and the
// popup stays a thin UI. Every fetch goes to the LOCAL Maverick dashboard
// (http://127.0.0.1:<port> — see host_permissions in manifest.json; no other
// host is reachable) and reuses the dashboard's existing REST API:
//
//   POST /api/v1/goals                   start a goal (the chat/start API)
//   GET  /api/v1/goals/{id}/events       poll a goal's event feed
//
// When a dashboard token is configured (Options in the popup), it is sent as
// the same `Authorization: Bearer` header the dashboard's other API clients
// use. Plain JS, no build step, no remote code.

const DEFAULTS = { base: "http://127.0.0.1:8765", token: "" };

async function settings() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  return Object.assign({}, DEFAULTS, stored);
}

function headersFor(s, isJson) {
  const h = {};
  if (isJson) h["Content-Type"] = "application/json";
  if (s.token) h["Authorization"] = "Bearer " + s.token;
  return h;
}

// Start a goal on the local dashboard. Title/description map onto the same
// fields the dashboard chat page submits; the server enforces its own caps.
async function startGoal(title, description) {
  const s = await settings();
  const resp = await fetch(s.base + "/api/v1/goals", {
    method: "POST",
    headers: headersFor(s, true),
    body: JSON.stringify({
      title: String(title || "").slice(0, 200),
      description: String(description || ""),
    }),
  });
  if (!resp.ok) {
    const detail = (await resp.text()).slice(0, 300);
    throw new Error("dashboard replied " + resp.status + ": " + detail);
  }
  return resp.json();
}

// Poll a goal's events (incremental: pass the last seen event id as `since`).
async function goalEvents(goalId, since) {
  const s = await settings();
  const url =
    s.base +
    "/api/v1/goals/" +
    encodeURIComponent(goalId) +
    "/events?since=" +
    encodeURIComponent(since || 0);
  const resp = await fetch(url, { headers: headersFor(s, false) });
  if (!resp.ok) throw new Error("dashboard replied " + resp.status);
  return resp.json();
}

// Message router for the popup. `sendResponse` is kept open (return true)
// while the async work runs; every branch answers {ok, ...} so the popup
// never hangs on an exception.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg && msg.type === "chat") {
        sendResponse({ ok: true, goal: await startGoal(msg.title, msg.description) });
      } else if (msg && msg.type === "events") {
        sendResponse({ ok: true, data: await goalEvents(msg.goalId, msg.since) });
      } else {
        sendResponse({ ok: false, error: "unknown message type" });
      }
    } catch (e) {
      sendResponse({ ok: false, error: String((e && e.message) || e) });
    }
  })();
  return true;
});
