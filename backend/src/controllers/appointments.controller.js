const svc = require('../services/appointments.service');
const { fail, isUuid, bookingInput } = require('../validate');

exports.listByDay = async (req, res, next) => {
  try {
    const day = req.query.day || new Date().toISOString().slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) throw fail(400, 'Fecha inválida');
    res.json(await svc.listByDay(req.auth.tenantId, day));
  } catch (e) { next(e); }
};

// Agenda manual: sin staffId, la cita queda a nombre de quien la crea.
exports.book = async (req, res, next) => {
  try {
    const input = bookingInput({ ...req.body, staffId: req.body.staffId ?? req.auth.userId });
    res.status(201).json(await svc.book(req.auth.tenantId, input));
  } catch (e) { next(e); }
};

// Quién cobra = req.auth.userId (JWT verificado). Cualquier staffId en el body se ignora.
exports.complete = async (req, res, next) => {
  try {
    const payments = req.body.payments;
    const valid = isUuid(req.params.id) && Array.isArray(payments) && payments.length >= 1 && payments.length <= 2 &&
      payments.every((p) => p && ['cash', 'transfer'].includes(p.method) && Number.isInteger(p.amountCents) && p.amountCents > 0);
    if (!valid) throw fail(400, 'Datos de cobro inválidos');

    res.json(await svc.complete(
      req.auth.tenantId,
      req.auth.userId,
      req.params.id,
      payments.map((p) => ({ method: p.method, amountCents: p.amountCents }))
    ));
  } catch (e) { next(e); }
};

exports.updateStatus = async (req, res, next) => {
  try {
    // 'completed' no entra por aquí: solo por /complete, que registra caja y comisión.
    const allowed = ['available', 'booked', 'blocked', 'cancelled'];
    if (!isUuid(req.params.id) || !allowed.includes(req.body.status)) throw fail(400, 'Estado inválido');
    res.json(await svc.updateStatus(req.auth.tenantId, req.params.id, req.body.status));
  } catch (e) { next(e); }
};
