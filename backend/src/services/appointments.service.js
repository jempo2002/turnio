const pool = require('../config/db');
const { fail } = require('../validate');

// Toda query lleva "tenant_id = $1": segunda barrera además de RLS en la DB.
async function listByDay(tenantId, day) {
  const { rows } = await pool.query(
    `select id, service_id, staff_id, customer_name, customer_phone,
            scheduled_at, status, price_cents
     from appointments
     where tenant_id = $1 and scheduled_at::date = $2
     order by scheduled_at`,
    [tenantId, day]
  );
  return rows;
}

// El insert sale de un select: servicio y profesional deben existir, estar activos y ser
// del mismo tenant, y el precio se copia del servicio. Sin fila = sin reserva.
async function book(tenantId, { serviceId, staffId, customerName, customerPhone, scheduledAt }) {
  try {
    const { rows } = await pool.query(
      `insert into appointments (tenant_id, service_id, staff_id, customer_name, customer_phone, scheduled_at, price_cents, status)
       select s.tenant_id, s.id, u.id, $4, $5, $6, s.price_cents, 'booked'
       from services s
       join users u on u.tenant_id = s.tenant_id and u.id = $3 and u.active
       where s.tenant_id = $1 and s.id = $2 and s.active
       returning id, staff_id, scheduled_at, status, price_cents`,
      [tenantId, serviceId, staffId, customerName, customerPhone, scheduledAt]
    );
    if (!rows[0]) throw fail(404, 'Servicio o profesional no encontrado');
    return rows[0];
  } catch (e) {
    // uq_appointments_staff_slot: otro cliente ganó la franja
    if (e.code === '23505') throw fail(409, 'Ese profesional ya está ocupado a esa hora');
    throw e;
  }
}

// Cobro atómico: cita completada + movimientos de caja + comisión, todo a nombre de userId.
// userId llega del JWT (controlador), nunca del body.
async function complete(tenantId, userId, appointmentId, payments) {
  const client = await pool.connect();
  try {
    await client.query('begin');

    const staff = await client.query(
      `select 1 from users where tenant_id = $1 and id = $2 and active`,
      [tenantId, userId]
    );
    if (!staff.rows[0]) throw fail(403, 'Usuario sin acceso a este negocio');

    const { rows } = await client.query(
      `select a.price_cents, a.customer_name, s.name as service_name,
              least(coalesce(s.staff_payout_cents, 0), a.price_cents) as payout_cents
       from appointments a
       left join services s on s.id = a.service_id
       where a.tenant_id = $1 and a.id = $2 and a.status = 'booked'
       for update of a`,
      [tenantId, appointmentId]
    );
    const appt = rows[0];
    if (!appt) throw fail(404, 'Cita no encontrada o ya cobrada');

    const paid = payments.reduce((t, p) => t + p.amountCents, 0);
    if (paid !== appt.price_cents) throw fail(400, 'Los pagos no suman el precio de la cita');

    await client.query(
      `update appointments set status = 'completed', staff_id = $3
       where tenant_id = $1 and id = $2`,
      [tenantId, appointmentId, userId]
    );

    const concept = [appt.service_name, appt.customer_name].filter(Boolean).join(' · ') || 'Cita';
    for (const [i, p] of payments.entries()) {
      // Pago mixto = dos movimientos; la comisión se anota una sola vez.
      await client.query(
        `insert into transactions (tenant_id, type, concept, amount_cents, method, staff_id, appointment_id, staff_payout_cents)
         values ($1, 'income', $2, $3, $4, $5, $6, $7)`,
        [tenantId, concept, p.amountCents, p.method, userId, appointmentId, i === 0 ? appt.payout_cents : null]
      );
    }

    await client.query('commit');
    return { id: appointmentId, status: 'completed', staff_id: userId, staff_payout_cents: appt.payout_cents };
  } catch (e) {
    await client.query('rollback');
    throw e;
  } finally {
    client.release();
  }
}

async function updateStatus(tenantId, appointmentId, status) {
  const { rows } = await pool.query(
    `update appointments set status = $3
     where tenant_id = $1 and id = $2
     returning id, status`,
    [tenantId, appointmentId, status]
  );
  if (!rows[0]) throw fail(404, 'Cita no encontrada');
  return rows[0];
}

module.exports = { listByDay, book, complete, updateStatus };
