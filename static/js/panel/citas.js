/* Turnio — Citas: agenda del día por profesional, cobro de citas y venta rápida.
   Datos: /api/citas, /api/profesionales, /api/horario, /api/agenda/disponibilidad,
   /api/citas/<id>/cobrar, /api/productos y /api/ventas (T4 a T6). */

(function () {
  'use strict';

  var T = window.Turnio, $ = T.$, esc = T.esc, pesos = T.pesos;
  var NEGOCIO = document.body.dataset.negocio || '';

  var filtro = 'todas';
  var dia = new Date();               /* día que se está viendo (fecha del celular) */
  var profesionales = [];             /* quienes atienden en la sede, con sus servicios */
  var quien = null;                   /* id del profesional cuya agenda se ve */
  var horario = [];                   /* 7 días, lunes = 0 */
  var citas = [];                     /* citas y bloqueos del día de esa agenda */
  var cargaActual = null;             /* AbortController de la última carga */
  var $lista = $('citas');

  function hoyISO() { return T.fechaISO(new Date()); }
  function fecha() { return T.fechaISO(dia); }
  function esHoy() { return fecha() === hoyISO(); }
  function ahoraHHMM() { var d = new Date(); return T.hhmm(d.getHours() * 60 + d.getMinutes()); }
  function horarioDelDia() { return horario[(dia.getDay() + 6) % 7]; }
  function profesional(id) { return profesionales.find(function (p) { return p.id_usuario === id; }); }
  function primerNombre(n) { return String(n || '').split(' ')[0]; }

  /* Hora de inicio/fin de una cita dentro del día que se ve (un bloqueo de
     varios días empieza a las 00:00 y termina a las 24:00 de los días del medio). */
  function horaEnDia(iso, borde) {
    if (iso.slice(0, 10) < fecha()) return '00:00';
    if (iso.slice(0, 10) > fecha()) return borde;
    return iso.slice(11, 16);
  }

  /* ══ Cabecera ══ */
  var h = new Date().getHours();
  $('saludo').textContent = (h < 12 ? 'Buenos días' : h < 19 ? 'Buenas tardes' : 'Buenas noches') + ', ' + primerNombre(T.yo.nombre);

  function pintarDia() {
    var largo = dia.toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' });
    $('fecha').textContent = largo;
    var manana = new Date(); manana.setDate(manana.getDate() + 1);
    var ayer = new Date(); ayer.setDate(ayer.getDate() - 1);
    $('dia-hoy').textContent = esHoy() ? 'Hoy' : fecha() === T.fechaISO(manana) ? 'Mañana' :
      fecha() === T.fechaISO(ayer) ? 'Ayer' : dia.toLocaleDateString('es-CO', { weekday: 'short', day: 'numeric', month: 'short' });

    /* Abierto / cerrado ahora (solo tiene sentido hoy) */
    var d = horarioDelDia(), est = $('estado-local');
    if (!d || !esHoy()) { est.classList.add('hidden'); est.classList.remove('inline-flex'); return; }
    var ahora = ahoraHHMM();
    var abierto = d.abierto && ahora >= d.abre && ahora < d.cierra;
    est.className = 'mt-1 inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ' +
      (abierto ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-brand-darkest/60');
    est.innerHTML = '<span class="h-1.5 w-1.5 rounded-full ' + (abierto ? 'bg-emerald-500' : 'bg-slate-400') + '" aria-hidden="true"></span>' +
      (abierto ? 'Abierto' : 'Cerrado');
  }

  function moverDia(n) {
    if (n === 0) dia = new Date(); else dia.setDate(dia.getDate() + n);
    pintarDia();
    cargarAgenda();
  }
  $('dia-ant').addEventListener('click', function () { moverDia(-1); });
  $('dia-sig').addEventListener('click', function () { moverDia(1); });
  $('dia-hoy').addEventListener('click', function () { moverDia(0); });

  /* ══ Selector de agenda: Admin y Recepción ven la de cualquiera; el Profesional, la suya ══ */
  function pintarProfesionales() {
    var sel = $('profesional');
    var ver = T.yo.rol !== 'Profesional' && profesionales.length > 1;
    $('caja-profesional').classList.toggle('hidden', !ver);
    sel.innerHTML = profesionales.map(function (p) {
      return '<option value="' + p.id_usuario + '">Agenda de ' + esc(p.nombre_completo) +
        (p.id_usuario === T.yo.id ? ' (tú)' : '') + '</option>';
    }).join('');
    if (quien) sel.value = String(quien);
  }

  $('profesional').addEventListener('change', function () {
    quien = Number(this.value);
    try { sessionStorage.setItem('turnio-agenda', quien); } catch (e) { /* sin almacenamiento */ }
    cargarAgenda();
  });

  /* ══ Carga ══ */
  function cargarTodo() {
    $lista.setAttribute('aria-busy', 'true');
    return Promise.all([T.api('GET', '/api/profesionales'), T.api('GET', '/api/horario')]).then(function (r) {
      profesionales = r[0].profesionales;
      horario = r[1].dias;
      var guardado = null;
      try { guardado = Number(sessionStorage.getItem('turnio-agenda')); } catch (e) {}
      quien = T.yo.rol === 'Profesional' ? T.yo.id
        : profesional(guardado) ? guardado
        : profesional(T.yo.id) ? T.yo.id
        : profesionales.length ? profesionales[0].id_usuario : null;
      pintarProfesionales();
      pintarDia();
      return cargarAgenda();
    }).catch(function (e) { T.errorCarga($lista, e, cargarTodo); });
  }

  function cargarAgenda() {
    if (!quien) { pintar(); return Promise.resolve(); }
    if (cargaActual) cargaActual.abort();
    var control = cargaActual = new AbortController();
    $lista.setAttribute('aria-busy', 'true');
    var pedidas = [T.api('GET', '/api/citas?fecha=' + fecha() + '&id_profesional=' + quien, null, { signal: control.signal })];
    if (T.esCaja) pedidas.push(T.api('GET', '/api/caja', null, { signal: control.signal }).catch(function () { return null; }));
    return Promise.all(pedidas).then(function (r) {
      citas = r[0].citas;
      if (r[1]) $('n-caja').textContent = pesos(r[1].caja.ingresos - r[1].caja.salidas);
      pintar();
    }).catch(function (e) { T.errorCarga($lista, e, cargarAgenda); });
  }

  /* ══ Línea de tiempo ══
     Color por hora: verde = libre, rojo tenue = reservada, gris = ya pasó o no se atiende. */
  var COLOR_HORA = {
    disponible: 'text-emerald-600',
    reservada:  'text-rose-600',
    completada: 'text-brand-darkest/40',
    no_asistio: 'text-brand-darkest/40',
    bloqueada:  'text-brand-darkest/40'
  };
  var BTN = 'flex min-w-0 flex-1 items-center justify-center rounded-xl px-1 text-xs font-semibold transition active:scale-[.98] ';

  /* WhatsApp de Colombia: 10 dígitos que empiezan por 3 → con el 57 delante. */
  function wa(tel) {
    var t = String(tel || '').replace(/\D/g, '');
    return t.length === 10 && t.charAt(0) === '3' ? '57' + t : t;
  }

  function items() {
    var lista = citas.map(function (c) {
      return Object.assign({}, c, { hora: horaEnDia(c.inicio, '23:59'), hasta: horaEnDia(c.fin, '24:00') });
    });
    var d = horarioDelDia();
    var almuerzoYaBloqueado = d && lista.some(function (c) {
      return c.estado === 'bloqueada' && c.hora === d.almuerzo_desde && c.hasta === d.almuerzo_hasta;
    });
    if (d && d.abierto && d.almuerzo_desde && d.almuerzo_hasta && !almuerzoYaBloqueado) {
      lista.push({ estado: 'bloqueada', hora: d.almuerzo_desde, hasta: d.almuerzo_hasta, cliente_nombre: 'Almuerzo', servicio: 'No reservable' });
    }
    if (fecha() >= hoyISO()) {
      var ocupado = lista.filter(function (c) { return c.estado === 'reservada' || c.estado === 'bloqueada'; })
        .map(function (c) { return { hora: c.hora, fin: c.hasta }; });
      T.turnosLibres(d, ocupado, esHoy() ? ahoraHHMM() : null).forEach(function (hora) {
        lista.push({ estado: 'disponible', hora: hora });
      });
    }
    return lista.sort(function (a, b) { return a.hora < b.hora ? -1 : a.hora > b.hora ? 1 : 0; });
  }

  function tarjeta(c) {
    var hora = '<span class="w-11 shrink-0 pt-4 text-right text-xs font-semibold tabular-nums ' + COLOR_HORA[c.estado] + '">' + c.hora + '</span>';
    var li = '<li class="flex gap-3">' + hora;

    /* Turno libre: toda la tarjeta es el botón. Un toque abre la hoja con la hora ya puesta. */
    if (c.estado === 'disponible') {
      return li +
        '<button type="button" data-agendar="' + c.hora + '" class="min-w-0 flex-1 rounded-2xl border border-dashed border-emerald-300 bg-emerald-50 py-4 text-sm font-semibold text-emerald-700 transition hover:bg-emerald-100 active:scale-[.99]">' +
          'Disponible · Agendar' +
        '</button></li>';
    }

    if (c.estado === 'bloqueada') {
      var texto = c.cliente_nombre === 'Almuerzo' && !c.id_cita ? 'Almuerzo · No reservable'
        : (c.toda_la_sede ? 'Local cerrado' : 'Bloqueado') + (c.nota ? ' · ' + c.nota : '') + ' · hasta ' + c.hasta;
      return li +
        '<div class="min-w-0 flex-1 truncate rounded-2xl bg-slate-200/60 px-4 py-3.5 text-xs font-medium text-brand-darkest/55">' + esc(texto) + '</div></li>';
    }

    var hecha = c.estado !== 'reservada';
    var acciones;
    if (c.estado === 'completada') {
      acciones = '<div class="mt-2 flex items-center justify-between gap-2">' +
          '<span class="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-brand-darkest/55">Completada</span>' +
          '<button type="button" data-accion="reabrir" data-id="' + c.id_cita + '" class="rounded-xl px-3 text-xs font-medium text-brand-darkest/55 transition hover:bg-slate-100">Deshacer</button>' +
        '</div>';
    } else if (c.estado === 'no_asistio') {
      acciones = '<div class="mt-2"><span class="rounded-full bg-amber-100 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-amber-800">No asistió</span></div>';
    } else {
      var msg = 'Hola ' + primerNombre(c.cliente_nombre) + ', te recordamos tu cita ' +
        (esHoy() ? 'hoy' : 'el ' + dia.toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' })) +
        ' a las ' + c.hora + (NEGOCIO ? ' en ' + NEGOCIO : '') + '.';
      acciones = '<div class="mt-3 flex gap-2">' +
          '<button type="button" data-accion="liberar" data-id="' + c.id_cita + '" class="' + BTN + 'border border-slate-200 text-rose-700 hover:bg-rose-50" aria-label="Liberar el turno de ' + esc(c.cliente_nombre) + '">Liberar</button>' +
          (c.cliente_telefono
            ? '<a href="https://wa.me/' + wa(c.cliente_telefono) + '?text=' + encodeURIComponent(msg) + '" target="_blank" rel="noopener" ' +
              'class="' + BTN + 'min-h-[44px] bg-emerald-50 text-emerald-700 hover:bg-emerald-100" aria-label="Recordar por WhatsApp a ' + esc(c.cliente_nombre) + '">Recordar</a>'
            : '') +
          '<button type="button" data-accion="completar" data-id="' + c.id_cita + '" class="' + BTN + 'bg-brand-dark text-white hover:bg-brand-darkest" aria-label="Completar la cita de ' + esc(c.cliente_nombre) + '">Completar</button>' +
        '</div>';
    }

    return li +
      '<div class="min-w-0 flex-1 rounded-2xl border border-slate-200 border-l-4 bg-white p-4 ' +
        (hecha ? 'border-l-slate-300 opacity-60' : 'border-l-rose-300 shadow-soft') + '">' +
        '<div class="flex items-start gap-2">' +
          '<div class="min-w-0 flex-1">' +
            '<p class="truncate text-base font-semibold' + (c.estado === 'completada' ? ' line-through decoration-brand-darkest/30' : '') + '">' + esc(c.cliente_nombre) + '</p>' +
            '<p class="mt-0.5 truncate text-xs text-brand-darkest/55">' + esc(c.servicio || '') + ' · hasta ' + c.hasta +
              (c.origen === 'publica' ? ' · <span class="font-semibold text-brand-dark">Reservó online</span>' : '') + '</p>' +
          '</div>' +
          '<p class="shrink-0 text-sm font-semibold">' + pesos(c.precio) + '</p>' +
        '</div>' +
        acciones +
      '</div></li>';
  }

  function marcaAhora(ahora) {
    return '<li class="flex items-center gap-3 py-0.5" aria-label="Hora actual: ' + ahora + '">' +
      '<span class="w-11 shrink-0 text-right text-xs font-bold tabular-nums text-brand-dark">' + ahora + '</span>' +
      '<span class="h-2 w-2 shrink-0 rounded-full bg-brand-dark" aria-hidden="true"></span>' +
      '<span class="h-px min-w-0 flex-1 bg-brand-dark/40" aria-hidden="true"></span>' +
      '<span class="shrink-0 text-[10px] font-bold uppercase tracking-wide text-brand-dark">Ahora</span>' +
    '</li>';
  }

  function pintar() {
    $lista.removeAttribute('aria-busy');
    var todos = items();
    var ahora = esHoy() ? ahoraHHMM() : null;
    var visibles = 0, marcado = !ahora;
    $lista.innerHTML = todos.map(function (c) {
      if (filtro !== 'todas' && c.estado !== filtro) return '';
      /* La marca "Ahora" va antes del primer turno futuro, si ya pasó alguno */
      var marca = '';
      if (!marcado && c.hora > ahora) { marcado = true; if (visibles) marca = marcaAhora(ahora); }
      visibles++;
      return marca + tarjeta(c);
    }).join('');

    var d = horarioDelDia();
    $('vacio').textContent = !quien ? 'Nadie atiende todavía en esta sede. ' + (T.yo.rol === 'Admin' ? 'Suma a tu equipo desde Ajustes.' : 'Pídele al administrador que configure el equipo.')
      : filtro !== 'todas' ? 'No hay turnos con este filtro.'
      : d && !d.abierto ? 'El local no abre este día.'
      : 'No hay turnos este día.';
    $('vacio').classList.toggle('hidden', visibles > 0);

    $('n-reservadas').textContent = todos.filter(function (c) { return c.estado === 'reservada'; }).length;
    $('n-libres').textContent = todos.filter(function (c) { return c.estado === 'disponible'; }).length;
    if ($('n-atendidas')) $('n-atendidas').textContent = todos.filter(function (c) { return c.estado === 'completada'; }).length;
    $('sheet-eyebrow').textContent = profesional(quien) ? 'Agenda de ' + profesional(quien).nombre_completo : '';

    document.querySelectorAll('.filtro').forEach(function (b) {
      var activo = b.dataset.filtro === filtro;
      b.setAttribute('aria-pressed', activo);
      b.className = 'filtro min-w-0 truncate rounded-full px-1 text-sm font-semibold transition ' +
        (activo ? 'bg-brand-darkest text-white' : 'bg-slate-100 text-brand-darkest/60 hover:bg-slate-200');
    });
  }

  document.querySelectorAll('.filtro').forEach(function (b) {
    b.addEventListener('click', function () { filtro = b.dataset.filtro; pintar(); });
  });

  /* ── Acciones sobre la lista (delegación: la lista se repinta entera) ── */
  $lista.addEventListener('click', function (e) {
    var slot = e.target.closest('[data-agendar]');
    if (slot) { abrir(slot.dataset.agendar); return; }

    var b = e.target.closest('[data-accion]');
    if (!b) return;
    var c = citas.find(function (x) { return x.id_cita === Number(b.dataset.id); });
    if (!c) return;

    if (b.dataset.accion === 'completar') {
      abrirPago(c);
    } else if (b.dataset.accion === 'reabrir') {
      /* Deshacer también retira el cobro de la caja: se confirma */
      T.confirmar(
        '¿Deshacer el cobro de ' + c.cliente_nombre + '?',
        'La cita vuelve a "Reservada" y los ' + pesos(c.precio) + ' salen de la caja.',
        'Deshacer cobro'
      ).then(function (si) {
        if (!si) return;
        T.ocupado(b, T.api('DELETE', '/api/citas/' + c.id_cita + '/cobro')).then(function () {
          T.toast('Cita reabierta · cobro retirado de caja');
          return cargarAgenda();
        }).catch(T.fallo);
      });
    } else {
      /* Liberar cancela la cita y deja la hora libre: se confirma */
      T.confirmar(
        '¿Liberar el turno de ' + c.cliente_nombre + '?',
        'La cita se cancela y las ' + c.hora + ' vuelven a quedar reservables.',
        'Liberar turno'
      ).then(function (si) {
        if (!si) return;
        T.ocupado(b, T.api('POST', '/api/citas/' + c.id_cita + '/cancelar', {})).then(function () {
          T.toast('Turno de las ' + c.hora + ' liberado');
          return cargarAgenda();
        }).catch(T.fallo);
      });
    }
  });

  /* ══ Copiar link de reservas ══ */
  $('btn-copiar').addEventListener('click', function () {
    var link = this.dataset.link;
    /* ponytail: sin clipboard API (http o navegador viejo) mostramos el link para copiar a mano */
    if (!navigator.clipboard) { T.toast(link); return; }
    navigator.clipboard.writeText(link).then(
      function () { T.toast('✓ Link de reservas copiado'); },
      function () { T.toast(link); }
    );
  });

  /* ══ Agenda manual: la cita queda en la agenda que se está viendo ══ */
  var sheet = T.hoja($('sheet-cliente'));
  var form = $('form-reserva');
  var $hora = $('hora');
  var horaPedida = null, consultaHoras = 0;

  function serviciosDe() {
    var p = profesional(quien);
    return p ? p.servicios : [];
  }

  function llenarServicios() {
    $('servicios').innerHTML = serviciosDe().map(function (s) {
      return '<label class="flex min-h-[56px] cursor-pointer items-center gap-3 rounded-2xl border border-brand-light bg-white p-3 transition has-[:checked]:border-brand-dark has-[:checked]:bg-brand-lightest/50">' +
        '<input type="radio" name="servicio" value="' + s.id_servicio + '" required class="h-5 w-5 shrink-0 accent-brand-dark">' +
        '<span class="min-w-0 flex-1 truncate text-sm font-medium">' + esc(s.nombre) +
          '<span class="block text-xs font-normal text-brand-darkest/55">' + s.duracion_min + ' min</span></span>' +
        '<span class="shrink-0 text-sm font-semibold">' + pesos(s.precio) + '</span>' +
      '</label>';
    }).join('');
  }

  /* Horas libres para ese servicio (con su duración real), según la API */
  function llenarHoras() {
    var marcado = form.querySelector('input[name="servicio"]:checked');
    if (!marcado) return Promise.resolve();
    var n = ++consultaHoras;
    $hora.disabled = true;
    $hora.innerHTML = '<option value="">Buscando horas libres…</option>';
    return T.api('GET', '/api/agenda/disponibilidad?id_servicio=' + marcado.value + '&fecha=' + fecha() + '&id_profesional=' + quien)
      .then(function (d) {
        if (n !== consultaHoras) return;   /* llegó tarde: ya se eligió otro servicio */
        var horas = d.profesionales.length ? d.profesionales[0].horas : [];
        $hora.innerHTML = horas.length
          ? horas.map(function (x) { return '<option value="' + x + '">' + x + '</option>'; }).join('')
          : '<option value="">' + (d.abierto ? 'No quedan horas libres para este servicio' : 'El local no abre este día') + '</option>';
        $hora.disabled = horas.length === 0;
        if (horaPedida && horas.indexOf(horaPedida) >= 0) $hora.value = horaPedida;
      })
      .catch(function (e) {
        if (n !== consultaHoras) return;
        $hora.innerHTML = '<option value="">No se pudieron cargar las horas</option>';
        T.fallo(e);
      });
  }

  $('servicios').addEventListener('change', llenarHoras);

  function abrir(hora) {
    if (!serviciosDe().length) {
      T.toast(T.yo.rol === 'Admin' ? 'Crea primero un servicio en Inventario' : 'Este profesional no tiene servicios asignados', 'error');
      return;
    }
    horaPedida = hora || null;
    llenarServicios();
    form.reset();
    form.classList.remove('enviado');
    sheet.showModal();
    /* Primer servicio ya marcado y cursor en el nombre.
       Queda en 2 toques: el turno libre y "Agendar cita". */
    form.querySelector('input[name="servicio"]').checked = true;
    llenarHoras();
    $('nombre').focus();
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var datos = new FormData(form);
    var hora = String(datos.get('hora') || '');
    if (!hora) { T.toast('Elige una hora libre', 'error'); return; }
    T.ocupado($('btn-agendar'), T.api('POST', '/api/citas', {
      id_profesional: quien,
      id_servicio: Number(datos.get('servicio')),
      inicio: fecha() + 'T' + hora,
      cliente_nombre: String(datos.get('nombre')).trim(),
      cliente_telefono: String(datos.get('telefono')).trim()
    })).then(function (r) {
      sheet.close();
      T.toast('✓ ' + r.cita.cliente_nombre + ' agendado a las ' + r.cita.hora);
      return cargarAgenda();
    }).catch(function (err) {
      T.fallo(err);
      /* Pudo entrar otra reserva mientras la hoja estaba abierta */
      if (err.status === 409) llenarHoras();
    });
  });

  /* ══ Selector de pago (lo usan Venta rápida y Completar cita) ══
     Efectivo / Transferencia / Mixto. En mixto, al escribir una parte la otra se completa sola.
     cuerpo() devuelve {metodo} o {pagos: [...]}, o null si el mixto no cuadra con el total. */
  function crearPago(el, nombre) {
    var CHIP = 'flex min-h-[44px] min-w-0 cursor-pointer items-center justify-center rounded-xl border border-brand-light px-1 text-[13px] font-semibold transition has-[:checked]:border-brand-dark has-[:checked]:bg-brand-lightest has-[:checked]:text-brand-dark has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand';
    var CAMPO = 'mt-1 block w-full min-w-0 rounded-xl border border-brand-light bg-white px-3 text-base transition focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/25';
    el.innerHTML =
      '<div class="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Método de pago">' +
        ['efectivo', 'transferencia', 'mixto'].map(function (m) {
          return '<label class="' + CHIP + '"><input type="radio" name="' + nombre + '" value="' + m + '" class="sr-only">' +
            '<span class="truncate capitalize">' + m + '</span></label>';
        }).join('') +
      '</div>' +
      '<div data-mixto class="mt-2 hidden grid-cols-2 gap-2 rounded-2xl bg-slate-100 p-3">' +
        '<label class="min-w-0 text-xs font-medium">En efectivo<input data-ef type="number" inputmode="numeric" min="0" step="100" placeholder="0" class="' + CAMPO + '"></label>' +
        '<label class="min-w-0 text-xs font-medium">En transferencia<input data-tr type="number" inputmode="numeric" min="0" step="100" placeholder="0" class="' + CAMPO + '"></label>' +
      '</div>';

    var total = 0;
    var radios = el.querySelectorAll('input[type=radio]');
    var mixto = el.querySelector('[data-mixto]'), ef = el.querySelector('[data-ef]'), tr = el.querySelector('[data-tr]');
    var resto = function (v) { return Math.max(0, total - (Number(v) || 0)); };

    function metodo() { return el.querySelector('input[type=radio]:checked').value; }
    function mostrar() {
      var m = metodo() === 'mixto';
      mixto.classList.toggle('hidden', !m);
      mixto.classList.toggle('grid', m);
    }

    el.addEventListener('change', function (e) {
      if (e.target.type !== 'radio') return;
      mostrar();
      if (metodo() === 'mixto') { ef.value = ''; tr.value = ''; ef.focus(); }
    });
    ef.addEventListener('input', function () { tr.value = resto(ef.value); });
    tr.addEventListener('input', function () { ef.value = resto(tr.value); });

    return {
      reiniciar: function (t) { total = t; radios[0].checked = true; ef.value = ''; tr.value = ''; mostrar(); },
      /* El total de la venta cambia con el carrito: se reajusta la parte en transferencia */
      total: function (t) { total = t; if (ef.value !== '') tr.value = resto(ef.value); },
      cuerpo: function () {
        if (metodo() !== 'mixto') return { metodo: metodo() };
        var a = Number(ef.value) || 0, b = Number(tr.value) || 0;
        if (a <= 0 || b <= 0 || a + b !== total) {
          T.toast('Efectivo + transferencia deben sumar ' + pesos(total), 'error');
          ef.focus();
          return null;
        }
        return { pagos: [{ metodo: 'efectivo', monto: a }, { metodo: 'transferencia', monto: b }] };
      }
    };
  }

  /* ══ Completar cita: cobro → caja → estado (todo o nada, en el servidor) ══ */
  var sheetP = T.hoja($('sheet-pago'));
  var pagoCita = crearPago($('pago-cita'), 'metodo-cita');
  var citaPago = null;

  function abrirPago(c) {
    citaPago = c;
    $('pago-cliente').textContent = c.cliente_nombre;
    $('pago-servicio').textContent = (c.servicio || '') + ' · ' + c.hora;
    $('pago-total').textContent = pesos(c.precio);
    $('btn-pagar').textContent = 'Confirmar pago de ' + pesos(c.precio);

    /* Reparto fijo: el pago propio del profesional por ese servicio, o el del servicio */
    var p = profesional(c.id_profesional);
    var s = p && p.servicios.find(function (x) { return x.id_servicio === c.id_servicio; });
    var paga = T.pagoProfesional(c.precio, s && s.pago_profesional);
    var nombre = c.profesional || (p && p.nombre_completo) || '';
    var mio = c.id_profesional === T.yo.id;
    $('pago-reparto').textContent = paga
      ? (mio ? 'Recibes ' : 'Recibe ') + pesos(paga) + ' · Local ' + pesos(c.precio - paga)
      : 'Este servicio no tiene pago al profesional configurado: todo queda para el local.';
    $('pago-iniciales').textContent = T.iniciales(nombre);
    $('pago-atiende').textContent = 'Atiende ' + nombre + (mio ? ' · tu sesión' : '');
    pagoCita.reiniciar(c.precio);
    sheetP.showModal();
  }

  $('btn-pagar').addEventListener('click', function () {
    var c = citaPago;
    var cuerpo = c && pagoCita.cuerpo();
    if (!cuerpo) return;
    T.ocupado(this, T.api('POST', '/api/citas/' + c.id_cita + '/cobrar', cuerpo)).then(function () {
      sheetP.close();
      T.toast('✓ Cita completada · ' + pesos(c.precio) + ' en caja');
      return cargarAgenda();
    }).catch(T.fallo);
  });

  /* ══ Venta rápida ══
     carrito[id_producto] = cantidad. El stock se descuenta al cobrar, en el servidor. */
  var sheetV = T.hoja($('sheet-venta'));
  var pagoVenta = crearPago($('pago-venta'), 'metodo-venta');
  var productos = [];
  var carrito = {};

  function producto(id) { return productos.find(function (p) { return p.id_producto === id; }); }
  function enCarrito() { return Object.keys(carrito).map(Number); }

  function sinTildes(s) {
    return String(s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  }

  /* Productos a mostrar en la cuadrícula (máx. 6 = 2 filas de 3):
     con texto escrito, los que coinciden por nombre; si no, los más vendidos. */
  function vitrina() {
    var q = sinTildes($('codigo').value.trim());
    var buscando = /[a-z]/.test(q);
    var lista = productos.slice();
    if (buscando) lista = lista.filter(function (p) { return sinTildes(p.nombre).indexOf(q) >= 0; });
    else lista.sort(function (a, b) { return (b.vendidos || 0) - (a.vendidos || 0); });
    return { buscando: buscando, lista: lista.slice(0, 6) };
  }

  function pintarVenta() {
    var v = vitrina();
    $('productos-titulo').textContent = !productos.length ? 'Todavía no hay productos en el inventario'
      : !v.buscando ? 'Más vendidos' : v.lista.length ? 'Resultados' : 'Ningún producto con ese nombre';
    $('productos').innerHTML = v.lista.map(function (p) {
      var n = carrito[p.id_producto] || 0, quedan = p.stock - n;
      return '<button type="button" data-producto="' + p.id_producto + '"' + (quedan <= 0 ? ' disabled' : '') +
        ' class="relative min-w-0 rounded-2xl border p-2.5 text-center transition active:scale-95 disabled:opacity-40 ' +
        (n ? 'border-brand-dark bg-brand-lightest/60' : 'border-brand-light bg-white hover:bg-slate-50') + '">' +
        (n ? '<span class="absolute right-1.5 top-1.5 grid h-5 min-w-[20px] place-items-center rounded-full bg-brand-dark px-1 text-[11px] font-bold text-white">' + n + '</span>' : '') +
        '<span class="block text-2xl" aria-hidden="true">' + esc(p.emoji || '📦') + '</span>' +
        '<span class="mt-1 block truncate text-xs font-semibold">' + esc(p.nombre) + '</span>' +
        '<span class="block text-xs text-brand-dark">' + pesos(p.precio) + '</span>' +
        '<span class="block text-[10px] text-brand-darkest/45">' + (p.stock ? 'Quedan ' + quedan : 'Agotado') + '</span>' +
      '</button>';
    }).join('');

    var total = 0;
    $('carrito').innerHTML = enCarrito().map(function (id) {
      var p = producto(id), sub = p.precio * carrito[id];
      total += sub;
      return '<li class="flex items-center gap-2">' +
        '<button type="button" data-quitar="' + id + '" class="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-white text-lg font-semibold" aria-label="Quitar una unidad de ' + esc(p.nombre) + '">−</button>' +
        '<span class="min-w-0 flex-1 truncate text-sm">' + carrito[id] + ' × ' + esc(p.nombre) + '</span>' +
        '<span class="shrink-0 text-sm font-semibold">' + pesos(sub) + '</span>' +
      '</li>';
    }).join('');

    pagoVenta.total(total);
    $('carrito-vacio').classList.toggle('hidden', total > 0);
    $('total').textContent = pesos(total);
    $('btn-cobrar').disabled = total === 0;
    $('btn-cobrar').textContent = total ? 'Cobrar ' + pesos(total) : 'Cobrar';
  }

  function agregar(p) {
    if (!productos.some(function (x) { return x.id_producto === p.id_producto; })) productos.push(p);
    if ((carrito[p.id_producto] || 0) >= p.stock) { T.toast('No quedan más unidades de ' + p.nombre, 'error'); return; }
    carrito[p.id_producto] = (carrito[p.id_producto] || 0) + 1;
    pintarVenta();
  }

  function agregarPorCodigo(codigo) {
    codigo = String(codigo).trim();
    if (!codigo) return;
    var p = productos.find(function (x) { return x.codigo_barras === codigo; });
    if (p) { if (navigator.vibrate) navigator.vibrate(40); agregar(p); return; }
    T.api('GET', '/api/productos/codigo/' + encodeURIComponent(codigo)).then(function (r) {
      if (navigator.vibrate) navigator.vibrate(40);
      agregar(r.producto);
    }).catch(function (e) {
      T.toast(e.status === 404 ? 'El código ' + codigo + ' no está en el inventario' : e.message, 'error');
    });
  }

  $('btn-venta').addEventListener('click', function () {
    carrito = {};
    $('codigo').value = '';
    pagoVenta.reiniciar(0);
    $('productos').innerHTML = '<div class="esqueleto h-24"></div><div class="esqueleto h-24"></div><div class="esqueleto h-24"></div>';
    $('productos-titulo').textContent = 'Cargando productos…';
    sheetV.showModal();
    T.api('GET', '/api/productos').then(function (r) {
      productos = r.productos;
      pintarVenta();
    }).catch(function (e) {
      $('productos').innerHTML = '';
      $('productos-titulo').textContent = 'No se pudieron cargar los productos';
      T.fallo(e);
    });
  });

  $('codigo').addEventListener('input', pintarVenta);

  $('productos').addEventListener('click', function (e) {
    var b = e.target.closest('[data-producto]');
    if (b) agregar(producto(Number(b.dataset.producto)));
  });

  $('carrito').addEventListener('click', function (e) {
    var b = e.target.closest('[data-quitar]');
    if (!b) return;
    var id = Number(b.dataset.quitar);
    if (--carrito[id] <= 0) delete carrito[id];
    pintarVenta();
  });

  $('form-codigo').addEventListener('submit', function (e) {
    e.preventDefault();
    var v = vitrina();
    if (!v.buscando) agregarPorCodigo($('codigo').value);
    else if (v.lista.length === 1) agregar(v.lista[0]);   /* Enter con un solo resultado lo agrega */
    else return;                                          /* varios o ninguno: se elige tocando */
    $('codigo').value = '';
    pintarVenta();
  });

  $('btn-cobrar').addEventListener('click', function () {
    /* Primero se valida el pago: si el mixto no cuadra, no se envía nada */
    var cuerpo = pagoVenta.cuerpo();
    if (!cuerpo) return;
    cuerpo.items = enCarrito().map(function (id) { return { id_producto: id, cantidad: carrito[id] }; });
    T.ocupado(this, T.api('POST', '/api/ventas', cuerpo)).then(function (r) {
      sheetV.close();
      T.toast('✓ Venta de ' + pesos(r.venta.total) + ' registrada en caja');
      if (T.esCaja) cargarAgenda();   /* "En caja" cambió */
    }).catch(T.fallo);
  });

  /* ── Escáner: la librería (375 KB) solo se descarga al tocar "Escanear" ── */
  var lector = null, ultimo = '', ultimoT = 0;

  function cargarLector() {
    return new Promise(function (ok, mal) {
      if (window.Html5Qrcode) return ok();
      var s = document.createElement('script');
      s.src = '/static/lib/html5-qrcode.min.js';
      s.onload = ok;
      s.onerror = mal;
      document.head.appendChild(s);
    });
  }

  function detener() {
    $('lector').classList.add('hidden');
    $('btn-escanear').textContent = 'Escanear';
    if (!lector) return;
    var l = lector;
    lector = null;
    /* stop() lanza o rechaza si la cámara nunca arrancó: en ambos casos no hay nada que apagar */
    try { l.stop().then(function () { l.clear(); }).catch(function () {}); } catch (e) {}
  }

  $('btn-escanear').addEventListener('click', function () {
    var btn = this;
    if (lector) { detener(); return; }

    /* Los navegadores solo entregan la cámara en HTTPS o localhost */
    if (!window.isSecureContext || !navigator.mediaDevices) {
      T.toast('La cámara necesita HTTPS. Escribe el código.', 'error');
      $('codigo').focus();
      return;
    }

    btn.setAttribute('aria-busy', 'true');
    cargarLector().then(function () {
      /* Desde aquí el botón ya sirve para cancelar, aunque la cámara tarde o pida permiso */
      btn.removeAttribute('aria-busy');
      btn.textContent = 'Detener';
      var F = window.Html5QrcodeSupportedFormats;
      $('lector').classList.remove('hidden');
      lector = new window.Html5Qrcode('lector', {
        formatsToSupport: [F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_128, F.CODE_39],
        verbose: false
      });
      return lector.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 240, height: 120 } },
        function (codigo) {
          /* La cámara lee el mismo código muchas veces por segundo: una sola unidad cada 2 s */
          var t = Date.now();
          if (codigo === ultimo && t - ultimoT < 2000) return;
          ultimo = codigo; ultimoT = t;
          agregarPorCodigo(codigo);
        },
        function () { /* fotograma sin código: normal */ }
      );
    }).catch(function () {
      btn.removeAttribute('aria-busy');
      detener();
      T.toast('No se pudo abrir la cámara. Escribe el código.', 'error');
    });
  });

  sheetV.addEventListener('close', detener);

  cargarTodo();

  /* Lo que otro del equipo (o una reserva online) cambió aparece al volver a la
     pestaña y cada minuto mientras está a la vista. */
  T.alVolver(function () { pintarDia(); cargarAgenda(); }, 60000);
})();
