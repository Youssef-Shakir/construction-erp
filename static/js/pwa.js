/* Register the service worker and show an "Install app" button when the
 * browser offers installation (Chrome/Edge/Android). iOS: Share -> Add to Home Screen. */
(function () {
  var script = document.currentScript;
  var swUrl = (script && script.dataset.sw) || '/sw.js';

  if ('serviceWorker' in navigator && window.isSecureContext) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register(swUrl, { scope: '/' }).catch(function (err) {
        console.warn('Service worker registration failed', err);
      });
    });
  }

  var deferred = null;
  var button = document.getElementById('pwa-install');
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferred = e;
    if (button) button.hidden = false;
  });
  if (button) {
    button.addEventListener('click', function () {
      if (!deferred) return;
      deferred.prompt();
      deferred.userChoice.finally(function () { deferred = null; button.hidden = true; });
    });
  }
  window.addEventListener('appinstalled', function () { if (button) button.hidden = true; });
})();
