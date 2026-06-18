/* Lightwork site — demo-request modal.
   Opens from every "Book a demo" / "Request access" CTA on every page.
   Delivery: set ACCESS_KEY to a free Web3Forms key to send submissions
   straight to info@daybreakailabs.com. Until then it falls back to a
   pre-filled email so the form is never a dead end. */
(function () {
  "use strict";
  var ACCESS_KEY = ""; // <-- paste the Web3Forms access key here to enable direct-to-inbox delivery

  var modal = document.createElement("div");
  modal.className = "modal";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-label", "Book a demo");
  modal.innerHTML =
    '<div class="modal-card">' +
      '<button class="modal-close" aria-label="Close">&times;</button>' +
      '<h3>Book a demo</h3>' +
      '<p class="sub">Tell us a little about your work and we&rsquo;ll set up a short call on one real workflow.</p>' +
      '<form id="demo-form" novalidate>' +
        '<div class="field"><label for="df-name">Name</label><input id="df-name" name="name" required autocomplete="name"></div>' +
        '<div class="field"><label for="df-email">Work email</label><input id="df-email" type="email" name="email" required autocomplete="email"></div>' +
        '<div class="field"><label for="df-company">Company</label><input id="df-company" name="company" autocomplete="organization"></div>' +
        '<div class="field"><label for="df-msg">What would you want to put under governance?</label><textarea id="df-msg" name="message" rows="3"></textarea></div>' +
        '<input type="checkbox" name="botcheck" class="hp" tabindex="-1" autocomplete="off" aria-hidden="true">' +
        '<button type="submit" class="btn btn-primary df-submit">Request a demo</button>' +
        '<p class="df-foot">We read every request and reply personally.</p>' +
      '</form>' +
      '<div class="modal-done" hidden>' +
        '<h3>Thanks &mdash; we&rsquo;ll be in touch.</h3>' +
        '<p class="sub">Your request is in. We&rsquo;ll reply from info@daybreakailabs.com.</p>' +
        '<button class="btn btn-ghost modal-close2" style="margin-top:18px">Close</button>' +
      '</div>' +
    "</div>";

  function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  ready(function () {
    document.body.appendChild(modal);
    var card = modal.querySelector(".modal-card");
    var form = modal.querySelector("#demo-form");
    var done = modal.querySelector(".modal-done");
    var lastFocus = null;

    function open(e) {
      if (e) e.preventDefault();
      lastFocus = document.activeElement;
      form.hidden = false; done.hidden = true;
      modal.classList.add("show");
      document.documentElement.classList.add("modal-open");
      setTimeout(function () { var i = form.querySelector("input"); if (i) i.focus(); }, 40);
    }
    function close() {
      modal.classList.remove("show");
      document.documentElement.classList.remove("modal-open");
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    modal.addEventListener("click", function (e) { if (e.target === modal) close(); });
    modal.querySelector(".modal-close").addEventListener("click", close);
    modal.querySelector(".modal-close2").addEventListener("click", close);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && modal.classList.contains("show")) close(); });

    // Rewire every demo / access CTA on the page to open the modal.
    var ctas = document.querySelectorAll(
      'a[href^="mailto:info@daybreakailabs.com?subject=Request%20a%20Lightwork%20demo"],' +
      'a[href^="mailto:info@daybreakailabs.com?subject=Lightwork%20access"],' +
      "[data-demo]"
    );
    Array.prototype.forEach.call(ctas, function (a) { a.addEventListener("click", open); });

    function mailtoFallback(d) {
      var body = "Name: " + d.name + "\nWork email: " + d.email + "\nCompany: " + d.company + "\n\n" + (d.message || "");
      return "mailto:info@daybreakailabs.com?subject=" + encodeURIComponent("Lightwork demo request") + "&body=" + encodeURIComponent(body);
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var d = {
        name: form.name.value.trim(),
        email: form.email.value.trim(),
        company: form.company.value.trim(),
        message: form.message.value.trim(),
        botcheck: form.botcheck.checked
      };
      if (d.botcheck) return;                 // honeypot tripped
      if (!d.name || !d.email) { (d.name ? form.email : form.name).focus(); return; }

      if (ACCESS_KEY) {
        var btn = form.querySelector(".df-submit");
        btn.disabled = true; btn.textContent = "Sending…";
        fetch("https://api.web3forms.com/submit", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({
            access_key: ACCESS_KEY,
            subject: "New Lightwork demo request",
            from_name: "Lightwork site",
            name: d.name, email: d.email, company: d.company, message: d.message
          })
        })
          .then(function (r) { return r.json(); })
          .then(function (j) {
            if (j && j.success) { form.hidden = true; done.hidden = false; }
            else { btn.disabled = false; btn.textContent = "Request a demo"; window.location.href = mailtoFallback(d); }
          })
          .catch(function () { btn.disabled = false; btn.textContent = "Request a demo"; window.location.href = mailtoFallback(d); });
      } else {
        window.location.href = mailtoFallback(d);
      }
    });
  });
})();
