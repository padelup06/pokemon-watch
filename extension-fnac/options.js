const $ = (id) => document.getElementById(id);
const out = (t) => { $("out").textContent = Array.isArray(t) ? t.join("\n") : String(t); };
const clean = (u) => u.trim().replace(/[?#].*$/, ""); // retire ?oref=… et autres traceurs

chrome.storage.local.get(["webhook", "products", "intervalMinutes", "state"]).then((s) => {
  $("webhook").value = s.webhook || "";
  $("products").value = (s.products || ["https://www.fnac.com/Cartes-a-collectionner-Pokemon-30A-Coffret-Dresseur-d-Elite/a23200296/w-4"]).join("\n");
  $("interval").value = s.intervalMinutes || 3;
  const st = Object.entries(s.state || {}).map(([u, v]) => `${v.name || u} : ${v.status} (${v.at || ""})`);
  if (st.length) out(st);
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
