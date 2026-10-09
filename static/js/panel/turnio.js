/* Turnio — utilidades del panel y cliente de la API (T7).
   Reemplaza a datos.js: ya no hay localStorage, todo dato viene de la API
   Flask y cada cambio es un fetch. La sesión es la cookie HttpOnly del
   servidor; el JS nunca ve un token.
   En Node se puede requerir para probar la lógica pura (test-calculo.js). */

(function () {
  'use strict';

  /* ══════════ Lógica pura ══════════ */

  /* Moneda colombiana: sin decimales. */
  function pesos(n) {
    return '$' + Math.round(Number(n) || 0).toLocaleString('es-CO');
  }

  /* Precio de venta a partir del costo y el % de ganancia deseado.
     Se redondea a $100: es la moneda más pequeña que se maneja en el cajón. */
  function precioVenta(compra, pct) {
    if (!(compra > 0) || isNaN(pct)) return 0;
    return Math.round(compra * (1 + pct / 100) / 100) * 100;
  }

  /* Camino inverso: si se escribe el precio de venta a mano,
     se recalcula el % de ganancia que ese precio representa. */
  function pctGanancia(compra, venta) {
    if (!(compra > 0)) return 0;
    return Math.round((venta - compra) / compra * 100);
  }

  /* Reparto fijo: de lo que cuesta un servicio, cuánto es del profesional.
     Nunca negativo ni mayor que el precio; lo que sobra es del local. */
  function pagoProfesional(precio, monto) {
    if (!(monto > 0)) return 0;
    return Math.min(monto, precio);
  }

  function minutos(hhmm) {
    var p = String(hhmm).split(':');
    return Number(p[0]) * 60 + Number(p[1]);
  }

  function hhmm(min) {
    return String(Math.floor(min / 60)).padStart(2, '0') + ':' + String(min % 60).padStart(2, '0');
  }

  /* Turnos libres de una agenda para pintar en la línea de tiempo: una tarjeta
     por hora en punto, desde la apertura hasta la última hora que cabe antes del
     cierre. Una hora está libre si nada vigente la toca: citas reservadas,
     bloqueos o el almuerzo (una cita completada ya no ocupa, igual que en la API).
     `ocupado` = [{hora, fin}] en 'HH:MM' del día; `desde` = no antes de (hoy: ahora).
     ponytail: la hora exacta la elige quien agenda entre las que da
     /api/agenda/disponibilidad (cada 15 min, con la duración del servicio). */
  function turnosLibres(dia, ocupado, desde) {
    if (!dia || !dia.abierto) return [];
    var abre = minutos(dia.abre), cierra = minutos(dia.cierra);
    var bloques = ocupado.map(function (o) { return [minutos(o.hora), minutos(o.fin)]; });
    if (dia.almuerzo_desde && dia.almuerzo_hasta) bloques.push([minutos(dia.almuerzo_desde), minutos(dia.almuerzo_hasta)]);
    var minimo = desde ? minutos(desde) : 0;
    var libres = [];
    for (var t = Math.ceil(abre / 60) * 60; t + 60 <= cierra; t += 60) {
      if (t < minimo) continue;
      var choca = bloques.some(function (b) { return t < b[1] && t + 60 > b[0]; });
      if (!choca) libres.push(hhmm(t));
    }
    return libres;
  }

  var api = {
    pesos: pesos, precioVenta: precioVenta, pctGanancia: pctGanancia,
    pagoProfesional: pagoProfesional, turnosLibres: turnosLibres, minutos: minutos, hhmm: hhmm
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window === 'undefined') return;   /* Node: hasta aquí */

  /* ══════════ Sólo navegador ══════════ */

  var T = window.Turnio = api;
  var csrf = document.querySelector('meta[name="csrf-token"]');

  /* Quién tiene la sesión: lo pinta el servidor en data-* del <body>. */
  var b = document.body.dataset;
  T.yo = {
    id: Number(b.yoId),
    nombre: b.yoNombre || '',
    rol: b.yoRol || '',
    atiende: b.yoAtiende === '1',
    funciones: (b.yoFunciones || '').split(' ').filter(Boolean)
  };
  T.puede = function (funcion) { return T.yo.funciones.indexOf(funcion) >= 0; };
  T.esCaja = T.yo.rol === 'Admin' || T.yo.rol === 'Recepcion';

  T.$ = function (id) { return document.getElementById(id); };

  T.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };

  T.iniciales = function (nombre) {
    var p = String(nombre || '').trim().split(/\s+/);
    return (p.length > 1 ? p[0].charAt(0) + p[1].charAt(0) : p[0].slice(0, 2)).toUpperCase();
  };

  /* Fecha local del celular en AAAA-MM-DD (el servidor trabaja en hora de Colombia). */
  T.fechaISO = function (d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  };

  /* ── Cliente de la API ──
     T.api('POST', '/api/ventas', {...}) → promesa con el JSON si ok; si no,
     rechaza con un Error cuyo mensaje ya sirve para mostrar. Lo que no es de
     una pantalla en particular se resuelve aquí: sesión vencida → login, sin
     sede → elegirla. */
  function ErrorApi(msg, status, datos) {
    var e = new Error(msg);
    e.status = status;
    e.datos = datos || {};
    return e;
  }

  T.api = function (metodo, url, cuerpo, opciones) {
    var formData = cuerpo instanceof FormData;
    var headers = { 'Accept': 'application/json', 'X-CSRFToken': csrf ? csrf.content : '' };
    if (cuerpo && !formData) headers['Content-Type'] = 'application/json';
    return fetch(url, {
      method: metodo,
      credentials: 'same-origin',
      headers: headers,
      body: cuerpo ? (formData ? cuerpo : JSON.stringify(cuerpo)) : null,
      signal: opciones && opciones.signal
    }).then(function (r) {
      if (r.status === 401) {
        location.href = '/login';
        throw ErrorApi('Tu sesión se cerró. Vuelve a entrar.', 401);
      }
      return r.json().catch(function () { return { ok: false, msg: 'Error ' + r.status + '. Intenta de nuevo.' }; })
        .then(function (d) {
          if (d.code === 'sin_sede') { location.href = '/seleccionar-sede'; }
          if (!r.ok || d.ok === false) throw ErrorApi(d.msg || 'No se pudo completar.', r.status, d);
          return d;
        });
    }, function (e) {
      if (e && e.name === 'AbortError') throw e;
      throw ErrorApi('Sin conexión. Revisa el internet e intenta de nuevo.', 0);
    });
  };

  /* Botón ocupado mientras va la petición: spinner (aria-busy) y sin doble envío. */
  T.ocupado = function (boton, promesa) {
    if (!boton) return promesa;
    boton.setAttribute('aria-busy', 'true');
    boton.disabled = true;
    return promesa.finally(function () {
      boton.removeAttribute('aria-busy');
      boton.disabled = false;
    });
  };

  /* Error de una acción: aviso rojo. Devuelve null para encadenar en un catch. */
  T.fallo = function (e) {
    if (e && e.name === 'AbortError') return null;
    T.toast((e && e.message) || 'No se pudo completar.', 'error');
    return null;
  };

  /* Error al cargar una sección: tarjeta con "Reintentar" en lugar del contenido. */
  T.errorCarga = function (contenedor, e, reintentar) {
    if (e && e.name === 'AbortError') return;
    contenedor.removeAttribute('aria-busy');
    contenedor.innerHTML =
      '<div class="rounded-3xl border border-rose-200 bg-white p-6 text-center shadow-soft" role="alert">' +
        '<p class="text-sm font-semibold text-rose-700">No se pudo cargar</p>' +
        '<p class="mt-1 text-xs text-brand-darkest/60">' + T.esc((e && e.message) || 'Intenta de nuevo.') + '</p>' +
        '<button type="button" data-reintentar class="mt-4 rounded-xl bg-brand-dark px-5 text-sm font-semibold text-white transition hover:bg-brand-darkest active:scale-95">Reintentar</button>' +
      '</div>';
    contenedor.querySelector('[data-reintentar]').addEventListener('click', reintentar);
  };

  /* Feedback breve en un botón sin perder su etiqueta original (Nielsen #1). */
  T.avisar = function (el, texto, ms) {
    if (el.dataset.original === undefined) el.dataset.original = el.textContent;
    el.textContent = texto;
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.textContent = el.dataset.original; }, ms || 2000);
  };

  /* Aviso flotante arriba (no tapa la nav ni los botones del pulgar).
     Si hay una hoja abierta se cuelga de ella: un <dialog> modal tapa todo lo demás. */
  T.toast = function (msg, tipo) {
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
    t._t = setTimeout(function () { t.classList.remove('ver'); }, tipo === 'error' ? 4000 : 2600);
  };

  /* Reemplazo de confirm(): hoja inferior con la acción al alcance del pulgar.
     Devuelve una promesa con true/false. ESC o tocar fuera = cancelar. */
  T.confirmar = function (titulo, detalle, textoOk) {
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

  /* Hojas inferiores: tocar fuera cierra. */
  T.hoja = function (dialog) {
    dialog.addEventListener('click', function (e) { if (e.target === dialog) dialog.close(); });
    return dialog;
  };

  /* Volver a la pestaña (o al celular) refresca los datos: lo que otro del
     equipo cambió aparece sin recargar. Mientras está visible, cada `cadaMs`.
     ponytail: sondeo simple; si hace falta tiempo real, SSE o websockets. */
  T.alVolver = function (fn, cadaMs) {
    var ultima = Date.now();
    function quizas() {
      if (document.hidden || document.querySelector('dialog[open]')) return;
      if (Date.now() - ultima < 5000) return;
      ultima = Date.now();
      fn();
    }
    document.addEventListener('visibilitychange', quizas);
    window.addEventListener('focus', quizas);
    if (cadaMs) setInterval(quizas, cadaMs);
  };

  /* El evento submit no se dispara si el formulario es inválido: marcamos aquí. */
  document.addEventListener('invalid', function (e) {
    if (e.target.form) e.target.form.classList.add('enviado');
  }, true);
})();
