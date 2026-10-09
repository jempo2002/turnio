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

console.log('OK — fórmulas de dinero y agenda del panel');
