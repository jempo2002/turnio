const svc = require('../services/users.service');

exports.listStaff = async (req, res, next) => {
  try { res.json(await svc.listStaff(req.auth.tenantId)); }
  catch (e) { next(e); }
};
