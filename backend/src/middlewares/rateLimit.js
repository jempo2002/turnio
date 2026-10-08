// ponytail: contador en memoria, por proceso. Con más de una instancia o detrás de un proxy
// (req.ip sería el del proxy: configurar 'trust proxy'), pasar a express-rate-limit + Redis.
module.exports = function rateLimit(max, windowMs) {
  const hits = new Map();
  return (req, res, next) => {
    const now = Date.now();
    if (hits.size > 10000) hits.clear();
    const h = hits.get(req.ip);
    if (!h || h.reset < now) { hits.set(req.ip, { n: 1, reset: now + windowMs }); return next(); }
    if (++h.n > max) return res.status(429).json({ error: 'Demasiadas solicitudes, intenta en un momento' });
    next();
  };
};
