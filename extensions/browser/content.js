// Maverick page-context capture (content script).
//
// Inert by design: it collects NOTHING on its own, makes no network calls,
// and only answers an explicit getPageContext request sent by the popup
// when the user clicks "Send this page". The reply is the page title, URL,
// and the current text selection (capped) — nothing else.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "getPageContext") {
    sendResponse({
      title: String(document.title || "").slice(0, 300),
      url: String(location.href || "").slice(0, 2000),
      selection: String(window.getSelection() || "").slice(0, 4000),
    });
  }
  // Synchronous response; the channel is not kept open.
});
