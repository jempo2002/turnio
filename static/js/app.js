/* Turnio (tomado de jemPOS Chef): formularios y botones que llaman a la API.
 *
 *   <form data-api="POST /api/sedes">  envia los campos como JSON
 *   <button data-api="DELETE /api/sedes/3"
 *           data-confirmar="¿Eliminar la sede Centro?"   pregunta (título)
 *           data-detalle="Su historial se conserva."     qué va a pasar
 *           data-boton="Eliminar sede"                    texto del botón
 *           data-peligro="no">                            acción normal (azul)
 *
 * Sin JS inline (la CSP lo bloquea). Los avisos y la confirmación son los
 * mismos del panel (Turnio.aviso, Turnio.confirmar y Turnio.explicar en
 * static/js/panel/turnio.js; reglas en docs/ux-avisos.md). Con ok recarga la
 * página; con error dice qué pasó y qué hacer, con el botón para subir de plan
 * si es un límite. Si la respuesta trae `invitacion` (equipo), muestra el
 * enlace con botones de WhatsApp y copiar, y recarga al cerrar el aviso.
 */
(function () {
  'use strict';

  var T = window.Turnio;
  var csrf = document.querySelector('meta[name="csrf-token"]');

  function crearBoton(texto, clase) {
    var b = document.createElement(clase === 'a' ? 'a' : 'button');
    b.className = 'btn';
    b.textContent = texto;
    if (clase !== 'a') b.type = 'button';
    return b;
  }

  function mostrarInvitacion(msg, inv) {
    var caja = document.getElementById('mensaje');
    if (!caja) { T.aviso({ tipo: 'exito', titulo: msg, detalle: inv.enlace, ms: 15000 }); return; }
    caja.textContent = msg;
    caja.className = 'aviso aviso--ok';
    var campo = document.createElement('input');
    campo.readOnly = true;
    campo.value = inv.enlace;
    campo.setAttribute('aria-label', 'Enlace de invitación');
    var wa = crearBoton('Enviar por WhatsApp', 'a');
    wa.href = inv.whatsapp;
    wa.target = '_blank';
    wa.rel = 'noopener';
    var copiar = crearBoton('Copiar');
    copiar.addEventListener('click', function () {
      campo.select();
      if (navigator.clipboard) navigator.clipboard.writeText(inv.enlace);
      else document.execCommand('copy');
      copiar.textContent = 'Copiado';
    });
    var listo = crearBoton('Listo');
    listo.addEventListener('click', function () { window.location.reload(); });
    var fila = document.createElement('div');
    fila.className = 'form form--fila';
    [campo, wa, copiar, listo].forEach(function (el) { fila.appendChild(el); });
    caja.appendChild(fila);
    caja.hidden = false;
    caja.scrollIntoView({ block: 'nearest' });
  }

  function llamar(spec, cuerpo, boton, form) {
    var partes = spec.split(' ');
    var status = 0;
    if (boton) { boton.disabled = true; boton.setAttribute('aria-busy', 'true'); }
    return fetch(partes[1], {
      method: partes[0],
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-CSRFToken': csrf ? csrf.content : ''
      },
      body: cuerpo ? JSON.stringify(cuerpo) : null
    })
      .then(function (r) {
        status = r.status;
        if (r.status === 401) {
          T.aviso(T.explicar(401));
          window.setTimeout(function () { window.location.href = '/login'; }, 1500);
          return null;
        }
        return r.json().catch(function () { return { ok: false, msg: '' }; });
      }, function () { return { ok: false, msg: '' }; })
      .then(function (data) {
        if (!data) return;
        if (data.ok && data.invitacion) {
          mostrarInvitacion(data.msg, data.invitacion);
          return;
        }
        if (data.ok) {
          T.aviso({ tipo: 'exito', titulo: data.msg || 'Listo, quedó guardado.' });
          window.setTimeout(function () { window.location.reload(); }, 900);
          return;
        }
        if (data.code === 'sin_sede') { window.location.href = '/seleccionar-sede'; return; }
        var aviso = T.explicar(status, data.msg, data);
        var campo = form && data.field && form.elements[data.field];
        if (campo) T.marcarCampo(campo, aviso.detalle);
        T.aviso(aviso);
      })
      .finally(function () {
        if (boton) { boton.disabled = false; boton.removeAttribute('aria-busy'); }
      });
  }

  /* Pregunta antes de lo que borra o cuesta plata; sin data-confirmar, sigue derecho. */
  function confirmar(el) {
    var d = el.dataset;
    if (!d.confirmar) return Promise.resolve(true);
    return T.confirmar(d.confirmar, d.detalle || '', d.boton || 'Confirmar', { peligro: d.peligro !== 'no' });
  }

  document.addEventListener('submit', function (ev) {
    var form = ev.target;
    if (!form.dataset || !form.dataset.api) return;
    ev.preventDefault();
    confirmar(form).then(function (ok) {
      if (!ok) return;
      var datos = {};
      new FormData(form).forEach(function (v, k) { datos[k] = v; });
      llamar(form.dataset.api, datos, form.querySelector('[type="submit"]'), form);
    });
  });

  document.addEventListener('click', function (ev) {
    var boton = ev.target.closest('button[data-api]');
    if (!boton) return;
    confirmar(boton).then(function (ok) {
      if (ok) llamar(boton.dataset.api, null, boton);
    });
  });
})();
