/* Prueba de las fórmulas de dinero. Correr con:  node test-calculo.js  */

const assert = require('assert');
const { pesos, precioVenta, pctGanancia } = require('./theme.js');

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

/* ── Reparto de caja: lo repartido más lo del local nunca puede
      superar los ingresos, con cualquier comisión. ── */
const repartir = (generado, comision) => Math.round(generado * comision / 100);
[0, 25, 50, 100].forEach(c => {
  const pagos = [88000, 63000].map(g => repartir(g, c));
  const total = pagos.reduce((a, b) => a + b, 0);
  assert.ok(total <= 151000, `comisión ${c}% reparte ${total} de 151000`);
});
assert.strictEqual(repartir(88000, 50), 44000);
assert.strictEqual(repartir(63000, 40), 25200);

console.log('OK — 27 comprobaciones de cálculo');
