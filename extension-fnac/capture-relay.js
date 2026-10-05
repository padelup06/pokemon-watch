// Relais : range dans l'extension les appels notés par capture-main.js (15 derniers).
window.addEventListener("message", (ev) => {
  if (ev.source !== window || !ev.data || !ev.data.__pokewatchCapture) return;
  chrome.storage.local.get("captures").then(({ captures }) => {
    const list = (captures || []).concat([ev.data.__pokewatchCapture]).slice(-15);
    return chrome.storage.local.set({ captures: list });
  }).catch(() => {});
});
