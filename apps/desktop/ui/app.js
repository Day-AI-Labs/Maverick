// Splash controller for the Maverick desktop shell.
//
// The Rust side (src/lib.rs) starts `maverick dashboard` on 127.0.0.1:8765 if
// nothing is listening; this page waits for it and navigates in.
//
// IMPORTANT — why `mode: "no-cors"`: this page's origin is the Tauri webview
// (tauri://localhost / http://tauri.localhost), so a request to the dashboard
// at http://127.0.0.1:8765 is cross-origin. The dashboard emits no CORS header
// for this origin, so a normal `fetch` is blocked and REJECTS — which made the
// old splash poll forever and never connect. A `no-cors` probe instead RESOLVES
// (opaque) the moment the server answers and only rejects on a refused
// connection, which is exactly the signal we want. Top-level navigation
// (location.replace) is not subject to CORS, so once we know the port answers
// we just go there.

(function () {
  "use strict";

  var PORT = 8765; // canonical dashboard port (maverick dashboard default)
  var DASH = "http://127.0.0.1:" + PORT;
  var FAST_MS = 600; // poll interval while we expect a quick startup
  var SLOW_MS = 2000; // poll interval after we've shown the trouble card
  var TROUBLE_AFTER = 9; // ~6s of fast polls before surfacing help

  var statusText = document.getElementById("status-text");
  var trouble = document.getElementById("trouble");
  var tries = 0;
  var connected = false;

  function setStatus(msg) {
    if (statusText) statusText.textContent = msg;
  }

  function connect() {
    if (connected) return;
    connected = true;
    setStatus("Connected — loading…");
    window.location.replace(DASH + "/");
  }

  function probe() {
    if (connected) return;
    tries += 1;

    if (tries === 1) setStatus("Starting the Maverick engine…");
    else if (tries < TROUBLE_AFTER) setStatus("Waiting for the dashboard…");

    fetch(DASH + "/healthz", { mode: "no-cors", cache: "no-store" })
      .then(function () {
        connect();
      })
      .catch(function () {
        if (tries >= TROUBLE_AFTER) {
          showTrouble();
          // Keep trying slowly so it auto-recovers if the user starts it.
          setTimeout(probe, SLOW_MS);
        } else {
          setTimeout(probe, FAST_MS);
        }
      });
  }

  function showTrouble() {
    if (trouble) trouble.style.display = "block";
    setStatus("Still waiting for the dashboard…");
  }

  // --- trouble-card controls ---
  var retry = document.getElementById("retry");
  if (retry) {
    retry.addEventListener("click", function () {
      if (trouble) trouble.style.display = "none";
      tries = 0;
      setStatus("Retrying…");
      probe();
    });
  }

  var copy = document.getElementById("copy");
  var copied = document.getElementById("copied");
  if (copy) {
    copy.addEventListener("click", function () {
      var cmd = "maverick dashboard";
      var flash = function () {
        if (!copied) return;
        copied.style.opacity = "1";
        setTimeout(function () { copied.style.opacity = "0"; }, 1400);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(cmd).then(flash, fallbackCopy);
      } else {
        fallbackCopy();
      }
      function fallbackCopy() {
        var ta = document.createElement("textarea");
        ta.value = cmd;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); flash(); } catch (e) { /* no-op */ }
        document.body.removeChild(ta);
      }
    });
  }

  probe();
})();
