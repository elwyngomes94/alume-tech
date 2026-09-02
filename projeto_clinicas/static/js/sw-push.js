// Service worker minimo, isolado, so para a pagina publica da senha
// (escopo "/chamada/"). Nao faz cache/interceptacao de requisicoes -- so
// existe para poder receber "push" com a pagina em segundo plano/fechada.
self.addEventListener("install", function (event) {
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", function (event) {
  var data = { title: "Atualizacao da senha", body: "", url: "/" };
  try {
    if (event.data) data = Object.assign(data, event.data.json());
  } catch (e) { /* payload nao era JSON -- usa os valores padrao */ }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/static/img/favicon.png",
      badge: "/static/img/favicon.png",
      vibrate: [300, 100, 300, 100, 300],
      data: { url: data.url },
    })
  );
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clients) {
      for (var i = 0; i < clients.length; i++) {
        if (clients[i].url.indexOf(url) !== -1 && "focus" in clients[i]) {
          return clients[i].focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});
