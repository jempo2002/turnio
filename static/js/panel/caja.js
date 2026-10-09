/* Turnio — Caja del día: totales, división por profesional, salidas y cierre.
   Datos: /api/caja, /api/caja/gastos, /api/caja/cierre, /api/servicios (T4, T5). */

(function () {
  'use strict';

  var T = window.Turnio, $ = T.$, pesos = T.pesos;

  var POR_PAGINA = 6;
  var pagina = 0;
  var caja = null;          /* resumen del día que manda la API */
  var servicios = [];

  $('fecha').textContent = new Date().toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' });

  function cerrada() { return caja && caja.estado === 'cerrada'; }

  function cargar() {
    return T.api('GET', '/api/caja').then(function (r) {
      caja = r.caja;
      pintar();
    }).catch(function (e) {
      if (caja) { T.fallo(e); return; }
      T.errorCarga($('contenido'), e, function () { location.reload(); });
    });
  }

  function pintar() {
    $('contenido').removeAttribute('aria-busy');
    $('total').textContent = pesos(caja.ingresos - caja.salidas);
    $('ingresos').textContent = pesos(caja.ingresos);
    $('salidas').textContent = pesos(caja.salidas);
    $('efectivo').textContent = pesos(caja.efectivo_esperado);
    $('efectivo-nota').textContent = caja.base ? 'En el cajón, con la base de ' + pesos(caja.base) : 'Debe estar en el cajón';
    $('transferencia').textContent = pesos(caja.transferencias);
    $('local').textContent = pesos(caja.local);

    /* Reparto: lo que gana cada quien quedó fijado en cada cobro al completar la cita */
    T.pintar($('profesionales'), caja.profesionales.length ? caja.profesionales.map(function (p) {
      return T.h`<li class="flex items-center gap-3 rounded-2xl bg-slate-100 p-3">
        <span class="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-brand-dark text-xs font-bold text-white">${T.iniciales(p.nombre)}</span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold">${p.nombre}</p>
          <p class="truncate text-xs text-brand-darkest/70">Generó ${pesos(p.total)} · ${p.citas}${p.citas === 1 ? ' cita' : ' citas'}</p>
        </div>
        <div class="shrink-0 text-right">
          <p class="text-base font-semibold text-brand-dark">${pesos(p.pago)}</p>
          <p class="text-[11px] text-brand-darkest/70">recibe</p>
        </div>
      </li>`;
    }) : T.h`<li class="rounded-2xl bg-slate-100 p-3 text-xs text-brand-darkest/70">Todavía no se ha cobrado ninguna cita hoy.</li>`);

    /* Cerrada: arqueo arriba y nada más se puede registrar ese día */
    var c = $('cerrada');
    c.classList.toggle('hidden', !cerrada());
    if (cerrada()) {
      var dif = caja.cierre.diferencia;
      T.pintar(c, T.h`<p class="text-xs font-semibold uppercase tracking-wide text-brand-darkest/70">Caja cerrada${caja.cierre.hora ? ' · ' + caja.cierre.hora.slice(11) : ''}</p>
        <p class="mt-1 text-sm">Contado <strong class="font-semibold">${pesos(caja.cierre.contado)}</strong> · ${
          dif === 0 ? T.h`<span class="font-semibold text-emerald-700">cuadró exacto</span>`
            : dif > 0 ? T.h`<span class="font-semibold text-amber-700">sobran ${pesos(dif)}</span>`
            : T.h`<span class="font-semibold text-rose-700">faltan ${pesos(-dif)}</span>`}</p>
        ${caja.cierre.observaciones && T.h`<p class="mt-1 text-xs text-brand-darkest/70">${caja.cierre.observaciones}</p>`}
        ${T.yo.rol === 'Admin' && T.h`<button type="button" id="btn-reabrir" class="mt-3 rounded-xl border border-brand-light px-4 text-sm font-semibold text-brand-dark transition hover:bg-brand-lightest/50">Reabrir caja</button>`}`);
    }
    $('btn-salida').disabled = cerrada();
    $('btn-cierre').disabled = cerrada();

    pintarMovimientos();
  }

  /* ══ Movimientos paginados (la API ya los manda del más reciente al más viejo) ══ */
  function accion(m) {
    if (cerrada()) return '';
    if (m.categoria === 'gasto') {
      return T.h`<button type="button" data-borrar="${m.id_movimiento}" class="shrink-0 rounded-lg px-2 text-xs font-medium text-brand-darkest/70 transition hover:bg-rose-50 hover:text-rose-700" aria-label="Deshacer salida ${m.concepto}">Deshacer</button>`;
    }
    if (m.categoria === 'producto') {
      return T.h`<button type="button" data-anular="${m.id_venta}" class="shrink-0 rounded-lg px-2 text-xs font-medium text-brand-darkest/70 transition hover:bg-rose-50 hover:text-rose-700" aria-label="Anular venta ${m.concepto}">Anular</button>`;
    }
    return '';
  }

  function pintarMovimientos() {
    var movs = caja.movimientos;
    var total = movs.length;
    var paginas = Math.max(1, Math.ceil(total / POR_PAGINA));
    pagina = Math.min(pagina, paginas - 1);   /* si se borró el último de una página */

    T.pintar($('movimientos'), movs.slice(pagina * POR_PAGINA, (pagina + 1) * POR_PAGINA).map(function (m) {
      var esIngreso = m.tipo === 'ingreso';
      return T.h`<li class="flex items-center gap-3 py-3">
        <span class="grid h-9 w-9 shrink-0 place-items-center rounded-full ${esIngreso ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-600'}">
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${
          esIngreso ? T.h`<path d="M12 19V5M5 12l7-7 7 7"></path>` : T.h`<path d="M12 5v14M5 12l7 7 7-7"></path>`}</svg>
        </span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-medium">${m.concepto}</p>
          <p class="truncate text-xs text-brand-darkest/70">${m.hora} · <span class="capitalize">${m.metodo}</span>${m.profesional ? ' · ' + m.profesional : ''}</p>
        </div>
        <p class="shrink-0 text-sm font-semibold ${esIngreso ? 'text-emerald-700' : 'text-rose-700'}">${esIngreso ? '+' : '−'}${pesos(m.monto)}</p>
        ${accion(m)}
      </li>`;
    }));

    $('mov-vacio').classList.toggle('hidden', total > 0);
    $('mov-cuenta').textContent = total + (total === 1 ? ' movimiento' : ' movimientos');
    $('paginas').classList.toggle('hidden', paginas < 2);
    $('paginas').classList.toggle('flex', paginas >= 2);
    $('pag-info').textContent = 'Página ' + (pagina + 1) + ' de ' + paginas;
    $('pag-ant').disabled = pagina === 0;
    $('pag-sig').disabled = pagina >= paginas - 1;
  }

  $('pag-ant').addEventListener('click', function () { pagina--; pintarMovimientos(); });
  $('pag-sig').addEventListener('click', function () { pagina++; pintarMovimientos(); });

  /* ══ Deshacer una salida o anular una venta ══ */
  $('movimientos').addEventListener('click', function (e) {
    var b = e.target.closest('[data-borrar], [data-anular]');
    if (!b) return;
    var gasto = b.dataset.borrar !== undefined;
    var m = caja.movimientos.find(function (x) {
      return gasto ? x.id_movimiento === Number(b.dataset.borrar) : x.id_venta === Number(b.dataset.anular);
    });
    var titulo = gasto ? '¿Borrar esta salida?' : '¿Anular esta venta?';
    var detalle = m.concepto + ' · ' + pesos(m.monto) + (gasto ? '' : '. Las unidades vuelven al inventario.');
    T.confirmar(titulo, detalle, gasto ? 'Borrar salida' : 'Anular venta').then(function (si) {
      if (!si) return;
      var url = gasto ? '/api/caja/movimientos/' + m.id_movimiento : '/api/ventas/' + m.id_venta;
      T.ocupado(b, T.api('DELETE', url)).then(function (r) {
        T.toast(gasto ? 'Salida borrada' : r.msg);
        return cargar();
      }).catch(T.fallo);
    });
  });

  /* ══ Hoja de salida ══ */
  var sheet = T.hoja($('sheet-salida'));
  var form = $('form-salida');

  $('btn-salida').addEventListener('click', function () {
    form.reset();
    form.classList.remove('enviado');
    sheet.showModal();
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var d = new FormData(form);
    var monto = Number(d.get('monto'));
    T.ocupado($('btn-guardar-salida'), T.api('POST', '/api/caja/gastos', {
      concepto: String(d.get('concepto')).trim(),
      monto: monto,
      metodo: String(d.get('metodo'))
    })).then(function () {
      pagina = 0;   /* la salida nueva queda arriba de la primera página */
      sheet.close();
      T.toast('✓ Salida de ' + pesos(monto) + ' guardada');
      return cargar();
    }).catch(T.fallo);
  });

  /* ══ Cierre con arqueo ══ */
  var sheetC = T.hoja($('sheet-cierre'));
  var formC = $('form-cierre');

  function mostrarDiferencia() {
    var v = $('contado').value;
    var p = $('cierre-diferencia');
    if (v === '') { p.textContent = ''; return; }
    var dif = Number(v) - caja.efectivo_esperado;
    p.className = 'mt-1.5 text-xs font-medium ' + (dif === 0 ? 'text-emerald-700' : dif > 0 ? 'text-amber-700' : 'text-rose-700');
    p.textContent = dif === 0 ? 'Cuadra exacto.' : dif > 0 ? 'Sobran ' + pesos(dif) + '.' : 'Faltan ' + pesos(-dif) + '.';
  }
  $('contado').addEventListener('input', mostrarDiferencia);

  $('btn-cierre').addEventListener('click', function () {
    formC.reset();
    formC.classList.remove('enviado');
    $('cierre-esperado').textContent = pesos(caja.efectivo_esperado);
    mostrarDiferencia();
    sheetC.showModal();
  });

  formC.addEventListener('submit', function (e) {
    e.preventDefault();
    T.ocupado($('btn-confirmar-cierre'), T.api('POST', '/api/caja/cierre', {
      contado: Number($('contado').value),
      observaciones: $('observaciones').value.trim()
    })).then(function () {
      sheetC.close();
      T.toast('✓ Caja cerrada');
      return cargar();
    }).catch(T.fallo);
  });

  $('cerrada').addEventListener('click', function (e) {
    var b = e.target.closest('#btn-reabrir');
    if (!b) return;
    T.confirmar('¿Reabrir la caja de hoy?', 'Se borra el arqueo y el día vuelve a recibir cobros y salidas.', 'Reabrir caja').then(function (si) {
      if (!si) return;
      T.ocupado(b, T.api('POST', '/api/caja/reabrir', {})).then(function () {
        T.toast('Caja reabierta');
        return cargar();
      }).catch(T.fallo);
    });
  });

  /* ══ Pago por servicio (Admin): monto fijo para el profesional, el resto para el local ══ */
  var $reparto = $('reparto');

  function pintarReparto() {
    T.pintar($reparto, servicios.length ? servicios.map(function (s) {
      var paga = T.pagoProfesional(s.precio, s.pago_profesional);
      return T.h`<li>
        <div class="flex items-baseline justify-between gap-2">
          <label for="pago-${s.id_servicio}" class="min-w-0 truncate text-sm font-medium">${s.nombre}</label>
          <span class="shrink-0 text-xs text-brand-darkest/70">Precio ${pesos(s.precio)}</span>
        </div>
        <div class="mt-1.5 flex items-center gap-2">
          <span class="shrink-0 text-xs text-brand-darkest/70">Profesional</span>
          <input id="pago-${s.id_servicio}" data-pago="${s.id_servicio}" type="number" inputmode="numeric" min="0" max="${s.precio}" step="500" value="${paga}"
            class="block w-full min-w-0 flex-1 rounded-xl border border-brand-light bg-white px-3 text-base transition focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/25">
          <span class="shrink-0 text-xs text-brand-darkest/70">Local <strong data-local class="font-semibold text-brand-dark">${pesos(s.precio - paga)}</strong></span>
        </div>
      </li>`;
    }) : T.h`<li class="text-xs text-brand-darkest/70">Crea servicios en Inventario para configurar su reparto.</li>`);
  }

  if ($reparto) {
    /* Se cargan al abrir el desplegable: casi nunca se usa */
    $('detalle-reparto').addEventListener('toggle', function () {
      if (!this.open || servicios.length) return;
      T.pintar($reparto, T.h`<li class="esqueleto h-14"></li><li class="esqueleto h-14"></li>`);
      T.api('GET', '/api/servicios').then(function (r) {
        servicios = r.servicios;
        pintarReparto();
      }).catch(function (e) { T.errorCarga($reparto, e, function () { location.reload(); }); });
    });

    /* Mientras se escribe: se actualiza "Local" sin repintar (no se pierde el foco) */
    $reparto.addEventListener('input', function (e) {
      var inp = e.target.closest('[data-pago]');
      if (!inp) return;
      var s = servicios.find(function (x) { return x.id_servicio === Number(inp.dataset.pago); });
      inp.closest('li').querySelector('[data-local]').textContent = pesos(s.precio - T.pagoProfesional(s.precio, Number(inp.value)));
    });

    /* Al salir del campo se guarda; si escribió más que el precio, queda el precio */
    $reparto.addEventListener('change', function (e) {
      var inp = e.target.closest('[data-pago]');
      if (!inp) return;
      var s = servicios.find(function (x) { return x.id_servicio === Number(inp.dataset.pago); });
      var antes = s.pago_profesional;
      var nuevo = T.pagoProfesional(s.precio, Number(inp.value));
      inp.value = nuevo;
      T.api('PUT', '/api/servicios/' + s.id_servicio, {
        nombre: s.nombre, duracion_min: s.duracion_min, precio: s.precio, pago_profesional: nuevo
      }).then(function () {
        s.pago_profesional = nuevo;
        T.toast('✓ Reparto guardado');
      }).catch(function (err) {
        inp.value = antes;
        inp.closest('li').querySelector('[data-local]').textContent = pesos(s.precio - antes);
        T.fallo(err);
      });
    });
  }

  cargar();

  /* Lo que se cobró en otro celular aparece al volver a la pestaña y cada minuto */
  T.alVolver(cargar, 60000);
})();
