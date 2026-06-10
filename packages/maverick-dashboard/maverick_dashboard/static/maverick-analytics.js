/* <maverick-analytics> — embeddable Maverick analytics web component.
 *
 * Self-contained (Web Components API, no framework, no dependencies).
 * Renders total spend, an episode-cost sparkline, and a goals-by-status bar
 * chart from the dashboard's existing read endpoints:
 *
 *   GET <endpoint>/api/v1/spend
 *   GET <endpoint>/api/v1/goals?limit=100
 *
 * Attributes:
 *   endpoint  Dashboard base URL (default: "" = the page's own origin).
 *   token     Optional bearer, sent as "Authorization: Bearer <token>".
 *
 * HONEST LIMITS — read before embedding anywhere but the dashboard itself:
 *   - Same-origin: the dashboard sends NO CORS headers, so fetches from a
 *     page on another origin are blocked by the browser. Embed on a page the
 *     dashboard serves (see /embed-demo) or behind the same reverse proxy.
 *   - Token exposure: anyone who can read the embedding page's HTML can read
 *     the token and gains full dashboard API access with it. Only embed on
 *     pages whose audience you would trust with the dashboard itself.
 *   - No-token loopback mode needs no token attribute at all.
 */
(function () {
  "use strict";
  if (typeof customElements === "undefined" || customElements.get("maverick-analytics")) return;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // Hand-drawn inline-SVG sparkline (polyline over min..max).
  function sparklineSVG(values, w, h, stroke) {
    if (!values.length) return '<span class="muted">no data</span>';
    const lo = Math.min(...values), hi = Math.max(...values);
    const span = (hi - lo) || 1, n = values.length, pad = 2;
    const pts = values.map((v, i) => {
      const x = pad + (w - 2 * pad) * (n > 1 ? i / (n - 1) : 0.5);
      const y = pad + (h - 2 * pad) * (1 - (v - lo) / span);
      return x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
    return '<svg width="' + w + '" height="' + h + '" role="img" aria-label="sparkline of ' +
      n + ' values from ' + lo.toFixed(4) + " to " + hi.toFixed(4) + '">' +
      '<polyline points="' + pts + '" fill="none" stroke="' + stroke + '" stroke-width="1.5"/></svg>';
  }

  // Hand-drawn horizontal bar chart for {label: count}.
  function barsSVG(counts, w, color, textColor) {
    const labels = Object.keys(counts).sort();
    if (!labels.length) return '<span class="muted">no goals</span>';
    const max = Math.max(...labels.map((k) => counts[k])) || 1;
    const rowH = 18;
    const rows = labels.map((k, i) => {
      const bw = Math.max(2, (w - 110) * (counts[k] / max));
      const y = i * rowH;
      return '<text x="0" y="' + (y + 12) + '" font-size="10" fill="' + textColor + '">' + esc(k) + "</text>" +
        '<rect x="70" y="' + (y + 3) + '" width="' + bw.toFixed(1) + '" height="10" rx="2" fill="' + color + '"></rect>' +
        '<text x="' + (74 + bw).toFixed(1) + '" y="' + (y + 12) + '" font-size="10" fill="' + textColor + '">' + counts[k] + "</text>";
    }).join("");
    return '<svg width="' + w + '" height="' + (labels.length * rowH) + '" role="img" aria-label="goals by status: ' +
      labels.map((k) => k + " " + counts[k]).join(", ") + '">' + rows + "</svg>";
  }

  class MaverickAnalytics extends HTMLElement {
    connectedCallback() {
      const root = this.attachShadow({ mode: "open" });
      root.innerHTML =
        "<style>" +
        ":host { display: block; font: 13px/1.5 -apple-system, 'Segoe UI', Roboto, sans-serif; " +
        "color: #e6edf3; background: #161b22; border: 1px solid #30363d; border-radius: 8px; " +
        "padding: 1rem; max-width: 420px; }" +
        "h2 { margin: 0 0 0.5rem; font-size: 0.75rem; text-transform: uppercase; " +
        "letter-spacing: 0.08em; color: #9aa3ad; }" +
        ".num { font-size: 1.6rem; font-weight: 600; }" +
        ".muted { color: #9aa3ad; }" +
        "section { margin-bottom: 0.9rem; }" +
        ".err { color: #f85149; }" +
        "</style>" +
        '<section><h2>Total spend</h2><div id="spend" class="muted">loading…</div></section>' +
        '<section><h2>Episode cost trend</h2><div id="trend" class="muted">loading…</div></section>' +
        '<section style="margin-bottom:0"><h2>Goals by status</h2><div id="goals" class="muted">loading…</div></section>';
      this._load(root);
    }

    _fetch(path) {
      const base = (this.getAttribute("endpoint") || "").replace(/\/+$/, "");
      const headers = { Accept: "application/json" };
      const token = this.getAttribute("token");
      if (token) headers.Authorization = "Bearer " + token;
      return fetch(base + path, { headers }).then((r) => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
    }

    _load(root) {
      const put = (id, html, isErr) => {
        const el = root.getElementById(id);
        el.innerHTML = html;
        el.className = isErr ? "err" : "";
      };
      this._fetch("/api/v1/spend").then((data) => {
        const total = data.total || {};
        put("spend", "$" + Number(total.dollars || 0).toFixed(4) +
          ' <span class="muted">(' + (Number(total.runs) || 0) + " episodes)</span>");
        const costs = (data.episodes || [])
          .map((e) => Number(e.cost_dollars || 0))
          .reverse(); // API returns newest first; plot oldest -> newest
        put("trend", sparklineSVG(costs, 360, 42, "#3fb950"));
      }).catch((e) => {
        put("spend", "spend: " + esc(e.message), true);
        put("trend", "trend: " + esc(e.message), true);
      });
      this._fetch("/api/v1/goals?limit=100").then((goals) => {
        const counts = {};
        (goals || []).forEach((g) => {
          const s = g.status || "unknown";
          counts[s] = (counts[s] || 0) + 1;
        });
        put("goals", barsSVG(counts, 360, "#3fb950", "#9aa3ad"));
      }).catch((e) => {
        put("goals", "goals: " + esc(e.message), true);
      });
    }
  }

  customElements.define("maverick-analytics", MaverickAnalytics);
})();
