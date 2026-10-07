// Exécuté dans les pages fnac.com : note les appels que la page fait elle-même vers
// fnac.com au sujet des magasins et du stock (ex. le panneau « Retirer en magasin »),
// pour savoir comment la Fnac obtient la disponibilité magasin par magasin.
// Rien n'est envoyé ailleurs : les relevés restent dans l'extension.
(() => {
  const RELEVANT = /store|shop|magasin|stock|availab|dispo|retrait|collect|pickup/i;
  const same = (u) => { try { return new URL(u, location.href).origin === location.origin; } catch (e) { return false; } };
  const send = (method, url, body, status, text) => {
    if (!same(url) || /\.(js|css|png|jpe?g|webp|svg|woff2?)(\?|$)/i.test(url)) return;
    if (!RELEVANT.test(url) && !RELEVANT.test((text || "").slice(0, 4000))) return;
    window.postMessage({ __pokewatchCapture: {
      at: new Date().toISOString(), page: location.pathname, method, url: String(url),
      body: typeof body === "string" ? body.slice(0, 1500)
        : body instanceof URLSearchParams ? body.toString()
        : body instanceof FormData ? "FormData " + JSON.stringify([...body.entries()].map(([k, v]) => [k, String(v)]))
        : body ? "(non texte)" : "",
      status, response: (text || "").slice(0, 6000),
    } }, location.origin);
  };
  const origFetch = window.fetch;
  window.fetch = async function (input, init) {
    const res = await origFetch.apply(this, arguments);
    try {
      const url = typeof input === "string" ? input : input.url;
      const method = (init && init.method) || (input && input.method) || "GET";
      res.clone().text().then((t) => send(method, url, init && init.body, res.status, t), () => {});
    } catch (e) { /* jamais gênant pour la page */ }
    return res;
  };
  const open = XMLHttpRequest.prototype.open;
  const sendX = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) { this.__pw = { method, url }; return open.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (body) {
    this.addEventListener("load", () => {
      try {
        const t = this.responseType === "" || this.responseType === "text" ? this.responseText
          : this.responseType === "json" ? JSON.stringify(this.response) : "";
        send(this.__pw.method, this.__pw.url, body, this.status, t);
      } catch (e) { /* idem */ }
    });
    return sendX.apply(this, arguments);
  };
})();
