/* Turnio — Inventario: productos con su stock en la sede y servicios.
   Datos: /api/productos (+ /movimientos), /api/servicios (T4, T5).
   Admin: crea, edita y elimina. Recepción: sube o baja unidades. */

(function () {
  'use strict';

  var T = window.Turnio, $ = T.$, esc = T.esc, pesos = T.pesos;
  var ADMIN = T.yo.rol === 'Admin';

  var productos = [];
  var servicios = [];
  var tab = 'productos';

  var BTN_EDITAR = 'shrink-0 rounded-xl bg-brand-lightest px-3 text-xs font-semibold text-brand-dark transition hover:bg-brand-light active:scale-95';
  var BTN_ELIMINAR = 'shrink-0 rounded-xl px-3 text-xs font-semibold text-rose-700 transition hover:bg-rose-50 active:scale-95';

  function producto(id) { return productos.find(function (p) { return p.id_producto === id; }); }
  function servicio(id) { return servicios.find(function (s) { return s.id_servicio === id; }); }

  /* ══ Pestañas ══ */
  function pintarTabs() {
    document.querySelectorAll('.tab').forEach(function (b) {
      var activo = b.dataset.tab === tab;
      b.setAttribute('aria-selected', activo);
      b.className = 'tab rounded-xl py-3 text-center text-sm transition ' +
        (activo ? 'bg-white font-semibold text-brand-dark shadow-soft' : 'font-medium text-brand-darkest/55 hover:bg-white/70');
    });
    $('panel-productos').hidden = tab !== 'productos';
    $('panel-servicios').hidden = tab !== 'servicios';
    if ($('btn-nuevo-texto')) $('btn-nuevo-texto').textContent = tab === 'productos' ? 'Producto' : 'Servicio';
    $('subtitulo').textContent = tab === 'productos'
      ? 'Lo que vendes además de los servicios'
      : 'Los servicios que ve tu cliente';
  }

  document.querySelectorAll('.tab').forEach(function (b) {
    b.addEventListener('click', function () { tab = b.dataset.tab; pintarTabs(); });
  });

  /* ══ Carga ══ */
  function cargarProductos() {
    return T.api('GET', '/api/productos').then(function (r) {
      productos = r.productos;
      pintarProductos();
    }).catch(function (e) { T.errorCarga($('productos'), e, cargarProductos); });
  }

  function cargarServicios() {
    return T.api('GET', '/api/servicios').then(function (r) {
      servicios = r.servicios;
      pintarServicios();
    }).catch(function (e) { T.errorCarga($('servicios'), e, cargarServicios); });
  }

  /* ══ Productos ══ */
  function pintarProductos() {
    $('productos').removeAttribute('aria-busy');
    var enAlerta = 0, agotados = 0;

    $('productos').innerHTML = productos.map(function (p) {
      var agotado = p.stock <= 0;
      var bajo = !agotado && p.stock_bajo;
      if (agotado) agotados++; else if (bajo) enAlerta++;

      var aviso = agotado
        ? '<span class="rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-rose-700">Agotado</span>'
        : bajo
          ? '<span class="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-800">Quedan pocas</span>'
          : '';

      var borde = agotado ? 'border-rose-200' : bajo ? 'border-amber-200' : 'border-slate-200';
      var nombre = esc(p.nombre);

      return '<li class="rounded-2xl border ' + borde + ' bg-white p-4 shadow-soft' + (agotado ? ' opacity-75' : '') + '">' +
        '<div class="flex items-center gap-3">' +
          '<span class="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-brand-lightest/70 text-xl" aria-hidden="true">' + esc(p.emoji || '📦') + '</span>' +
          '<div class="min-w-0 flex-1">' +
            '<div class="flex flex-wrap items-center gap-x-2 gap-y-1">' +
              '<p class="truncate text-sm font-semibold">' + nombre + '</p>' + aviso +
            '</div>' +
            '<p class="mt-0.5 text-xs text-brand-darkest/55">Compra ' + pesos(p.costo) + ' · Venta ' + pesos(p.precio) +
              ' · <span class="font-medium text-brand-dark">+' + pesos(p.precio - p.costo) + '</span></p>' +
            (p.codigo_barras ? '<p class="mt-0.5 truncate text-[11px] tabular-nums text-brand-darkest/40">Cód. ' + esc(p.codigo_barras) + '</p>' : '') +
          '</div>' +
        '</div>' +
        '<div class="mt-3 flex items-center gap-1 border-t border-brand-light/40 pt-3">' +
          (ADMIN
            ? '<button type="button" data-editar="' + p.id_producto + '" class="' + BTN_EDITAR + '" aria-label="Editar ' + nombre + '">Editar</button>' +
              '<button type="button" data-eliminar="' + p.id_producto + '" class="' + BTN_ELIMINAR + '" aria-label="Eliminar ' + nombre + '">Eliminar</button>'
            : '') +
          '<div class="ml-auto flex shrink-0 items-center gap-1">' +
            '<button type="button" data-menos="' + p.id_producto + '"' + (agotado ? ' disabled' : '') +
              ' class="grid h-11 w-11 place-items-center rounded-xl border border-brand-light text-lg font-semibold transition hover:bg-brand-lightest/60 disabled:opacity-30" aria-label="Quitar una unidad de ' + nombre + '">−</button>' +
            '<span class="w-9 text-center text-base font-semibold tabular-nums" aria-label="' + p.stock + ' unidades">' + p.stock + '</span>' +
            '<button type="button" data-mas="' + p.id_producto + '" class="grid h-11 w-11 place-items-center rounded-xl border border-brand-light text-lg font-semibold transition hover:bg-brand-lightest/60" aria-label="Agregar una unidad de ' + nombre + '">+</button>' +
          '</div>' +
        '</div>' +
      '</li>';
    }).join('') || '<li class="rounded-2xl border border-slate-200 bg-white p-6 text-center text-sm text-brand-darkest/60">' +
      (ADMIN ? 'Todavía no hay productos. Toca “Producto” para agregar el primero.' : 'Todavía no hay productos.') + '</li>';

    var partes = [];
    if (agotados) partes.push(agotados + ' agotado' + (agotados > 1 ? 's' : ''));
    if (enAlerta) partes.push(enAlerta + ' por acabarse');
    $('resumen-alertas').textContent = !productos.length ? 'Sin productos todavía.'
      : partes.length ? '⚠ ' + partes.join(' · ') + '. Toca reponer.'
      : 'Todo con stock suficiente.';
  }

  /* +1 / −1: una entrada o salida en el kardex de la sede. Los toques seguidos
     van en fila para que el stock que muestra la API sea siempre el último. */
  var fila = Promise.resolve();

  function mover(p, tipo) {
    var previo = p.stock;
    p.stock += tipo === 'Entrada' ? 1 : -1;
    pintarProductos();
    fila = fila.then(function () {
      return T.api('POST', '/api/productos/' + p.id_producto + '/movimientos', {
        tipo: tipo, cantidad: 1, motivo: tipo === 'Entrada' ? 'Ajuste rápido (+1)' : 'Ajuste rápido (−1)'
      }).then(function (r) {
        p.stock = r.stock;
        p.stock_bajo = p.stock_minimo > 0 && p.stock <= p.stock_minimo;
        pintarProductos();
      }).catch(function (e) {
        p.stock = previo;
        pintarProductos();
        T.fallo(e);
      });
    });
  }

  $('productos').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    var d = b.dataset;

    if (d.editar !== undefined) { abrirProducto(producto(Number(d.editar))); return; }

    if (d.eliminar !== undefined) {
      var p = producto(Number(d.eliminar));
      T.confirmar(
        '¿Eliminar "' + p.nombre + '"?',
        'Sale del inventario y de la venta rápida. Las ventas ya registradas en caja no cambian.',
        'Eliminar producto'
      ).then(function (si) {
        if (!si) return;
        T.ocupado(b, T.api('DELETE', '/api/productos/' + p.id_producto)).then(function () {
          T.toast('Producto eliminado');
          return cargarProductos();
        }).catch(T.fallo);
      });
      return;
    }

    if (d.menos !== undefined) mover(producto(Number(d.menos)), 'Salida');
    else if (d.mas !== undefined) mover(producto(Number(d.mas)), 'Entrada');
  });

  /* ══ Servicios ══ */
  function pintarServicios() {
    $('servicios').removeAttribute('aria-busy');
    $('servicios').innerHTML = servicios.map(function (s) {
      var paga = T.pagoProfesional(s.precio, s.pago_profesional);
      var nombre = esc(s.nombre);
      return '<li class="rounded-2xl border border-slate-200 bg-white p-4 shadow-soft">' +
        '<div class="flex items-start gap-3">' +
          '<div class="min-w-0 flex-1">' +
            '<p class="truncate text-sm font-semibold">' + nombre + '</p>' +
            '<p class="mt-0.5 truncate text-xs text-brand-darkest/55">' + s.duracion_min + ' min · Profesional ' + pesos(paga) + ' · Local ' + pesos(s.precio - paga) + '</p>' +
          '</div>' +
          '<p class="shrink-0 text-base font-semibold">' + pesos(s.precio) + '</p>' +
        '</div>' +
        (ADMIN
          ? '<div class="mt-3 flex items-center justify-end gap-1 border-t border-brand-light/40 pt-3">' +
              '<button type="button" data-editar="' + s.id_servicio + '" class="' + BTN_EDITAR + '" aria-label="Editar ' + nombre + '">Editar</button>' +
              '<button type="button" data-eliminar="' + s.id_servicio + '" class="' + BTN_ELIMINAR + '" aria-label="Eliminar ' + nombre + '">Eliminar</button>' +
            '</div>'
          : '') +
      '</li>';
    }).join('') || '<li class="rounded-2xl border border-slate-200 bg-white p-6 text-center text-sm text-brand-darkest/60">' +
      (ADMIN ? 'Todavía no hay servicios. Toca “Servicio” para crear el primero.' : 'Todavía no hay servicios.') + '</li>';
  }

  $('servicios').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.editar !== undefined) { abrirServicio(servicio(Number(b.dataset.editar))); return; }
    if (b.dataset.eliminar === undefined) return;

    var s = servicio(Number(b.dataset.eliminar));
    T.confirmar(
      '¿Eliminar "' + s.nombre + '"?',
      'Deja de aparecer en el link público de reservas. Las citas ya agendadas con este servicio no cambian.',
      'Eliminar servicio'
    ).then(function (si) {
      if (!si) return;
      T.ocupado(b, T.api('DELETE', '/api/servicios/' + s.id_servicio)).then(function () {
        T.toast('Servicio eliminado');
        return cargarServicios();
      }).catch(T.fallo);
    });
  });

  /* ══ Calculadora de utilidad ══
     compra + % → venta, y venta → % en sentido inverso. Redondea a $100 (moneda real). */
  var compra = $('p-compra'), ganancia = $('p-ganancia'), venta = $('p-venta'), utilidad = $('utilidad');

  function mostrarUtilidad() {
    var c = Number(compra.value) || 0, v = Number(venta.value) || 0;
    var dif = v - c;
    utilidad.innerHTML = dif >= 0
      ? 'Ganas <strong class="font-semibold text-brand-dark">' + pesos(dif) + '</strong> por unidad.'
      : '<strong class="font-semibold text-rose-700">Pierdes ' + pesos(-dif) + '</strong> por unidad: vendes más barato de lo que compras.';
  }

  function calcularVenta() {
    var v = T.precioVenta(Number(compra.value), Number(ganancia.value));
    if (v) venta.value = v;
    mostrarUtilidad();
  }

  function calcularGanancia() {
    var c = Number(compra.value);
    if (c > 0) ganancia.value = T.pctGanancia(c, Number(venta.value));
    mostrarUtilidad();
  }

  compra.addEventListener('input', calcularVenta);
  ganancia.addEventListener('input', calcularVenta);
  venta.addEventListener('input', calcularGanancia);

  /* ══ Hojas ══ */
  var sheetP = T.hoja($('sheet-producto')), formP = $('form-producto');
  var sheetS = T.hoja($('sheet-servicio')), formS = $('form-servicio');

  /* Un mismo formulario crea y edita: editP / editS apuntan al registro en edición (o null si es nuevo) */
  var editP = null, editS = null;

  function abrirProducto(p) {
    editP = p || null;
    formP.reset();
    formP.classList.remove('enviado');
    $('producto-titulo').textContent = p ? 'Editar producto' : 'Nuevo producto';
    $('p-unidades-label').textContent = p ? 'Unidades en stock (conteo)' : 'Unidades que entran';
    if (p) {
      $('p-nombre').value = p.nombre;
      $('p-codigo').value = p.codigo_barras || '';
      $('p-unidades').value = p.stock;
      $('p-minimo').value = p.stock_minimo || '';
      compra.value = p.costo;
      venta.value = p.precio;
      ganancia.value = T.pctGanancia(p.costo, p.precio);
    }
    mostrarUtilidad();
    sheetP.showModal();
  }

  function mostrarLocal() {
    var precio = Number($('s-precio').value) || 0;
    var paga = T.pagoProfesional(precio, Number($('s-pago').value));
    $('s-local').textContent = 'El local se queda con ' + pesos(precio - paga) + ' de cada servicio.';
  }

  function abrirServicio(s) {
    editS = s || null;
    formS.reset();
    formS.classList.remove('enviado');
    $('servicio-titulo').textContent = s ? 'Editar servicio' : 'Nuevo servicio';
    if (s) {
      $('s-nombre').value = s.nombre;
      var dur = $('s-duracion');
      /* Una duración que no está en la lista (la puso otro) se agrega para no perderla */
      if (!dur.querySelector('option[value="' + s.duracion_min + '"]')) {
        dur.insertAdjacentHTML('beforeend', '<option value="' + s.duracion_min + '">' + s.duracion_min + ' min</option>');
      }
      dur.value = s.duracion_min;
      $('s-precio').value = s.precio;
      $('s-pago').value = s.pago_profesional || '';
    }
    mostrarLocal();
    sheetS.showModal();
  }

  $('s-precio').addEventListener('input', mostrarLocal);
  $('s-pago').addEventListener('input', mostrarLocal);

  if ($('btn-nuevo')) {
    $('btn-nuevo').addEventListener('click', function () {
      if (tab === 'productos') abrirProducto(); else abrirServicio();
    });
  }

  formP.addEventListener('submit', function (e) {
    e.preventDefault();
    var d = new FormData(formP);
    var codigo = String(d.get('codigo')).trim();

    /* Dos productos con el mismo código harían ambigua la venta por escáner (la API también lo frena) */
    var repetido = codigo && productos.find(function (p) { return p !== editP && p.codigo_barras === codigo; });
    if (repetido) {
      T.toast('Ese código ya lo tiene "' + repetido.nombre + '"', 'error');
      $('p-codigo').focus();
      return;
    }

    var campos = {
      nombre: String(d.get('nombre')).trim(),
      codigo_barras: codigo,
      emoji: editP ? editP.emoji : '',
      costo: Number(d.get('compra')),
      precio: Number(d.get('venta')),
      stock_minimo: Number(d.get('minimo')) || 0
    };
    var unidades = Number(d.get('unidades'));
    var p = editP;
    var guardar;
    if (p) {
      /* Los datos del producto y, si cambió el conteo, un Ajuste en el kardex */
      guardar = T.api('PUT', '/api/productos/' + p.id_producto, campos).then(function () {
        if (unidades === p.stock) return null;
        return T.api('POST', '/api/productos/' + p.id_producto + '/movimientos', {
          tipo: 'Ajuste', cantidad: unidades, motivo: 'Conteo desde Inventario'
        });
      });
    } else {
      campos.stock = unidades;
      guardar = T.api('POST', '/api/productos', campos);
    }

    T.ocupado($('btn-guardar-producto'), guardar).then(function () {
      sheetP.close();
      T.toast(p ? '✓ Producto actualizado' : '✓ Producto guardado');
      return cargarProductos();
    }).catch(function (err) {
      T.fallo(err);
      if (p) cargarProductos();   /* pudo quedar guardado a medias (datos sí, conteo no) */
    });
  });

  formS.addEventListener('submit', function (e) {
    e.preventDefault();
    var d = new FormData(formS);
    var precio = Number(d.get('precio'));
    var campos = {
      nombre: String(d.get('nombre')).trim(),
      duracion_min: Number(d.get('duracion')),
      precio: precio,
      pago_profesional: T.pagoProfesional(precio, Number(d.get('pago')))
    };
    var s = editS;
    T.ocupado($('btn-guardar-servicio'), s
      ? T.api('PUT', '/api/servicios/' + s.id_servicio, campos)
      : T.api('POST', '/api/servicios', campos)
    ).then(function () {
      sheetS.close();
      T.toast(s ? '✓ Servicio actualizado' : '✓ Servicio guardado');
      return cargarServicios();
    }).catch(T.fallo);
  });

  pintarTabs();
  cargarProductos();
  cargarServicios();

  /* Lo vendido en otro celular baja el stock: se refresca al volver a la pestaña */
  T.alVolver(function () { cargarProductos(); }, 0);
})();
