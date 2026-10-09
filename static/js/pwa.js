/* App instalable (T9): registra el service worker (/sw.js, app/routes/pwa.py)
   y maneja el aviso "Instalar Turnio" de Ajustes.

   <section data-instalar-caja hidden>            se muestra si se puede instalar
     <button data-instalar hidden>                Android/Chrome: abre el aviso del navegador
     <p data-instalar-ios hidden>                 iPhone: instrucciones (Safari no tiene aviso)
   <button data-recargar>                         pagina sin conexion: vuelve a intentar */
(function () {
  'use strict';

  if ('serviceWorker' in navigator && window.isSecureContext) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js').catch(function () { /* sin SW la app funciona igual */ });
    });
  }

  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-recargar]')) location.reload();
  });

  var instalada = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  if (instalada) return;

  function mostrar(sel) {
    var caja = document.querySelector('[data-instalar-caja]');
    var el = document.querySelector(sel);
    if (!caja || !el) return null;
    caja.hidden = false;
    el.hidden = false;
    return el;
  }

  var aviso = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    aviso = e;
    var boton = mostrar('[data-instalar]');
    if (!boton || boton.dataset.listo) return;
    boton.dataset.listo = '1';
    boton.addEventListener('click', function () {
      if (!aviso) return;
      aviso.prompt();
      aviso.userChoice.finally(function () { aviso = null; });
    });
  });
  window.addEventListener('appinstalled', function () {
    var caja = document.querySelector('[data-instalar-caja]');
    if (caja) caja.hidden = true;
  });

  if (/iphone|ipad|ipod/i.test(navigator.userAgent)) {
    document.addEventListener('DOMContentLoaded', function () { mostrar('[data-instalar-ios]'); });
    if (document.readyState !== 'loading') mostrar('[data-instalar-ios]');
  }
})();
