/* Turnio — página pública de reservas (T8): /r/<slug>.
   El cliente elige sede (si hay varias), servicio, día, hora y profesional, y
   deja nombre y WhatsApp. Solo consume /api/publico/<slug>: horas libres,
   nunca citas ni datos de otros clientes. Todo HTML pasa por T.h/T.pintar. */

(function () {
  'use strict';

  var T = window.Turnio;
  var $ = T.$;
  var slug = document.body.dataset.slug;
  var API = '/api/publico/' + encodeURIComponent(slug);
  var form = $('form-reserva');
  var DIAS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];
  var MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  var RADIO = 'flex cursor-pointer items-center gap-3 rounded-2xl border border-brand-light bg-white p-3 transition has-[:checked]:border-brand-dark has-[:checked]:bg-brand-lightest/50 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand';

  var datos = null;        /* respuesta de /api/publico/<slug> */
  var hoy = null;          /* Date UTC del día de hoy en Colombia (lo dice el servidor) */
  var semana = 0;          /* cuántas semanas adelante se está viendo */
  var libres = null;       /* disponibilidad del día elegido */
  var pedido = null;       /* AbortController de la consulta de horas en curso */

  /* ── Fechas: todo en UTC para que la zona del celular no mueva el día ── */
  function fecha(iso) {
    var p = iso.split('-');
    return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
  }
  function iso(d) { return d.toISOString().slice(0, 10); }
  function masDias(d, n) { return new Date(d.getTime() + n * 86400000); }
  function diaSemana(d) { return (d.getUTCDay() + 6) % 7; }   /* 0 = lunes, como horarios_sede */
  function fechaLarga(d) { return DIAS[d.getUTCDay()] + ' ' + d.getUTCDate() + ' de ' + MESES[d.getUTCMonth()]; }

  function elegido(nombre) {
    var r = form.querySelector('input[name="' + nombre + '"]:checked');
    return r ? r.value : '';
  }
  function sede() {
    var id = Number(elegido('sede')) || (datos.sedes[0] && datos.sedes[0].id_sede);
    return datos.sedes.filter(function (s) { return s.id_sede === id; })[0];
  }
  function servicio() {
    var id = Number(elegido('servicio'));
    return sede().servicios.filter(function (s) { return s.id_servicio === id; })[0];
  }
  function profesionales() {
    var s = servicio();
    return s ? sede().profesionales.filter(function (p) { return p.servicios.indexOf(s.id_servicio) >= 0; }) : [];
  }

  function avatar(p, libre) {
    return T.h`<span class="grid h-10 w-10 shrink-0 place-items-center rounded-full text-xs font-bold text-white ${libre ? 'bg-brand-dark' : 'bg-slate-400'}" aria-hidden="true">${T.iniciales(p.nombre)}</span>`;
  }

  function aviso(titulo, detalle, whatsapp) {
    $('cargando').classList.add('hidden');
    form.classList.add('hidden');
    var a = $('aviso');
    T.pintar(a, T.h`
      <p class="text-base font-semibold">${titulo}</p>
      <p class="mt-1 text-sm text-brand-darkest/70">${detalle}</p>
      ${whatsapp && T.h`<a href="${'https://wa.me/' + wa(whatsapp)}" target="_blank" rel="noopener" class="mt-5 flex min-h-[52px] items-center justify-center rounded-2xl bg-emerald-600 px-4 text-base font-semibold text-white transition hover:bg-emerald-700">Escribir por WhatsApp</a>`}`);
    a.classList.remove('hidden');
  }

  /* WhatsApp de Colombia: 10 dígitos que empiezan por 3 → con el 57 delante. */
  function wa(tel) {
    var t = String(tel || '').replace(/\D/g, '');
    return t.length === 10 && t.charAt(0) === '3' ? '57' + t : t;
  }

  /* ── Cabecera: dirección y si hoy está abierto ── */
  function pintarCabecera() {
    var s = sede();
    $('sede-info').textContent = [datos.sedes.length > 1 ? s.nombre : '', s.direccion].filter(Boolean).join(' · ');
    var h = s.horario[diaSemana(hoy)];
    var e = $('estado-hoy');
    e.className = 'mt-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ' +
      (h.abierto ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-brand-darkest/70');
    T.pintar(e, T.h`<span class="h-1.5 w-1.5 rounded-full ${h.abierto ? 'bg-emerald-500' : 'bg-slate-400'}" aria-hidden="true"></span>${h.abierto ? 'Hoy atiende de ' + h.abre + ' a ' + h.cierra : 'Hoy no atiende'}`);
  }

  /* ── 1. Sede ── */
  function pintarSedes() {
    var varias = datos.sedes.length > 1;
    $('paso-sede').classList.toggle('hidden', !varias);
    if (!varias) return;
    var antes = elegido('sede') || String(datos.sedes[0].id_sede);
    T.pintar($('sedes'), datos.sedes.map(function (s) {
      return T.h`<label class="${RADIO} min-h-[56px]">
        <input type="radio" name="sede" value="${s.id_sede}" required class="h-5 w-5 shrink-0 accent-brand-dark"${String(s.id_sede) === antes ? T.h` checked` : ''}>
        <span class="min-w-0 flex-1 text-sm font-medium">${s.nombre}${s.direccion && T.h`<span class="block truncate text-xs font-normal text-brand-darkest/70">${s.direccion}</span>`}</span>
      </label>`;
    }));
  }

  /* ── 2. Servicio ── */
  function pintarServicios() {
    var lista = sede().servicios;
    T.pintar($('servicios'), lista.length ? lista.map(function (s) {
      return T.h`<label class="${RADIO} min-h-[56px]">
        <input type="radio" name="servicio" value="${s.id_servicio}" required class="h-5 w-5 shrink-0 accent-brand-dark">
        <span class="min-w-0 flex-1 truncate text-sm font-medium">${s.nombre}<span class="block text-xs font-normal text-brand-darkest/70">${s.duracion_min} min</span></span>
        <span class="shrink-0 text-sm font-semibold">${T.pesos(s.precio)}</span>
      </label>`;
    }) : T.h`<p class="text-sm text-brand-darkest/70">Esta sede aún no publica servicios para reservar en línea.</p>`);
  }

  /* ── 3. Día: semanas de 7 días desde hoy, hasta max_dias ── */
  function pintarDias() {
    var s = sede(), inicio = masDias(hoy, semana * 7), ultimo = masDias(hoy, datos.max_dias);
    var antes = elegido('dia');
    $('mes').textContent = MESES[inicio.getUTCMonth()] + ' ' + inicio.getUTCFullYear();
    $('semana-ant').disabled = semana === 0;
    $('semana-sig').disabled = masDias(inicio, 7) > ultimo;
    var celdas = [];
    for (var i = 0; i < 7; i++) {
      var d = masDias(inicio, i), valor = iso(d);
      var abierto = d <= ultimo && s.horario[diaSemana(d)].abierto;
      celdas.push(T.h`<label class="flex min-h-[60px] min-w-0 cursor-pointer flex-col items-center justify-center rounded-xl border border-brand-light bg-white text-sm transition has-[:checked]:border-brand-dark has-[:checked]:bg-brand-lightest has-[:checked]:text-brand-dark has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand has-[:disabled]:cursor-not-allowed has-[:disabled]:bg-slate-200/60 has-[:disabled]:text-brand-darkest/35"${!abierto && d <= ultimo ? T.h` title="No atiende"` : ''}>
        <input type="radio" name="dia" value="${valor}" class="sr-only" aria-label="${fechaLarga(d)}"${abierto ? '' : T.h` disabled`}${abierto && valor === antes ? T.h` checked` : ''}>
        <span class="text-[10px] font-medium uppercase">${i === 0 && semana === 0 ? 'hoy' : DIAS[d.getUTCDay()]}</span>
        <span class="font-semibold tabular-nums">${d.getUTCDate()}</span>
      </label>`);
    }
    T.pintar($('dias'), celdas);
  }

  /* ── 4. Hora: una hora se ofrece si al menos un profesional está libre ──
     `refrescar`: la misma consulta otra vez sin borrar lo elegido; si la hora
     elegida ya no está libre, se avisa. */
  function cargarHoras(refrescar) {
    var s = servicio(), dia = elegido('dia'), antes = elegido('hora');
    if (!refrescar) {
      libres = null;
      $('paso-hora').disabled = $('paso-pro').disabled = true;
      T.pintar($('horas'), '');
      pintarPros();
    }
    if (!s || !dia) {
      $('horas-ayuda').textContent = s ? 'Elige un día.' : 'Elige un servicio y un día.';
      return;
    }
    if (!refrescar) $('horas-ayuda').textContent = 'Buscando horas libres…';
    if (pedido) pedido.abort();
    pedido = new AbortController();
    var url = API + '/disponibilidad?id_sede=' + sede().id_sede + '&id_servicio=' + s.id_servicio + '&fecha=' + dia;
    T.api('GET', url, null, { signal: pedido.signal }).then(function (d) {
      libres = d;
      pintarHoras(antes);
      if (antes && !elegido('hora')) {
        T.aviso({ tipo: 'aviso', titulo: 'Esa hora se acaba de ocupar', detalle: 'Alguien reservó las ' + antes + ' hace un momento. Elige otra de las horas libres.' });
      }
    }).catch(function (e) {
      if (e && e.name === 'AbortError') return;
      var a = (e && e.aviso) || T.explicar(0);
      $('horas-ayuda').textContent = 'No pudimos cargar las horas. ' + a.detalle;
    });
  }

  function cuentaPorHora() {
    var cuenta = {};
    (libres ? libres.profesionales : []).forEach(function (p) {
      p.horas.forEach(function (h) { cuenta[h] = (cuenta[h] || 0) + 1; });
    });
    return cuenta;
  }

  function pintarHoras(antes) {
    var cuenta = cuentaPorHora();
    var horas = Object.keys(cuenta).sort();
    $('paso-hora').disabled = !horas.length;
    $('horas-ayuda').textContent = horas.length
      ? fechaLarga(fecha(libres.fecha)).replace(/^./, function (c) { return c.toUpperCase(); }) + ':'
      : (libres.abierto ? 'Ya no quedan horas libres ese día. Prueba otro.' : 'Ese día no atiende. Prueba otro.');
    T.pintar($('horas'), horas.map(function (h) {
      var n = cuenta[h];
      return T.h`<label class="flex min-h-[52px] min-w-0 cursor-pointer flex-col items-center justify-center rounded-xl border border-brand-light bg-white px-1 text-sm font-semibold tabular-nums transition has-[:checked]:border-brand-dark has-[:checked]:bg-brand-lightest has-[:checked]:text-brand-dark has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand">
        <input type="radio" name="hora" value="${h}" class="sr-only"${h === antes ? T.h` checked` : ''}>${h}
        <span class="text-[10px] font-medium text-emerald-700">${n === 1 ? '1 libre' : n + ' libres'}</span>
      </label>`;
    }));
    return pintarPros();
  }

  /* ── 5. Profesional: los que hacen el servicio; libre u ocupado a esa hora ── */
  function pintarPros() {
    var hora = elegido('hora'), antes = elegido('profesional');
    if (!hora || !libres) {
      $('paso-pro').disabled = true;
      T.pintar($('pros'), '');
      $('pros-ayuda').textContent = 'Elige una hora para ver quién está libre.';
      pintarResumen();
      return '';
    }
    var horasDe = {};
    libres.profesionales.forEach(function (p) { horasDe[p.id_profesional] = p.horas; });
    var lista = profesionales().map(function (p) {
      return { p: p, libre: (horasDe[p.id_profesional] || []).indexOf(hora) >= 0 };
    });
    var nLibres = lista.filter(function (x) { return x.libre; }).length;
    if (!antes || (antes !== 'cualquiera' && !lista.some(function (x) { return x.libre && String(x.p.id_profesional) === antes; }))) {
      antes = nLibres === 1 ? String(lista.filter(function (x) { return x.libre; })[0].p.id_profesional) : 'cualquiera';
    }
    $('paso-pro').disabled = false;
    $('pros-ayuda').textContent = 'A las ' + hora + ':';
    var filas = lista.map(function (x) {
      var p = x.p;
      return T.h`<label class="flex min-h-[60px] items-center gap-3 rounded-2xl border p-3 transition ${x.libre
          ? 'cursor-pointer border-brand-light bg-white has-[:checked]:border-brand-dark has-[:checked]:bg-brand-lightest/50 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand'
          : 'cursor-not-allowed border-slate-200 bg-slate-200/50'}">
        <input type="radio" name="profesional" value="${p.id_profesional}" class="h-5 w-5 shrink-0 accent-brand-dark"${x.libre ? '' : T.h` disabled`}${x.libre && String(p.id_profesional) === antes ? T.h` checked` : ''}>
        ${avatar(p, x.libre)}
        <span class="min-w-0 flex-1 truncate text-sm font-semibold${x.libre ? '' : ' text-brand-darkest/70'}">${p.nombre}</span>
        <span class="shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${x.libre ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-200 text-brand-darkest/70'}">${x.libre ? 'Libre' : 'Ocupado'}</span>
      </label>`;
    });
    if (nLibres > 1) {
      filas.unshift(T.h`<label class="${RADIO} min-h-[60px]">
        <input type="radio" name="profesional" value="cualquiera" class="h-5 w-5 shrink-0 accent-brand-dark"${antes === 'cualquiera' ? T.h` checked` : ''}>
        <span class="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-brand-lightest text-brand-dark" aria-hidden="true">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.5"></circle><path d="M2.5 20a6.5 6.5 0 0 1 13 0"></path><path d="M16 4.5a3.5 3.5 0 0 1 0 7"></path><path d="M18 14.5a6.5 6.5 0 0 1 3.5 5.5"></path></svg>
        </span>
        <span class="min-w-0 flex-1 truncate text-sm font-semibold">Cualquiera disponible<span class="block text-xs font-normal text-brand-darkest/70">${nLibres} libres a esa hora</span></span>
      </label>`);
    }
    T.pintar($('pros'), filas);
    pintarResumen();
    return antes;
  }

  function pintarResumen() {
    var s = servicio(), dia = elegido('dia'), hora = elegido('hora'), r = $('resumen');
    r.classList.toggle('hidden', !(s && dia && hora));
    if (s && dia && hora) r.textContent = s.nombre + ' · ' + fechaLarga(fecha(dia)) + ' a las ' + hora + ' · ' + T.pesos(s.precio);
  }

  /* ── Cambios en el formulario ── */
  form.addEventListener('change', function (e) {
    var n = e.target.name;
    if (n === 'sede') {
      $('paso-dia').disabled = true;
      pintarCabecera();
      pintarServicios();
      pintarDias();
      cargarHoras();
    } else if (n === 'servicio') {
      $('paso-dia').disabled = false;
      cargarHoras();
    } else if (n === 'dia') {
      cargarHoras();
    } else if (n === 'hora') {
      pintarPros();
    } else if (n === 'profesional') {
      pintarResumen();
    }
  });

  $('semana-ant').addEventListener('click', function () { semana--; pintarDias(); cargarHoras(); });
  $('semana-sig').addEventListener('click', function () { semana++; pintarDias(); cargarHoras(); });

  /* Falta un paso: no es un error, es la guía de qué sigue (docs/ux-avisos.md). */
  function falta(titulo, detalle, id) {
    T.aviso({ tipo: 'aviso', titulo: titulo, detalle: detalle });
    var el = id && $(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  var AYUDA_CAMPO = {
    nombre: 'Escribe tu nombre para que sepan quién llega.',
    telefono: 'Escribe tu WhatsApp de 10 dígitos, ej. 300 123 4567. Ahí te pueden confirmar la cita.'
  };

  /* Errores al reservar, dichos para el cliente (no para el equipo del negocio). */
  function falloReserva(err) {
    if (err && err.status === 409) {
      T.aviso({ tipo: 'error', titulo: 'Esa hora ya no está libre', detalle: 'Alguien la reservó hace un momento. Elige otra de las horas que quedan.' });
    } else if (err && err.status === 429) {
      T.aviso({ tipo: 'aviso', titulo: 'No puedes reservar más por ahora', detalle: err.message });
    } else if (err && err.status === 403) {
      T.aviso({ tipo: 'aviso', titulo: 'Reservas en línea en pausa', detalle: err.message || 'Escríbele al negocio por WhatsApp para pedir tu cita.' });
    } else {
      T.fallo(err, form);
    }
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (!servicio()) return falta('Falta elegir el servicio', 'Toca el que quieres en la lista de servicios.', 'servicios');
    if (!elegido('dia')) return falta('Falta elegir el día', 'Toca un día de la semana; con las flechas ves otras semanas.', 'dias');
    if (!elegido('hora')) return falta('Falta elegir la hora', 'Toca una de las horas libres de ese día.', 'horas');
    if (!elegido('profesional')) return falta('Falta elegir quién te atiende', 'Toca un nombre, o «Cualquiera disponible» si te da igual.', 'pros');
    form.classList.add('enviado');
    if (!form.checkValidity()) {
      var malo = form.querySelector('#nombre:invalid, #telefono:invalid');
      if (malo) T.marcarCampo(malo, AYUDA_CAMPO[malo.id]);
      return falta('Faltan tus datos', 'Escribe tu nombre y tu WhatsApp completo para apartar la cita.');
    }
    var d = new FormData(form);
    var cuerpo = {
      id_sede: sede().id_sede,
      id_servicio: servicio().id_servicio,
      id_profesional: d.get('profesional'),
      inicio: d.get('dia') + 'T' + d.get('hora'),
      cliente_nombre: String(d.get('nombre')).trim(),
      cliente_telefono: String(d.get('telefono')).trim(),
      sitio_web: d.get('sitio_web') || ''
    };
    T.ocupado($('btn-reservar'), T.api('POST', API + '/reservas', cuerpo)).then(function (r) {
      exito(r.cita);
    }).catch(function (err) {
      falloReserva(err);
      /* Otro cliente ganó la hora: se vuelven a pedir las horas libres. */
      if (err && err.status === 409) cargarHoras(true);
    });
  });

  function exito(c) {
    T.pintar($('reserva-detalle'), T.h`
      <p class="font-semibold text-brand-darkest">${c.servicio} · ${T.pesos(c.precio)}</p>
      <p class="first-letter:uppercase">${c.fecha_texto} de ${c.hora} a ${c.hasta}</p>
      <p>Con ${c.profesional}</p>
      ${datos.sedes.length > 1 && T.h`<p>${c.sede}</p>`}
      ${c.direccion && T.h`<p>${c.direccion}</p>`}`);
    $('btn-whatsapp').href = c.whatsapp_url;
    form.classList.add('hidden');
    var ok = $('reserva-ok');
    ok.classList.remove('hidden');
    ok.focus();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  $('btn-otra').addEventListener('click', function () {
    var nombre = $('nombre').value, telefono = $('telefono').value;
    form.reset();
    $('nombre').value = nombre;
    $('telefono').value = telefono;
    form.classList.remove('hidden', 'enviado');
    $('reserva-ok').classList.add('hidden');
    $('paso-dia').disabled = true;
    pintarSedes();
    pintarServicios();
    pintarDias();
    cargarHoras();
  });

  /* Volver a la pestaña refresca las horas: otro cliente pudo tomar una. */
  T.alVolver(function () {
    if (!form.classList.contains('hidden') && elegido('dia') && servicio()) cargarHoras(true);
  }, 60000);

  /* ── Arranque ── */
  var ini = $('iniciales');
  if (ini) ini.textContent = T.iniciales($('negocio').textContent);

  T.api('GET', API).then(function (d) {
    datos = d;
    hoy = fecha(d.hoy);
    if (!d.sedes.length) return aviso('Todavía no hay sedes', 'Este negocio aún no abre su agenda en línea. Escríbele por WhatsApp para pedir tu cita.', d.negocio.whatsapp);
    pintarSedes();
    pintarCabecera();
    if (!d.negocio.recibe_reservas) {
      return aviso('Reservas en línea en pausa', 'Este negocio no está recibiendo reservas en línea por ahora. Escríbele por WhatsApp.', sede().whatsapp);
    }
    pintarServicios();
    pintarDias();
    $('cargando').classList.add('hidden');
    form.classList.remove('hidden');
  }).catch(function (e) {
    T.errorCarga($('cargando'), e, function () { location.reload(); });
    $('cargando').classList.remove('space-y-3');
  });
})();
