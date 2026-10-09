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

  /* Avisos (docs/ux-avisos.md): todo error que ve una persona dice qué pasó
     (titulo) y qué hacer (detalle), sin jerga. `status` es el HTTP de la API
     (0 = sin conexión), `msg` lo que explicó el servidor y `datos` su JSON. */
  function explicar(status, msg, datos) {
    datos = datos || {};
    msg = String(msg || '').trim();
    if (datos.code === 'limite_plan') {
      return { tipo: 'aviso', titulo: 'Llegaste al tope de tu plan', detalle: msg,
               accion: datos.accion_url ? { texto: datos.accion_texto || 'Ver planes', href: datos.accion_url } : null };
    }
    if (status === 401) return { tipo: 'aviso', titulo: 'Tu sesión se cerró', detalle: 'Vuelve a entrar con tu correo y contraseña.' };
    if (status === 0) return { tipo: 'error', titulo: 'Sin conexión', detalle: 'Revisa el internet del celular y vuelve a intentarlo. No se guardó nada.' };
    if (status === 402 || datos.code === 'suscripcion_vencida') {
      return { tipo: 'aviso', titulo: 'Tu suscripción venció', detalle: 'Puedes ver todo, pero para guardar cambios renueva tu plan.', accion: { texto: 'Ver mi plan', href: '/ajustes#plan' } };
    }
    if (status === 429) return { tipo: 'aviso', titulo: 'Espera un momento', detalle: msg || 'Hiciste varios intentos seguidos. Espera un minuto y vuelve a intentarlo.' };
    if (status === 403) return { tipo: 'error', titulo: 'No tienes permiso para esto', detalle: (msg && !/permis/i.test(msg) ? msg + ' ' : '') + 'Pídele al administrador que lo haga o que te dé acceso.' };
    if (status === 404) return { tipo: 'error', titulo: 'Ya no está disponible', detalle: (msg ? msg + ' ' : '') + 'Recarga la pantalla para ver los datos al día.', accion: { texto: 'Recargar', recargar: true } };
    if (status === 409) return { tipo: 'error', titulo: 'No se pudo guardar', detalle: msg || 'Alguien cambió esto hace un momento. Recarga y vuelve a intentarlo.' };
    if (status >= 500) return { tipo: 'error', titulo: 'Algo falló de nuestro lado', detalle: 'No es tu culpa. Intenta de nuevo en un momento; si sigue pasando, escríbenos por WhatsApp.' };
    return { tipo: 'error', titulo: 'Revisa los datos', detalle: msg || 'Algo no quedó bien. Revisa lo que escribiste y vuelve a intentarlo.' };
  }

  var api = {
    explicar: explicar,
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
  /* Como se le dice a quien atiende en este negocio: barbero, estilista,
     manicurista... (T9, app/services/vertical_service.py). */
  T.voc = { profesional: b.vocProfesional || 'profesional' };
  T.voc.Profesional = T.voc.profesional.charAt(0).toUpperCase() + T.voc.profesional.slice(1);
  T.puede = function (funcion) { return T.yo.funciones.indexOf(funcion) >= 0; };
  T.esCaja = T.yo.rol === 'Admin' || T.yo.rol === 'Recepcion';

  T.$ = function (id) { return document.getElementById(id); };

  T.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };

  /* ── HTML que escapa solo ──
     T.h`<p>${nombre}</p>` escapa todo lo que se interpola, como Jinja: un dato
     del usuario nunca se vuelve marcado. Lo que ya es T.h (o una lista de T.h)
     entra tal cual; false/null/undefined no pintan nada. T.pintar() es el único
     sitio que convierte ese texto en nodos (tests/test_seguridad.py). */
  function Html(texto) { this.texto = texto; }

  function trozo(v) {
    if (v instanceof Html) return v.texto;
    if (Array.isArray(v)) return v.map(trozo).join('');
    if (v === null || v === undefined || v === false) return '';
    return T.esc(v);
  }

  T.h = function (partes) {
    var texto = partes[0];
    for (var i = 1; i < arguments.length; i++) texto += trozo(arguments[i]) + partes[i];
    return new Html(texto);
  };

  T.pintar = function (el, contenido) {
    el.replaceChildren(document.createRange().createContextualFragment(trozo(contenido)));
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
  /* El mensaje del error ya es el texto amable (detalle de explicar()); el
     título y la acción van en e.aviso para T.fallo. */
  function ErrorApi(msg, status, datos) {
    var aviso = explicar(status, msg, datos);
    var e = new Error(aviso.detalle);
    e.status = status;
    e.datos = datos || {};
    e.aviso = aviso;
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
      return r.json().catch(function () { return { ok: false, msg: '' }; })
        .then(function (d) {
          if (d.code === 'sin_sede') { location.href = '/seleccionar-sede'; }
          if (!r.ok || d.ok === false) throw ErrorApi(d.msg || '', r.status, d);
          return d;
        });
    }, function (e) {
      if (e && e.name === 'AbortError') throw e;
      throw ErrorApi('', 0);
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

  /* ── Errores en un campo: el mensaje va debajo del campo, no solo arriba ── */
  T.marcarCampo = function (campo, msg) {
    if (!campo) return;
    var id = (campo.id || campo.name) + '-error';
    var p = document.getElementById(id);
    if (!p) {
      p = document.createElement('p');
      p.id = id;
      p.className = 'campo-error';
      campo.insertAdjacentElement('afterend', p);
    }
    p.textContent = msg;
    campo.setAttribute('aria-invalid', 'true');
    campo.setAttribute('aria-describedby', id);
    campo.addEventListener('input', function limpiar() {
      campo.removeAttribute('aria-invalid');
      p.remove();
      campo.removeEventListener('input', limpiar);
    });
    campo.focus();
  };

  /* Error de una acción: aviso con qué pasó y qué hacer. Si el servidor dice
     qué campo está mal (`field`) y viene el formulario, se marca ese campo.
     Devuelve null para encadenar en un catch. */
  T.fallo = function (e, form) {
    if (e && e.name === 'AbortError') return null;
    var a = (e && e.aviso) || explicar(e && e.status, e && e.message);
    var campo = form && e && e.datos && e.datos.field && form.elements[e.datos.field];
    if (campo) T.marcarCampo(campo, a.detalle);
    T.aviso(a);
    return null;
  };

  /* Error al cargar una sección: tarjeta con qué pasó y "Reintentar" en lugar del contenido. */
  T.errorCarga = function (contenedor, e, reintentar) {
    if (e && e.name === 'AbortError') return;
    var a = (e && e.aviso) || explicar(e && e.status, e && e.message);
    contenedor.removeAttribute('aria-busy');
    T.pintar(contenedor, T.h`
      <div class="rounded-3xl border border-rose-200 bg-white p-6 text-center shadow-soft" role="alert">
        <p class="text-sm font-semibold text-rose-700">No pudimos cargar esta parte · ${a.titulo}</p>
        <p class="mt-1 text-xs text-brand-darkest/70">${a.detalle}</p>
        <button type="button" data-reintentar class="mt-4 rounded-xl bg-brand-dark px-5 text-sm font-semibold text-white transition hover:bg-brand-darkest active:scale-95">Reintentar</button>
      </div>`);
    contenedor.querySelector('[data-reintentar]').addEventListener('click', reintentar);
  };

  /* Feedback breve en un botón sin perder su etiqueta original (Nielsen #1). */
  T.avisar = function (el, texto, ms) {
    if (el.dataset.original === undefined) el.dataset.original = el.textContent;
    el.textContent = texto;
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.textContent = el.dataset.original; }, ms || 2000);
  };

  /* ── Aviso flotante (docs/ux-avisos.md) ──
     T.aviso({tipo, titulo, detalle, accion: {texto, href | fn | recargar}, ms})
     tipo: exito (verde, se va solo), info, aviso (ámbar) o error (rojo, se
     queda hasta 8 s y se puede cerrar). Siempre icono + texto: nunca solo
     color. Arriba, para no tapar la barra ni los botones del pulgar; si hay
     una hoja abierta se cuelga de ella (un <dialog> modal tapa lo demás). */
  var ICONOS = {
    exito: T.h`<path d="M20 6.5L9.5 17 4 11.5"></path>`,
    error: T.h`<circle cx="12" cy="12" r="9"></circle><path d="M12 7.5v5"></path><path d="M12 16.2v.3"></path>`,
    aviso: T.h`<path d="M12 3.5 2.5 20h19L12 3.5Z"></path><path d="M12 10v4"></path><path d="M12 17.2v.3"></path>`,
    info: T.h`<circle cx="12" cy="12" r="9"></circle><path d="M12 11v5.5"></path><path d="M12 7.8v.3"></path>`
  };
  var DURACION = { exito: 3200, info: 4500, aviso: 7000, error: 8000 };

  T.aviso = function (o) {
    var tipo = ICONOS[o.tipo] ? o.tipo : 'info';
    var t = document.getElementById('toast');
    if (!t) {
      t = document.createElement('div');
      t.id = 'toast';
    }
    (document.querySelector('dialog[open]') || document.body).appendChild(t);
    /* Los errores interrumpen al lector de pantalla; lo demás espera su turno. */
    t.setAttribute('role', tipo === 'error' ? 'alert' : 'status');
    t.className = tipo;
    var accion = o.accion;
    T.pintar(t, T.h`
      <svg class="icono" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONOS[tipo]}</svg>
      <div class="texto"><p class="titulo">${o.titulo}</p>${o.detalle && T.h`<p class="detalle">${o.detalle}</p>`}</div>
      ${accion && (accion.href
        ? T.h`<a class="accion" href="${accion.href}">${accion.texto}</a>`
        : T.h`<button type="button" class="accion">${accion.texto}</button>`)}
      <button type="button" class="cerrar" aria-label="Cerrar aviso">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"></path></svg>
      </button>`);
    function cerrar() { t.classList.remove('ver'); }
    t.querySelector('.cerrar').addEventListener('click', cerrar);
    var btn = t.querySelector('button.accion');
    if (btn) {
      btn.addEventListener('click', function () {
        cerrar();
        if (accion.recargar) location.reload();
        else if (accion.fn) accion.fn();
      });
    }
    void t.offsetWidth;   /* reinicia la animación si ya había un aviso visible */
    t.classList.add('ver');
    clearTimeout(t._t);
    t._t = setTimeout(cerrar, o.ms || DURACION[tipo]);
  };

  /* Atajo para un aviso de una línea. Sin tipo = éxito. */
  T.toast = function (msg, tipo) {
    T.aviso({ tipo: tipo || 'exito', titulo: msg });
  };

  /* Reemplazo de confirm(): hoja inferior con la acción al alcance del pulgar.
     `detalle` dice qué va a pasar; con {deshacer: false} se avisa que no tiene
     vuelta atrás. {peligro: false} pinta el botón con el color de la marca
     (una acción normal, no destructiva). Devuelve una promesa con true/false.
     ESC o tocar fuera = cancelar. */
  T.confirmar = function (titulo, detalle, textoOk, opciones) {
    opciones = opciones || {};
    var peligro = opciones.peligro !== false;
    return new Promise(function (resolve) {
      var d = document.createElement('dialog');
      d.className = 'confirmar';
      T.pintar(d, T.h`<form method="dialog"><h2>${titulo}</h2><p>${detalle || ''}</p>
        ${opciones.deshacer === false && T.h`<p class="irreversible">Esto no se puede deshacer.</p>`}
        <button value="ok" class="${peligro ? 'ok' : 'ok normal'}">${textoOk || 'Confirmar'}</button><button value="no" autofocus>Cancelar</button></form>`);
      d.addEventListener('click', function (e) { if (e.target === d) d.close(); });
      d.addEventListener('close', function () { resolve(d.returnValue === 'ok'); d.remove(); });
      document.body.appendChild(d);
      d.showModal();
    });
  };

  /* ── Guía de bienvenida (onboarding) ──
     T.guia('caja', contenedor, [{titulo, texto}, ...]): tarjeta al inicio de
     la pantalla con pocos pasos (máximo 3), que se puede saltar y no vuelve a
     salir en este dispositivo. T.guiasDeNuevo() las vuelve a mostrar todas. */
  var GUIA = 'turnio:guia:';

  function guardado(clave, valor) {
    try {
      if (valor === undefined) return localStorage.getItem(GUIA + clave);
      if (valor === null) localStorage.removeItem(GUIA + clave);
      else localStorage.setItem(GUIA + clave, valor);
    } catch (e) { /* modo privado o sin almacenamiento: la guía sale cada vez */ }
    return null;
  }

  T.guia = function (clave, contenedor, pasos) {
    if (!contenedor || !pasos.length || guardado(clave) === 'vista') return;
    var i = 0;
    var caja = document.createElement('section');
    caja.className = 'guia';
    caja.setAttribute('aria-label', 'Guía rápida');
    function cerrar() {
      guardado(clave, 'vista');
      caja.remove();
    }
    function pintar() {
      var p = pasos[i], ultimo = i === pasos.length - 1;
      T.pintar(caja, T.h`
        <p class="paso-guia">${pasos.length > 1 ? 'Guía rápida · ' + (i + 1) + ' de ' + pasos.length : 'Guía rápida'}</p>
        <p class="titulo">${p.titulo}</p>
        <p class="texto">${p.texto}</p>
        <div class="botones">
          ${!ultimo && T.h`<button type="button" data-saltar class="saltar">Saltar guía</button>`}
          <button type="button" data-seguir class="seguir">${ultimo ? '¡Entendido!' : 'Siguiente'}</button>
        </div>`);
      var saltar = caja.querySelector('[data-saltar]');
      if (saltar) saltar.addEventListener('click', cerrar);
      caja.querySelector('[data-seguir]').addEventListener('click', function () {
        if (ultimo) { cerrar(); return; }
        i++;
        pintar();
        caja.querySelector('[data-seguir]').focus();
      });
    }
    pintar();
    contenedor.prepend(caja);
  };

  T.guiasDeNuevo = function () {
    try {
      Object.keys(localStorage).forEach(function (k) { if (k.indexOf(GUIA) === 0) localStorage.removeItem(k); });
    } catch (e) { /* sin almacenamiento: ya salen siempre */ }
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
