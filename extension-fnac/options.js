const $ = (id) => document.getElementById(id);
const out = (t) => { $("out").textContent = Array.isArray(t) ? t.join("\n") : String(t); };
const clean = (u) => u.trim().replace(/[?#].*$/, ""); // retire ?oref=… et autres traceurs

chrome.storage.local.get(["webhook", "products", "intervalMinutes", "state"]).then(async (s) => {
  $("webhook").value = s.webhook || "";
  const defaults = (await chrome.runtime.sendMessage("defaults")) || [];
  $("products").value = (s.products || defaults).join("\n");
  $("interval").value = s.intervalMinutes || 3;
  const when = (iso) => (iso ? new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : "?");
  const st = Object.entries(s.state || {}).map(([u, v]) =>
    `${v.name || u}  (relevé à ${when(v.at)})\n   en ligne : ${v.web || `${v.status || "?"} (${v.source || "bloc d'achat introuvable"})`}\n   ${v.storeName || "magasin"} : ${v.storeText || "—"}` +
    (v.error ? `\n   ⚠ dernière lecture : ${v.error}` : "") +
    (v.diag && !v.diag.blocAchat
      ? `\n   🔎 diagnostic : page « ${v.diag.titre} », ${v.diag.reperes} repères, offres : ` +
        (v.diag.offres.map((o) => `${o.seller || "?"} ${o.price || ""}€ ${o.availability}`).join(" ; ") || "aucune")
      : ""));
  out(st.length ? ["Derniers relevés :", ...st] : "Pas encore de relevé : cliquez sur « Vérifier maintenant ».");
});

$("save").onclick = async () => {
  const products = $("products").value.split("\n").map(clean).filter((u) => u.startsWith("https://www.fnac.com/"));
  await chrome.storage.local.set({ webhook: $("webhook").value.trim(), products, intervalMinutes: Number($("interval").value) || 3 });
  await chrome.runtime.sendMessage("reschedule");
  $("products").value = products.join("\n");
  out(`Enregistré : ${products.length} fiche(s).`);
};
$("test").onclick = async () => out(await chrome.runtime.sendMessage("test-discord"));
$("now").onclick = async () => { out("Vérification en cours (quelques secondes par fiche)…"); out(await chrome.runtime.sendMessage("check-now")); };

chrome.storage.local.get("captures").then(({ captures }) => {
  if (!captures || !captures.length) return;
  $("capbox").hidden = false;
  $("cap").textContent = captures.map((c) =>
    `[${c.at}] ${c.method} ${c.url}  (page ${c.page}, réponse ${c.status})` +
    (c.body ? `\n  envoyé : ${c.body}` : "") + `\n  reçu : ${c.response.replace(/\s+/g, " ")}`).join("\n\n");
});
$("copycap").onclick = async () => { await navigator.clipboard.writeText($("cap").textContent); $("copycap").textContent = "Copié ✓"; };
$("clearcap").onclick = async () => { await chrome.storage.local.remove("captures"); $("capbox").hidden = true; };
