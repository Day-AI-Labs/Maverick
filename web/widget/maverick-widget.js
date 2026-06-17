/*
 * Maverick embeddable widget (roadmap: 2028 H1 distribution — "embeddable widget").
 *
 * A dependency-free floating chat button that drops onto any page and talks to
 * a Maverick dashboard's chat endpoint. Self-hostable: it posts to YOUR
 * dashboard origin, not a hosted service.
 *
 * Usage:
 *   <script src="/widget/maverick-widget.js"
 *           data-maverick-url="https://your-dashboard.example.com"
 *           data-maverick-title="Ask Maverick"></script>
 *
 * The dashboard must allow the embedding origin (CORS / same-origin policy).
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var BASE = (script && script.getAttribute("data-maverick-url")) || "";
  var TITLE = (script && script.getAttribute("data-maverick-title")) || "Maverick";
  BASE = BASE.replace(/\/+$/, "");

  function el(tag, props, css) {
    var n = document.createElement(tag);
    if (props) Object.keys(props).forEach(function (k) {
      // Hyphenated keys (e.g. "aria-label") are attributes, not IDL
      // properties: assigning n["aria-label"] creates a dead expando and the
      // attribute is never set. Route those through setAttribute.
      if (k.indexOf("-") !== -1) { n.setAttribute(k, props[k]); }
      else { n[k] = props[k]; }
    });
    if (css) Object.keys(css).forEach(function (k) { n.style[k] = css[k]; });
    return n;
  }

  var panel = el("div", null, {
    position: "fixed", bottom: "84px", right: "20px", width: "320px",
    maxHeight: "60vh", display: "none", flexDirection: "column",
    background: "#fff", border: "1px solid #ddd", borderRadius: "12px",
    boxShadow: "0 8px 30px rgba(0,0,0,.18)", overflow: "hidden",
    font: "14px/1.4 system-ui, sans-serif", zIndex: 2147483647
  });

  var header = el("div", { textContent: TITLE }, {
    padding: "10px 14px", fontWeight: "600", background: "#111", color: "#fff"
  });
  var log = el("div", null, {
    flex: "1", padding: "12px", overflowY: "auto", color: "#111"
  });
  var form = el("form", null, { display: "flex", borderTop: "1px solid #eee" });
  var input = el("input", {
    type: "text", placeholder: "Type a goal…", required: true
  }, { flex: "1", border: "0", padding: "12px", outline: "none" });
  var send = el("button", { type: "submit", textContent: "Send" }, {
    border: "0", background: "#111", color: "#fff", padding: "0 16px",
    cursor: "pointer"
  });
  form.appendChild(input); form.appendChild(send);
  panel.appendChild(header); panel.appendChild(log); panel.appendChild(form);

  var fab = el("button", { textContent: "💬", "aria-label": TITLE }, {
    position: "fixed", bottom: "20px", right: "20px", width: "52px",
    height: "52px", borderRadius: "50%", border: "0", background: "#111",
    color: "#fff", fontSize: "22px", cursor: "pointer",
    boxShadow: "0 6px 20px rgba(0,0,0,.25)", zIndex: 2147483647
  });

  function line(who, text) {
    var row = el("div", null, { margin: "6px 0" });
    row.appendChild(el("b", { textContent: who + ": " }));
    row.appendChild(document.createTextNode(text));
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
  }

  fab.addEventListener("click", function () {
    var open = panel.style.display === "flex";
    panel.style.display = open ? "none" : "flex";
    if (!open) input.focus();
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var msg = input.value.trim();
    if (!msg) return;
    line("You", msg);
    input.value = "";
    send.disabled = true;
    fetch(BASE + "/chat/send", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: "message=" + encodeURIComponent(msg),
      credentials: "include"
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        line("Maverick", (data && (data.reply || data.result)) || "Started.");
      })
      .catch(function (err) { line("Maverick", "Error: " + err); })
      .finally(function () { send.disabled = false; });
  });

  document.body.appendChild(panel);
  document.body.appendChild(fab);
})();
