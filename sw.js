// Service worker minimal : affiche les notifications de l'appli (alerte de descente, correspondance)
// et, depuis #20, celles du service d'alertes envoyées appli fermée. Aucune mise en cache.
// #40 : quand une notification du service arrive (puis quand elle est touchée), on le signale au
// service pour compter combien de téléphones l'ont vraiment reçue.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

const SRV = { url: null, at: 0 };
async function srvUrl() {
  if (SRV.url && Date.now() - SRV.at < 6 * 3600e3) return SRV.url;
  try {
    const r = await fetch("notifs.json?v=" + Math.floor(Date.now() / 36e5));
    if (r.ok) { const j = await r.json(); if (j && j.url) { SRV.url = j.url.replace(/\/+$/, ""); SRV.at = Date.now(); return SRV.url; } }
  } catch (err) {}
  return null;
}
// d = { n: numéro d'envoi, i: identifiant du téléphone, k: jeton } ajoutés par le service
async function signal(path, d) {
  if (!d || !d.n || !d.i || !d.k) return;
  const u = await srvUrl(); if (!u) return;
  try {
    await fetch(u + path, { method: "POST", headers: { "Content-Type": "text/plain" }, body: JSON.stringify({ n: d.n, i: d.i, k: d.k }) });
  } catch (err) {}
}

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil((async () => {
    // sur iPhone, « tag » ne remplace pas toujours l'ancienne notification : on la ferme d'abord
    if (d.tag) { try { (await self.registration.getNotifications({ tag: d.tag })).forEach((n) => n.close()); } catch (err) {} }
    await self.registration.showNotification(d.title || "Horaires", { body: d.body || "", tag: d.tag || undefined, icon: "icon-192.png", badge: "icon-192.png", data: { url: d.url || "./", n: d.n, i: d.i, k: d.k } });
    await signal("/recu", d); // après l'affichage : le réseau ne doit pas retarder la notification
  })());
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const data = e.notification.data || {};
  const url = data.url || null;
  const open = self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => {
    for (const c of cs) { if ("focus" in c) { if (url) c.postMessage({ type: "open", url }); return c.focus(); } }
    return self.clients.openWindow(url || "./#suivi");
  });
  e.waitUntil(Promise.all([open, signal("/vu", data)]));
});
