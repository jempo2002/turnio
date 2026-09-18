/* Turnia — tema y utilidades compartidas.
   En el navegador: cargar SIEMPRE justo después del CDN de Tailwind.
   En Node: se puede requerir para probar las fórmulas (ver test-calculo.js). */

(function () {
  'use strict';

  /* ══════════ Lógica pura (probada en test-calculo.js) ══════════ */

  /* Moneda colombiana: sin decimales. */
  function pesos(n) {
    return '$' + Math.round(n).toLocaleString('es-CO');
  }

  /* Precio de venta a partir del costo y el % de ganancia deseado.
     Se redondea a $100: es la moneda más pequeña que se maneja en el cajón. */
  function precioVenta(compra, pct) {
    if (!(compra > 0) || isNaN(pct)) return 0;
    return Math.round(compra * (1 + pct / 100) / 100) * 100;
  }

  /* Camino inverso: si el barbero escribe el precio de venta a mano,
     se recalcula el % de ganancia que ese precio representa. */
  function pctGanancia(compra, venta) {
    if (!(compra > 0)) return 0;
    return Math.round((venta - compra) / compra * 100);
  }

  var api = { pesos: pesos, precioVenta: precioVenta, pctGanancia: pctGanancia };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window === 'undefined') return;   /* Node: hasta aquí */

  /* ══════════ Sólo navegador ══════════ */

  window.pesos = pesos;
  window.precioVenta = precioVenta;
  window.pctGanancia = pctGanancia;

  /* Feedback breve en un botón sin perder su etiqueta original (Nielsen #1). */
  window.avisar = function (el, texto, ms) {
    if (el.dataset.original === undefined) el.dataset.original = el.textContent;
    el.textContent = texto;
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.textContent = el.dataset.original; }, ms || 2000);
  };

  window.tailwind = window.tailwind || {};
  window.tailwind.config = {
    theme: {
      extend: {
        colors: {
          brand: {
            lightest: '#C7EBF6',
            light:    '#9BD1DB',
            DEFAULT:  '#54C2DD',
            dark:     '#238AA6',
            darkest:  '#244D6A'
          }
        },
        fontFamily: {
          sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Inter', 'Helvetica Neue', 'Arial', 'sans-serif']
        },
        boxShadow: {
          soft: '0 1px 2px rgba(36,77,106,.06), 0 8px 24px -14px rgba(36,77,106,.35)',
          lift: '0 2px 4px rgba(36,77,106,.08), 0 20px 40px -16px rgba(36,77,106,.45)'
        }
      }
    }
  };

  /* CSS plano: no necesita pasar por Tailwind, así que un <style> normal basta. */
  var css = [
    ':focus-visible{outline:2px solid #238AA6;outline-offset:2px;border-radius:8px}',
    'html{background:#C7EBF6}',
    /* <dialog> nativo: backdrop, cierre con ESC y foco atrapado los pone el navegador */
    'dialog::backdrop{background:rgba(36,77,106,.5);backdrop-filter:blur(3px)}',
    'dialog[open]{animation:sheet-up .3s cubic-bezier(.32,.72,0,1)}',
    '@keyframes sheet-up{from{transform:translateY(100%)}}',
    '@media (prefers-reduced-motion:reduce){dialog[open]{animation:none}}',
    /* Rojo de validación sólo tras el primer intento de envío, no mientras se escribe */
    'form.enviado input:invalid,form.enviado select:invalid{border-color:#dc2626}'
  ].join('\n');

  var s = document.createElement('style');
  s.textContent = css;
  document.head.appendChild(s);
})();
