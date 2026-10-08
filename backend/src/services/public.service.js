const pool = require('../config/db');

// Vista de clientes finales: columnas explícitas. Nunca email, rol, comisiones ni métricas.

async function business(slug) {
  const { rows } = await pool.query(
    `select t.id, t.name,
            coalesce(json_agg(json_build_object(
              'id', s.id, 'name', s.name,
              'duration_minutes', s.duration_minutes, 'price_cents', s.price_cents
            ) order by s.name) filter (where s.id is not null), '[]') as services
     from tenants t
     left join services s on s.tenant_id = t.id and s.active
     where t.slug = $1 and t.active
     group by t.id`,
    [slug]
  );
  return rows[0];
}

async function availability(slug, at) {
  const { rows } = await pool.query(
    `select u.id, u.full_name as name, u.photo_url,
            not exists (
              select 1 from appointments a
              where a.tenant_id = u.tenant_id and a.staff_id = u.id
                and a.scheduled_at = $2 and a.status in ('booked', 'blocked')
            ) as available
     from users u
     join tenants t on t.id = u.tenant_id
     where t.slug = $1 and t.active and u.active
     order by u.full_name`,
    [slug, at]
  );
  return rows;
}

module.exports = { business, availability };
