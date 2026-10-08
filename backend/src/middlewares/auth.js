const jwt = require('jsonwebtoken');

// Verifica el JWT (emitido por Supabase Auth) y adjunta tenant_id/role.
// tenant_id viene del token firmado por el servidor, nunca de body/query del cliente:
// evita que un usuario pida datos de otro negocio cambiando un parámetro.
function requireAuth(req, res, next) {
  const header = req.headers.authorization || '';
  const token = header.startsWith('Bearer ') ? header.slice(7) : null;
  if (!token) return res.status(401).json({ error: 'No autenticado' });

  try {
    const payload = jwt.verify(token, process.env.SUPABASE_JWT_SECRET, { algorithms: ['HS256'] });
    const tenantId = payload.app_metadata?.tenant_id;
    if (!tenantId) return res.status(403).json({ error: 'Token sin tenant asignado' });

    req.auth = { userId: payload.sub, tenantId, role: payload.app_metadata?.role || 'staff' };
    next();
  } catch (e) {
    return res.status(401).json({ error: 'Token inválido o expirado' });
  }
}

function requireRole(...roles) {
  return (req, res, next) => {
    if (!roles.includes(req.auth?.role)) return res.status(403).json({ error: 'Permiso insuficiente' });
    next();
  };
}

module.exports = { requireAuth, requireRole };
