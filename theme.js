/* Turnio — tema y utilidades compartidas.
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

  /* Reparto fijo: de lo que cuesta un servicio, cuánto es del barbero.
     Nunca negativo ni mayor que el precio; lo que sobra es del local. */
  function pagoBarbero(precio, monto) {
    if (!(monto > 0)) return 0;
    return Math.min(monto, precio);
  }

  /* ── Agenda por profesional ──
     Un profesional está ocupado a una hora si tiene un turno vigente (reservado o bloqueado).
     Un turno completado ya no ocupa: al cobrar, queda libre otra vez. */
  function ocupado(citas, hora, barbero) {
    return citas.some(function (c) {
      return c.hora === hora && c.barbero === barbero && (c.estado === 'reservada' || c.estado === 'bloqueada');
    });
  }

  function horasAgenda(citas) {
    return citas.map(function (c) { return c.hora; })
      .filter(function (h, i, todas) { return todas.indexOf(h) === i; }).sort();
  }

  /* Lo único que ve el cliente final: nombre y si está libre. Nada de correo ni pagos.
     Es el mismo contrato de GET /api/public/:slug/availability. */
  function disponibilidad(citas, barberos, hora) {
    return barberos.map(function (b) {
      return { nombre: b.nombre, disponible: !ocupado(citas, hora, b.nombre) };
    });
  }

  /* Reserva hora + profesional. Devuelve la cita, o null si ya está ocupado
     o esa hora no existe en su agenda. */
  function reservar(citas, hora, barbero, d) {
    if (ocupado(citas, hora, barbero)) return null;
    var c = null, ultimo = -1;
    citas.forEach(function (x, i) {
      if (x.hora !== hora || x.barbero !== barbero) return;
      ultimo = i;
      if (x.estado === 'disponible') c = x;
    });
    if (ultimo < 0) return null;
    if (!c) {
      /* La franja solo tiene turnos ya completados: el nuevo va justo después */
      c = { id: 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), hora: hora, barbero: barbero };
      citas.splice(ultimo + 1, 0, c);
    }
    c.cliente = d.cliente; c.tel = d.tel; c.servicio = d.servicio; c.precio = d.precio;
    c.estado = 'reservada';
    return c;
  }

  var api = {
    pesos: pesos, precioVenta: precioVenta, pctGanancia: pctGanancia, pagoBarbero: pagoBarbero,
    ocupado: ocupado, horasAgenda: horasAgenda, disponibilidad: disponibilidad, reservar: reservar
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window === 'undefined') return;   /* Node: hasta aquí */

  /* ══════════ Sólo navegador ══════════ */

  Object.keys(api).forEach(function (k) { window[k] = api[k]; });

  /* Feedback breve en un botón sin perder su etiqueta original (Nielsen #1). */
  window.avisar = function (el, texto, ms) {
    if (el.dataset.original === undefined) el.dataset.original = el.textContent;
    el.textContent = texto;
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.textContent = el.dataset.original; }, ms || 2000);
  };

  /* Aviso flotante arriba (no tapa la nav ni los botones del pulgar).
     Si hay una hoja abierta se cuelga de ella: un <dialog> modal tapa todo lo demás. */
  window.toast = function (msg, tipo) {
    var t = document.getElementById('toast');
    if (!t) {
      t = document.createElement('div');
      t.id = 'toast';
      t.setAttribute('role', 'status');
    }
    (document.querySelector('dialog[open]') || document.body).appendChild(t);
    t.textContent = msg;
    t.className = tipo === 'error' ? 'error' : '';
    void t.offsetWidth;   /* reinicia la animación si ya había un aviso visible */
    t.classList.add('ver');
    clearTimeout(t._t);
    t._t = setTimeout(function () { t.classList.remove('ver'); }, 2600);
  };

  /* Reemplazo de confirm(): hoja inferior con la acción al alcance del pulgar.
     Devuelve una promesa con true/false. ESC o tocar fuera = cancelar. */
  window.confirmar = function (titulo, detalle, textoOk) {
    return new Promise(function (resolve) {
      var d = document.createElement('dialog');
      d.className = 'confirmar';
      d.innerHTML = '<form method="dialog"><h2></h2><p></p>' +
        '<button value="ok" class="ok"></button><button value="no" autofocus>Cancelar</button></form>';
      d.querySelector('h2').textContent = titulo;
      d.querySelector('p').textContent = detalle || '';
      d.querySelector('.ok').textContent = textoOk || 'Confirmar';
      d.addEventListener('click', function (e) { if (e.target === d) d.close(); });
      d.addEventListener('close', function () { resolve(d.returnValue === 'ok'); d.remove(); });
      document.body.appendChild(d);
      d.showModal();
    });
  };

  /* El evento submit no se dispara si el formulario es inválido: marcamos aquí. */
  document.addEventListener('invalid', function (e) {
    if (e.target.form) e.target.form.classList.add('enviado');
  }, true);

  /* Paleta: neutros + un solo acento (brand.dark) para las acciones principales. */
  window.tailwind = window.tailwind || {};
  window.tailwind.config = {
    theme: {
      extend: {
        colors: {
          brand: {
            lightest: '#E8F4F8',   /* tinte del acento: chips y fondos suaves */
            light:    '#D9E2E8',   /* bordes */
            DEFAULT:  '#54C2DD',   /* foco y detalles */
            dark:     '#17748E',   /* acento: 5.3:1 sobre blanco */
            darkest:  '#1B2B36'    /* texto */
          }
        },
        fontFamily: {
          sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Inter', 'Helvetica Neue', 'Arial', 'sans-serif']
        },
        boxShadow: {
          soft: '0 1px 2px rgba(15,23,42,.05), 0 8px 24px -16px rgba(15,23,42,.18)',
          lift: '0 2px 4px rgba(15,23,42,.06), 0 20px 40px -16px rgba(15,23,42,.28)'
        }
      }
    }
  };

  /* CSS plano: no necesita pasar por Tailwind, así que un <style> normal basta. */
  var css = [
    ':focus-visible{outline:2px solid #17748E;outline-offset:2px;border-radius:8px}',
    'html{background:#F1F5F9}',
    /* Navegación sólo vertical: nada puede empujar la página hacia los lados */
    'body{overflow-x:hidden}',
    /* Área táctil mínima de 44px en todo control, sin depender de cada pantalla */
    'button,select,input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=file]){min-height:44px}',
    /* <dialog> nativo: backdrop, cierre con ESC y foco atrapado los pone el navegador */
    'dialog::backdrop{background:rgba(15,23,42,.45);backdrop-filter:blur(3px)}',
    'dialog[open]{animation:sheet-up .3s cubic-bezier(.32,.72,0,1)}',
    '@keyframes sheet-up{from{transform:translateY(100%)}}',
    /* Rojo de validación sólo tras el primer intento de envío, no mientras se escribe */
    'form.enviado input:invalid,form.enviado select:invalid{border-color:#dc2626}',

    '#toast{position:fixed;left:50%;top:calc(.75rem + env(safe-area-inset-top));z-index:100;width:max-content;max-width:calc(100vw - 2rem);padding:.75rem 1.125rem;border-radius:999px;background:#1B2B36;color:#fff;font-size:.875rem;font-weight:600;text-align:center;box-shadow:0 12px 32px -12px rgba(15,23,42,.5);opacity:0;transform:translate(-50%,-150%);transition:transform .3s cubic-bezier(.32,.72,0,1),opacity .2s;pointer-events:none}',
    '#toast.ver{opacity:1;transform:translate(-50%,0)}',
    '#toast.error{background:#be123c}',

    'dialog.confirmar{margin:auto auto 0;width:100%;max-width:28rem;border:0;border-radius:1.5rem 1.5rem 0 0;padding:1.5rem 1.25rem calc(1.25rem + env(safe-area-inset-bottom));background:#fff;color:#1B2B36}',
    'dialog.confirmar h2{font-size:1.125rem;font-weight:600}',
    'dialog.confirmar p{margin:.375rem 0 1.25rem;font-size:.875rem;line-height:1.5;color:#64748b}',
    'dialog.confirmar button{display:block;width:100%;min-height:52px;border-radius:1rem;font-size:1rem;font-weight:600}',
    'dialog.confirmar .ok{margin-bottom:.5rem;background:#be123c;color:#fff}',

    /* Spinner: basta con poner aria-busy="true" en el botón */
    'button[aria-busy=true]{pointer-events:none;opacity:.85}',
    'button[aria-busy=true]::before{content:"";display:inline-block;width:1em;height:1em;margin-right:.5em;vertical-align:-.15em;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:giro .6s linear infinite}',
    '@keyframes giro{to{transform:rotate(360deg)}}',

    '@media (prefers-reduced-motion:reduce){dialog[open]{animation:none}#toast{transition:none}}'
  ].join('\n');

  var s = document.createElement('style');
  s.textContent = css;
  document.head.appendChild(s);
})();
