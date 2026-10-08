// Correr con: npm test
// La base de datos se simula: se comprueba qué SQL y qué parámetros manda el backend,
// no el comportamiento de Postgres (constraints, RLS). Eso se valida corriendo los .sql en Supabase.
const test = require('node:test');
const assert = require('node:assert');
const jwt = require('jsonwebtoken');

process.env.SUPABASE_JWT_SECRET = 'secreto-de-prueba';

const TENANT = '11111111-1111-4111-8111-111111111111';
const YO     = '22222222-2222-4222-8222-222222222222';
const OTRO   = '33333333-3333-4333-8333-333333333333';
const CITA   = '44444444-4444-4444-8444-444444444444';
const SERV   = '55555555-5555-4555-8555-555555555555';

let consultas = [];
let responder = () => [];
const query = async (sql, params) => { consultas.push({ sql, params }); return { rows: responder(sql, params) }; };
const pool = { query, connect: async () => ({ query, release() {} }) };
require.cache[require.resolve('../src/config/db')] = { exports: pool };

const app = require('../src/server');
let base, servidor;
test.before(() => new Promise((ok) => { servidor = app.listen(0, () => { base = 'http://127.0.0.1:' + servidor.address().port + '/api'; ok(); }); }));
test.after(() => servidor.close());
test.beforeEach(() => { consultas = []; responder = () => []; });

const token = jwt.sign({ sub: YO, app_metadata: { tenant_id: TENANT, role: 'staff' } }, process.env.SUPABASE_JWT_SECRET);
const post = (ruta, body, auth) => fetch(base + ruta, {
  method: 'POST',
  headers: Object.assign({ 'Content-Type': 'application/json' }, auth && { Authorization: 'Bearer ' + auth }),
  body: JSON.stringify(body),
});

test('completar cita: el cobro va al usuario del JWT, no al staffId del body', async () => {
  responder = (sql) => {
    if (sql.includes('from users')) return [{}];
    if (sql.includes('for update')) return [{ price_cents: 2500000, customer_name: 'Ana', service_name: 'Corte', payout_cents: 1500000 }];
    return [];
  };
  const r = await post('/appointments/' + CITA + '/complete',
    { staffId: OTRO, tenantId: OTRO, payments: [{ method: 'cash', amountCents: 1000000 }, { method: 'transfer', amountCents: 1500000 }] }, token);
  assert.strictEqual(r.status, 200);
  assert.strictEqual((await r.json()).staff_id, YO);

  const escrituras = consultas.filter((c) => /^\s*(update|insert)/.test(c.sql));
  assert.strictEqual(escrituras.length, 3, 'una cita + dos movimientos (pago mixto)');
  escrituras.forEach((c) => {
    assert.strictEqual(c.params[0], TENANT);
    assert.ok(c.params.includes(YO));
    assert.ok(!c.params.includes(OTRO), 'el id manipulado nunca llega a la base de datos');
  });
  const comisiones = escrituras.filter((c) => c.sql.includes('transactions')).map((c) => c.params[6]);
  assert.deepStrictEqual(comisiones, [1500000, null], 'la comisión se anota una sola vez');
  assert.ok(consultas.some((c) => c.sql === 'commit'));
});

test('completar cita: pagos que no suman el precio se revierten', async () => {
  responder = (sql) => (sql.includes('from users') ? [{}] : sql.includes('for update') ? [{ price_cents: 2500000, payout_cents: 0 }] : []);
  const r = await post('/appointments/' + CITA + '/complete', { payments: [{ method: 'cash', amountCents: 100 }] }, token);
  assert.strictEqual(r.status, 400);
  assert.ok(consultas.some((c) => c.sql === 'rollback'));
  assert.ok(!consultas.some((c) => /^\s*(update|insert)/.test(c.sql)));
});

test('completar cita: sin token o con token falso no se toca la base de datos', async () => {
  const pagos = { payments: [{ method: 'cash', amountCents: 2500000 }] };
  assert.strictEqual((await post('/appointments/' + CITA + '/complete', pagos)).status, 401);
  const falso = jwt.sign({ sub: OTRO, app_metadata: { tenant_id: TENANT } }, 'otro-secreto');
  assert.strictEqual((await post('/appointments/' + CITA + '/complete', pagos, falso)).status, 401);
  assert.strictEqual(consultas.length, 0);
});

test('disponibilidad pública: solo nombre, foto y disponibilidad', async () => {
  responder = () => [{ id: YO, name: 'Carlos', photo_url: null, available: true }, { id: OTRO, name: 'Junior', photo_url: null, available: false }];
  const r = await fetch(base + '/public/el-cuartel/availability?at=2030-01-01T15:00:00Z');
  assert.strictEqual(r.status, 200);
  assert.strictEqual((await r.json()).length, 2);

  const { sql, params } = consultas[0];
  assert.deepStrictEqual(params, ['el-cuartel', '2030-01-01T15:00:00.000Z']);
  const columnas = sql.slice(0, sql.indexOf('from users'));
  ['email', 'password', 'payout', 'role', '*'].forEach((x) => assert.ok(!columnas.includes(x), 'no debe exponer ' + x));
});

test('rutas públicas: entradas inválidas se rechazan antes de consultar', async () => {
  assert.strictEqual((await fetch(base + "/public/el-cuartel/availability?at='; drop table users;--")).status, 400);
  assert.strictEqual((await fetch(base + '/public/' + encodeURIComponent("x' or '1'='1") + '/availability?at=2030-01-01T15:00:00Z')).status, 400);
  const mala = await post('/public/el-cuartel/appointments', { serviceId: 'x', staffId: YO, scheduledAt: '2030-01-01T15:00:00Z', customerName: 'Ana' });
  assert.strictEqual(mala.status, 400);
  assert.strictEqual(consultas.length, 0);
});

test('reserva pública: precio sale del servicio y un choque de franja responde 409', async () => {
  const cuerpo = { serviceId: SERV, staffId: YO, scheduledAt: '2030-01-01T15:00:00Z', customerName: '  Ana  ', customerPhone: '+57 300 111-2233', priceCents: 1 };
  responder = (sql) => (sql.includes('from tenants') ? [{ id: TENANT, name: 'El Cuartel', services: [] }]
    : [{ id: CITA, staff_id: YO, scheduled_at: cuerpo.scheduledAt, status: 'booked', price_cents: 2500000 }]);
  const r = await post('/public/el-cuartel/appointments', cuerpo);
  assert.strictEqual(r.status, 201);
  assert.deepStrictEqual(Object.keys(await r.json()).sort(), ['id', 'price_cents', 'scheduled_at', 'status']);
  const insert = consultas.find((c) => c.sql.includes('insert into appointments'));
  assert.deepStrictEqual(insert.params, [TENANT, SERV, YO, 'Ana', '573001112233', '2030-01-01T15:00:00.000Z']);

  responder = (sql) => {
    if (sql.includes('from tenants')) return [{ id: TENANT, name: 'El Cuartel', services: [] }];
    throw Object.assign(new Error('duplicate key'), { code: '23505' });
  };
  assert.strictEqual((await post('/public/el-cuartel/appointments', cuerpo)).status, 409);
});
