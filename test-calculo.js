/* Prueba de las fórmulas del panel (static/js/panel/turnio.js). Correr con:  node test-calculo.js
   Antes probaba theme.js del prototipo; las mismas comprobaciones ahora van
   contra el código que corre en el panel (T9 borró el prototipo). */

const assert = require('assert');
const panel = require('./static/js/panel/turnio.js');
const { pesos, precioVenta, pctGanancia } = panel;
const pagoProfesional = panel.pagoProfesional;

/* ── Formato de moneda ── */
assert.strictEqual(pesos(0), '$0');
assert.strictEqual(pesos(5000), '$5.000');
assert.strictEqual(pesos(186500), '$186.500');
assert.strictEqual(pesos(4249.6), '$4.250', 'redondea, no trunca');

/* ── Precio de venta: costo + % de ganancia, redondeado a $100 ── */
assert.strictEqual(precioVenta(3000, 40), 4200);
assert.strictEqual(precioVenta(11000, 60), 17600);
assert.strictEqual(precioVenta(2000, 0), 2000, 'sin ganancia, se vende al costo');
assert.strictEqual(precioVenta(1250, 40), 1800, 'redondea 1750 al centenar más cercano');

/* Entradas basura no deben producir NaN en pantalla */
assert.strictEqual(precioVenta(0, 40), 0);
assert.strictEqual(precioVenta(NaN, 40), 0);
assert.strictEqual(precioVenta(-500, 40), 0, 'un costo negativo no genera precio');
assert.strictEqual(precioVenta(3000, NaN), 0);

/* ── Camino inverso: del precio de venta al % ── */
assert.strictEqual(pctGanancia(3000, 4200), 40);
assert.strictEqual(pctGanancia(2000, 2000), 0);
assert.strictEqual(pctGanancia(3000, 2500), -17, 'vender por debajo del costo da % negativo');
assert.strictEqual(pctGanancia(0, 5000), 0, 'sin costo no hay porcentaje que calcular');

/* ── Ida y vuelta: el % mostrado no puede desviarse más de lo que causa
      el redondeo a $100. Con costos >= $1.000 debe cerrar exacto. ── */
[1000, 1200, 3000, 4500, 11000, 25000].forEach(compra => {
  [0, 10, 20, 40, 75, 100].forEach(pct => {
    const venta = precioVenta(compra, pct);
    const vuelta = pctGanancia(compra, venta);
    const desvio = Math.abs(vuelta - pct);
    const maximo = Math.ceil(50 / compra * 100);  // medio centenar de redondeo
    assert.ok(desvio <= maximo,
      `compra ${compra} con ${pct}% dio venta ${venta} y volvió como ${vuelta}% (desvío ${desvio} > ${maximo})`);
  });
});

/* ── Reparto fijo: el profesional recibe un monto por servicio y el resto es del local.
      Entre los dos nunca pueden sumar más que el precio. ── */
assert.strictEqual(pagoProfesional(18000, 12000), 12000);
assert.strictEqual(18000 - pagoProfesional(18000, 12000), 6000, 'el local se queda el resto');
assert.strictEqual(pagoProfesional(18000, 25000), 18000, 'nunca más que el precio');
assert.strictEqual(pagoProfesional(18000, -500), 0, 'nunca negativo');
assert.strictEqual(pagoProfesional(18000, NaN), 0);
assert.strictEqual(pagoProfesional(18000, undefined), 0, 'servicio sin reparto configurado: todo al local');

/* Turnos libres de la línea de tiempo: horas en punto que nada vigente toca */
const lunes = { abierto: true, abre: '08:00', cierra: '12:00', almuerzo_desde: null, almuerzo_hasta: null };
assert.deepStrictEqual(panel.turnosLibres(lunes, []), ['08:00', '09:00', '10:00', '11:00']);
assert.deepStrictEqual(panel.turnosLibres(lunes, [{ hora: '09:30', fin: '10:15' }]), ['08:00', '11:00'],
  'una cita de 45 min a las 9:30 ocupa las 9 y las 10');
assert.deepStrictEqual(panel.turnosLibres(lunes, [{ hora: '08:00', fin: '09:00' }]), ['09:00', '10:00', '11:00'],
  'terminar a las 9 deja libre las 9');
assert.deepStrictEqual(panel.turnosLibres(lunes, [], '09:20'), ['10:00', '11:00'], 'hoy: no ofrece horas que ya pasaron');
assert.deepStrictEqual(panel.turnosLibres(Object.assign({}, lunes, { almuerzo_desde: '10:00', almuerzo_hasta: '11:00' }), []),
  ['08:00', '09:00', '11:00'], 'el almuerzo no se agenda');
assert.deepStrictEqual(panel.turnosLibres(Object.assign({}, lunes, { abre: '08:30', cierra: '11:30' }), []), ['09:00', '10:00'],
  'solo horas completas dentro del horario');
assert.deepStrictEqual(panel.turnosLibres(Object.assign({}, lunes, { abierto: false }), []), [], 'día cerrado');
assert.deepStrictEqual(panel.turnosLibres(undefined, []), []);
assert.deepStrictEqual(panel.turnosLibres(lunes, [{ hora: '00:00', fin: '24:00' }]), [], 'bloqueo de todo el día');

/* ── Avisos (docs/ux-avisos.md): todo error dice qué pasó y qué hacer ── */
const explicar = panel.explicar;
const sinRed = explicar(0);
assert.strictEqual(sinRed.titulo, 'Sin conexión');
assert.ok(/No se guardó nada/.test(sinRed.detalle), 'sin red: dice que no se perdió nada a medias');
assert.strictEqual(explicar(400, 'Escribe el precio.').detalle, 'Escribe el precio.', 'el mensaje del servidor es el qué hacer');
assert.ok(explicar(400, '').detalle.length > 10, 'sin mensaje del servidor igual dice qué hacer');
assert.strictEqual(explicar(500, 'Traceback secreto').detalle.indexOf('Traceback'), -1, 'un 500 no muestra nada interno');
const tope = explicar(403, 'Tu plan permite 2 sedes.', { code: 'limite_plan', accion_url: '/ajustes#plan', accion_texto: 'Subir de plan' });
assert.strictEqual(tope.tipo, 'aviso', 'el tope del plan no es un error');
assert.deepStrictEqual(tope.accion, { texto: 'Subir de plan', href: '/ajustes#plan' });
assert.strictEqual(explicar(404).accion.recargar, true, 'lo que ya no existe ofrece recargar');
assert.strictEqual(explicar(429, 'Ya tienes 3 citas por venir.').detalle, 'Ya tienes 3 citas por venir.');
[0, 400, 401, 402, 403, 404, 409, 429, 500, 503].forEach(function (st) {
  const a = explicar(st, '');
  assert.ok(a.titulo && a.detalle, 'status ' + st + ': título y qué hacer');
  assert.ok(['exito', 'info', 'aviso', 'error'].indexOf(a.tipo) >= 0);
  assert.ok(!/\b(error|inv[aá]lido|status|request)\b/i.test(a.titulo + ' ' + a.detalle), 'status ' + st + ': sin jerga');
});

/* ── Hora en 12 h con AM/PM (solo para mostrar; la API sigue en 24 h) ── */
const { hora12, franja } = panel;
assert.strictEqual(hora12('09:00'), '9:00 AM');
assert.strictEqual(hora12('14:30'), '2:30 PM');
assert.strictEqual(hora12('12:00'), '12:00 PM', 'mediodía es PM');
assert.strictEqual(hora12('00:15'), '12:15 AM', 'medianoche es 12 AM');
assert.strictEqual(hora12('23:45'), '11:45 PM');
assert.strictEqual(hora12('08:30:00'), '8:30 AM', 'ignora los segundos');
assert.strictEqual(hora12(''), '', 'sin hora no inventa una');
assert.strictEqual(franja('11:45'), 'manana');
assert.strictEqual(franja('12:00'), 'tarde');
assert.strictEqual(franja('17:59'), 'tarde');
assert.strictEqual(franja('18:00'), 'noche');

console.log('OK — fórmulas de dinero y agenda del panel, avisos y horas en 12 h');
