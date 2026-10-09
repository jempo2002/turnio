-- Turnio — datos de demo (barbería de prueba)
-- Idempotente: borra el tenant demo si ya existe (cascada limpia todo lo demás) y vuelve a insertar.
-- Ejecutar en el SQL Editor de Supabase o vía `psql "$DATABASE_URL" -f backend/db/seed.sql`.

delete from tenants where slug = 'demo-barberia';

with t as (
  insert into tenants (name, slug) values ('Barbería Turnio Demo', 'demo-barberia')
  returning id
),
staff as (
  insert into users (tenant_id, email, password_hash, full_name, role)
  select t.id, v.email, '$2b$10$demoseedhashnotrealbcrypt00000000000000000000000000', v.full_name, v.role
  from t, (values
    ('carlos@turnio.demo', 'Carlos', 'staff'),
    ('junior@turnio.demo', 'Junior', 'staff'),
    ('andres@turnio.demo', 'Andrés', 'owner')
  ) as v(email, full_name, role)
  returning id, full_name
),
svc as (
  insert into services (tenant_id, name, duration_minutes, price_cents, staff_payout_cents)
  select t.id, v.name, v.duration, v.price, v.payout
  from t, (values
    ('Corte clásico',      45, 20000, 13000),
    ('Corte + barba',      60, 25000, 15000),
    ('Perfilado de barba', 30, 15000, 10000),
    ('Fade',               45, 18000, 12000),
    ('Cejas',              15,  6000,  4000)
  ) as v(name, duration, price, payout)
  returning id, name
),
inv as (
  insert into inventory (tenant_id, barcode, emoji, name, quantity, cost_cents, price_cents, units_sold)
  select t.id, v.barcode, v.emoji, v.name, v.qty, v.cost, v.price, v.sold
  from t, (values
    ('7701234000011', '🍺', 'Cerveza en lata', 18, 3000,  5000,  42),
    ('7701234000028', '💧', 'Agua 500 ml',      4, 1200,  2000,  31),
    ('7701234000059', '🧴', 'Cera moldeadora',  7, 11000, 18000, 9),
    ('7701234000066', '☕', 'Café',             0, 1000,  2500,  37),
    ('7701234000073', '🧴', 'Gel fijador',      9, 6000,  10000, 4)
  ) as v(barcode, emoji, name, qty, cost, price, sold)
  returning id
)
insert into appointments (tenant_id, service_id, staff_id, customer_name, customer_phone, scheduled_at, status, price_cents)
select
  t.id,
  (select id from svc   where name      = v.service_name),
  (select id from staff where full_name = v.staff_name),
  v.customer_name,
  v.phone,
  (current_date + v.hora::time)::timestamptz,
  v.status,
  v.price
from t, (values
  ('08:00', 'Andrés Mejía',    'Corte + barba',      'Carlos', '573001112233', 'completed', 25000),
  ('09:00', 'Kevin Ríos',      'Fade',                'Junior', '573002223344', 'completed', 18000),
  ('10:00', 'Julián Pardo',    'Corte clásico',       'Carlos', '573003334455', 'booked',    20000),
  ('11:00', null,              null,                  null,     null,           'available', 0),
  ('12:00', 'Mateo Guzmán',    'Corte + barba',       'Junior', '573004445566', 'booked',    25000),
  ('14:00', 'Santiago Lozano', 'Perfilado de barba',  'Carlos', '573005556677', 'booked',    15000),
  ('15:00', null,              null,                  null,     null,           'available', 0),
  ('16:30', 'Valentina Ruiz',  'Cejas',               'Junior', '573006667788', 'booked',    6000)
) as v(hora, customer_name, service_name, staff_name, phone, status, price);
