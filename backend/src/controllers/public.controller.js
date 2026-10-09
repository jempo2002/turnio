const svc = require('../services/public.service');
const appointments = require('../services/appointments.service');
const { fail, isSlug, instant, bookingInput } = require('../validate');

async function tenant(slug) {
  if (!isSlug(slug)) throw fail(404, 'Negocio no encontrado');
  const t = await svc.business(slug);
  if (!t) throw fail(404, 'Negocio no encontrado');
  return t;
}

exports.business = async (req, res, next) => {
  try {
    const t = await tenant(req.params.slug);
    res.json({ name: t.name, services: t.services });
  } catch (e) { next(e); }
};

exports.availability = async (req, res, next) => {
  try {
    const at = instant(req.query.at);
    if (!isSlug(req.params.slug) || !at) throw fail(400, 'Hora inválida');
    res.json(await svc.availability(req.params.slug, at.toISOString()));
  } catch (e) { next(e); }
};

exports.book = async (req, res, next) => {
  try {
    const input = bookingInput(req.body);
    if (new Date(input.scheduledAt) < new Date()) throw fail(400, 'Esa hora ya pasó');
    const t = await tenant(req.params.slug);
    const a = await appointments.book(t.id, input);
    res.status(201).json({ id: a.id, scheduled_at: a.scheduled_at, status: a.status, price_cents: a.price_cents });
  } catch (e) { next(e); }
};
