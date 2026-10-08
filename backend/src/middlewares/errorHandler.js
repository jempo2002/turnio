// Handler único: nunca deja escapar detalle interno (stack, SQL) al cliente.
module.exports = function errorHandler(err, req, res, _next) {
  const status = err.status || 500;
  if (status === 500) console.error(err);
  res.status(status).json({ error: status === 500 ? 'Error interno' : err.message });
};
