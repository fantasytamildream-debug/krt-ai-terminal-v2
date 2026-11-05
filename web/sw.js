/* 📲 KRT Terminal — push notifications (tab மூடியிருந்தாலும்) */
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { title: "KRT", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "KRT Terminal", {
    body: d.body || "", tag: d.tag || undefined, renotify: true, requireInteraction: !!d.urgent,
    vibrate: d.urgent ? [300, 120, 300, 120, 500] : [200, 100, 200], data: { url: d.url || "/" },
    badge: "/icon.svg", icon: "/icon.svg"
  }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(L => {
    for (const c of L) { if ("focus" in c) return c.focus(); }
    return self.clients.openWindow((e.notification.data || {}).url || "/");
  }));
});
