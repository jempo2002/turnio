const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function fail(status, message) {
  const e = new Error(message);
  e.status = status;
  return e;
}

const isUuid = (v) => typeof v === 'string' && UUID.test(v);
const isSlug = (v) => typeof v === 'string' && /^[a-z0-9-]{1,60}$/.test(v);
const text = (v, max) => (typeof v === 'string' ? v.trim().slice(0, max) : '');

function instant(v) {
  const d = new Date(v);
  return typeof v === 'string' && !isNaN(d) ? d : null;
}

// El precio no se lee del cliente: sale del servicio en la base de datos.
function bookingInput(body) {
  const at = instant(body.scheduledAt);
  const customerName = text(body.customerName, 60);
  if (!isUuid(body.serviceId) || !isUuid(body.staffId) || !at || !customerName) {
    throw fail(400, 'Datos de reserva inválidos');
  }
  return {
    serviceId: body.serviceId,
    staffId: body.staffId,
    scheduledAt: at.toISOString(),
    customerName,
    customerPhone: String(body.customerPhone ?? '').replace(/\D/g, '').slice(0, 15),
  };
}

module.exports = { fail, isUuid, isSlug, instant, bookingInput };
