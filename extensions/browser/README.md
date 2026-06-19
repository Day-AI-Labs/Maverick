# Lightwork browser extension

A Manifest V3 WebExtension that puts a chat box to your **local** Lightwork
agent in the browser toolbar, plus a "Send this page" action that ships the
current page's title, URL, and text selection to the agent as goal context.

Plain JavaScript, no build step, no remote code. It reuses the dashboard's
existing REST API — `POST /api/v1/goals` to start a goal (the same start
path the dashboard chat uses) and `GET /api/v1/goals/{id}/events` to stream
progress back into the popup.

## Install (load unpacked)

1. Start the dashboard locally: `maverick dashboard` (default
   `http://127.0.0.1:8765`).
2. Set `MAVERICK_DASHBOARD_TOKEN` when starting the dashboard, then opt the
   server in to extension calls (fail-closed default — see "Security model"):
   add to `~/.maverick/config.toml`

   ```toml
   [dashboard]
   allow_extension = true
   ```

   or start the dashboard with `MAVERICK_DASHBOARD_ALLOW_EXTENSION=1`.
3. Chrome / Edge / Brave: open `chrome://extensions`, enable **Developer
   mode**, click **Load unpacked**, and pick this directory
   (`extensions/browser/`).
   Firefox: open `about:debugging#/runtime/this-firefox`, click **Load
   Temporary Add-on…**, and pick `manifest.json`.
4. Click the Lightwork toolbar icon and paste `MAVERICK_DASHBOARD_TOKEN` under
   **Settings** in the popup.

## Use

- **Chat**: type a goal, press **Send** (or Ctrl/Cmd-Enter). The popup polls
  the goal's event feed and renders progress + the final result.
- **Send this page**: ships the active tab's title, URL, and any selected
  text as goal context, together with whatever you typed in the chat box.

## Security model

- **Local only.** `host_permissions` is `http://127.0.0.1/*` — the extension
  *cannot* talk to any other host, and the popup refuses non-loopback
  dashboard URLs. Nothing ever leaves your machine.
- **Opt-in CORS, fail-closed.** The dashboard answers extension origins
  (`chrome-extension://…`, `moz-extension://…`) only when the operator sets
  `[dashboard] allow_extension = true` (or
  `MAVERICK_DASHBOARD_ALLOW_EXTENSION=1`). Off by default: no CORS header is
  emitted and extension POSTs are rejected by the dashboard's cross-site
  gate. The allowance is scoped to extension origins — ordinary web origins
  (`https://…`) are never allowed. Extension CORS is only enabled when
  `MAVERICK_DASHBOARD_TOKEN` is also set, so no-token loopback mode stays
  same-origin only.
- **Token.** Every extension call must carry `Authorization: Bearer <token>`;
  the popup stores the token in `chrome.storage.local` (extension-private, on
  disk, this machine). Without a token the dashboard serves loopback callers
  only and does not grant extension CORS or CSRF bypasses.
- **Inert content script.** `content.js` collects nothing on its own and
  makes no network calls; it only answers an explicit `getPageContext`
  message triggered by your click on "Send this page".
- **No remote code.** All scripts are local files; the extension-page CSP is
  `script-src 'self'`. CI parses `manifest.json` and statically checks these
  invariants (`packages/maverick-dashboard/tests/test_extension_static.py`).
