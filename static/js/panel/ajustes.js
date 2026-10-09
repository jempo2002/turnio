/* Turnio — Ajustes: datos del negocio, logo, horario de la sede y la cuenta.
   Datos: /api/negocio, /api/negocio/logo, /api/horario (T4) y /api/cuenta/clave. */

(function () {
  'use strict';

  var T = window.Turnio, $ = T.$, esc = T.esc;
  var dias = [];   /* 7 días, lunes = 0, tal como los manda /api/horario */

  $('cuenta-iniciales').textContent = T.iniciales(T.yo.nombre);

  /* ══ Contraseña ══ */
  var sheet = T.hoja($('sheet-clave')), formClave = $('form-clave');

  $('btn-clave').addEventListener('click', function () {
    formClave.reset();
    formClave.classList.remove('enviado');
    $('clave-error').classList.add('hidden');
    sheet.showModal();
  });

  formClave.addEventListener('submit', function (e) {
    e.preventDefault();
    formClave.classList.add('enviado');
    var iguales = $('clave-nueva').value === $('clave-repetir').value;
    $('clave-error').classList.toggle('hidden', iguales);
    if (!iguales) { $('clave-repetir').focus(); return; }
    T.ocupado($('btn-guardar-clave'), T.api('PUT', '/api/cuenta/clave', {
      actual: $('clave-actual').value,
      nueva: $('clave-nueva').value
    })).then(function () {
      sheet.close();
      T.toast('✓ Contraseña actualizada');
    }).catch(function (err) {
      T.fallo(err);
      var campo = err.datos && err.datos.field === 'actual' ? 'clave-actual' : 'clave-nueva';
      $(campo).focus();
    });
  });

  /* ══ Cerrar sesión: acción destructiva, se confirma (Nielsen #5) ══ */
  $('btn-salir').addEventListener('click', function () {
    var b = this;
    T.confirmar('¿Cerrar sesión?', 'Tendrás que volver a ingresar en este dispositivo.', 'Cerrar sesión').then(function (si) {
      if (!si) return;
      T.ocupado(b, T.api('POST', '/api/auth/logout')).then(function () {
        location.href = '/login';
      }).catch(T.fallo);
    });
  });

  if (!$('form-ajustes')) return;   /* Recepción y Profesional: solo su cuenta */

  /* ══ Horarios: <input type="time"> nativo = reloj del sistema, sin librerías ══ */
  var HORA = 'block w-full min-w-0 rounded-lg border border-brand-light bg-white px-1 py-1.5 text-xs tabular-nums transition focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30';

  function errorDia(d) {
    if (!d.abierto) return '';
    if (d.cierra <= d.abre) return 'La hora de cierre debe ir después de la de apertura.';
    if (!d.almuerzo_desde !== !d.almuerzo_hasta) return 'Pon el inicio y el fin del almuerzo, o ninguno.';
    if (d.almuerzo_desde && !(d.abre <= d.almuerzo_desde && d.almuerzo_desde < d.almuerzo_hasta && d.almuerzo_hasta <= d.cierra)) {
      return 'El almuerzo debe quedar dentro del horario.';
    }
    return '';
  }

  function pintarHorarios() {
    $('form-ajustes').removeAttribute('aria-busy');
    $('horarios').innerHTML = dias.map(function (d, i) {
      var error = errorDia(d);
      /* Tres filas fijas (día, horario, almuerzo): a 360 px nada se parte raro */
      function fila(etiqueta, a, b, va, vb) {
        return '<div class="mt-1 grid grid-cols-[3.75rem_1fr_auto_1fr] items-center gap-1">' +
          '<span class="text-xs text-brand-darkest/55">' + etiqueta + '</span>' +
          '<input type="time" data-campo="' + a + '" data-i="' + i + '" value="' + (va || '') + '" aria-label="' + etiqueta + ' desde, ' + esc(d.nombre) + '" class="' + HORA + '">' +
          '<span class="text-xs text-brand-darkest/40" aria-hidden="true">a</span>' +
          '<input type="time" data-campo="' + b + '" data-i="' + i + '" value="' + (vb || '') + '" aria-label="' + etiqueta + ' hasta, ' + esc(d.nombre) + '" class="' + HORA + '">' +
        '</div>';
      }
      return '<li class="rounded-2xl bg-brand-lightest/40 p-3">' +
        '<div class="flex items-center justify-between gap-3">' +
          '<label class="flex min-h-[44px] flex-1 cursor-pointer items-center gap-2.5">' +
            '<input type="checkbox" data-campo="abierto" data-i="' + i + '"' + (d.abierto ? ' checked' : '') + ' class="h-5 w-5 rounded accent-brand-dark">' +
            '<span class="text-sm font-medium">' + esc(d.nombre) + '</span>' +
          '</label>' +
          (d.abierto ? '' : '<span class="rounded-full bg-white px-3 py-1.5 text-xs font-medium text-brand-darkest/50">Cerrado</span>') +
        '</div>' +
        (d.abierto ? fila('Abre', 'abre', 'cierra', d.abre, d.cierra) + fila('Almuerzo', 'almuerzo_desde', 'almuerzo_hasta', d.almuerzo_desde, d.almuerzo_hasta) : '') +
        (error ? '<p class="mt-2 text-xs font-medium text-rose-700" role="alert">' + error + '</p>' : '') +
      '</li>';
    }).join('');
  }

  $('horarios').addEventListener('change', function (e) {
    var t = e.target, campo = t.dataset.campo;
    if (!campo) return;
    var d = dias[Number(t.dataset.i)];
    if (campo === 'abierto') d.abierto = t.checked;
    else d[campo] = t.value || null;
    pintarHorarios();
  });

  $('btn-copiar-lunes').addEventListener('click', function () {
    var l = dias[0];
    dias.forEach(function (d) {
      d.abierto = l.abierto; d.abre = l.abre; d.cierra = l.cierra;
      d.almuerzo_desde = l.almuerzo_desde; d.almuerzo_hasta = l.almuerzo_hasta;
    });
    pintarHorarios();
    T.avisar(this, '✓ Aplicado a los 7 días');
  });

  function cargarHorario() {
    return T.api('GET', '/api/horario').then(function (r) {
      dias = r.dias;
      pintarHorarios();
    }).catch(function (e) { T.errorCarga($('horarios'), e, cargarHorario); });
  }

  /* ══ Logo: se sube apenas se elige; la API valida tipo y tamaño ══ */
  $('logo').addEventListener('change', function () {
    var f = this.files && this.files[0];
    var input = this, err = $('logo-error');
    err.classList.add('hidden');
    if (!f) return;
    if (f.size > 2 * 1024 * 1024) {
      err.textContent = 'Esa imagen pesa ' + (f.size / 1048576).toFixed(1) + ' MB. El máximo son 2 MB.';
      err.classList.remove('hidden');
      input.value = '';
      return;
    }
    var datos = new FormData();
    datos.append('imagen', f);
    var boton = $('logo-boton');
    boton.setAttribute('aria-busy', 'true');
    T.api('POST', '/api/negocio/logo', datos).then(function (r) {
      var img = $('logo-img');
      img.src = r.logo_url;
      img.alt = 'Logo del negocio';
      img.classList.remove('hidden');
      $('logo-iniciales').classList.add('hidden');
      T.toast('✓ Logo actualizado');
    }).catch(function (e) {
      err.textContent = e.message;
      err.classList.remove('hidden');
    }).finally(function () {
      boton.removeAttribute('aria-busy');
      input.value = '';
    });
  });

  /* ══ Link público ══ */
  function urlPublica() {
    return $('slug').dataset.base + $('slug').value.trim();
  }

  function refrescarWhatsapp() {
    $('btn-whatsapp').href = 'https://wa.me/?text=' +
      encodeURIComponent('Reserva tu turno en ' + $('negocio').value.trim() + ': ' + urlPublica());
  }
  $('negocio').addEventListener('input', refrescarWhatsapp);
  $('slug').addEventListener('input', refrescarWhatsapp);
  refrescarWhatsapp();

  $('btn-copiar').addEventListener('click', function () {
    var btn = this;
    if (!navigator.clipboard) { T.toast(urlPublica()); return; }
    navigator.clipboard.writeText(urlPublica()).then(
      function () { T.avisar(btn, '✓ Copiado'); },
      function () { T.avisar(btn, 'Copia a mano', 3000); }
    );
  });

  /* ══ Guardar: datos del negocio y horario de la sede ══ */
  $('form-ajustes').addEventListener('submit', function (e) {
    e.preventDefault();
    this.classList.add('enviado');
    var malos = dias.filter(function (d) { return errorDia(d); });
    if (malos.length) {
      T.toast('Revisa el horario de ' + malos.map(function (d) { return d.nombre; }).join(', '), 'error');
      return;
    }
    var negocio = {
      nombre_negocio: $('negocio').value.trim(),
      tipo_negocio: $('tipo').value,
      telefono: $('whatsapp').value.trim(),
      slug: $('slug').value.trim().toLowerCase()
    };
    var pedidas = [T.api('PUT', '/api/negocio', negocio)];
    if (dias.length) pedidas.push(T.api('PUT', '/api/horario', { dias: dias }));
    T.ocupado($('btn-guardar'), Promise.all(pedidas)).then(function () {
      document.body.dataset.negocio = negocio.nombre_negocio;
      T.toast('✓ Cambios guardados');
    }).catch(T.fallo);
  });

  cargarHorario();
})();
