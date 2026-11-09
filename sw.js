// Service worker minimal : affiche les notifications de l'appli (alerte de descente, correspondance)
// et, depuis #20, celles du service d'alertes envoyées appli fermée. Aucune mise en cache.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil((async () => {
    // sur iPhone, « tag » ne remplace pas toujours l'ancienne notification : on la ferme d'abord
    if (d.tag) { try { (await self.registration.getNotifications({ tag: d.tag })).forEach((n) => n.close()); } catch (err) {} }
    await self.registration.showNotification(d.title || "Horaires", { body: d.body || "", tag: d.tag || undefined, icon: "icon-192.png", badge: "icon-192.png", data: { url: d.url || "./" } });
  })());
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || null;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => {
    for (const c of cs) { if ("focus" in c) { if (url) c.postMessage({ type: "open", url }); return c.focus(); } }
    return self.clients.openWindow(url || "./#suivi");
  }));
});
