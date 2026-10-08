-- Turnio — reservas públicas por profesional. Correr después de schema.sql.

alter table users add column if not exists photo_url text;

-- Candado de concurrencia: dos clientes no pueden quedarse con el mismo profesional a la misma hora.
-- Solo cuentan los turnos vigentes: al completar o cancelar, el profesional queda libre otra vez.
-- ponytail: compara la hora de inicio exacta (agenda en franjas fijas). Si llegan duraciones
-- variables, cambiar por un exclusion constraint con tstzrange.
create unique index if not exists uq_appointments_staff_slot
  on appointments (tenant_id, staff_id, scheduled_at)
  where status in ('booked', 'blocked');
