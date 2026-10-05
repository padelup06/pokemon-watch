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
    `${v.name || u}  (relevé à ${when(v.at)})\n   en ligne : ${v.web || v.status || "?"}\n   ${v.storeName || "magasin"} : ${v.storeText || "—"}` +
    (v.error ? `\n   ⚠ dernière lecture : ${v.error}` : ""));
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
