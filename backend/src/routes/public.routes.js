const router = require('express').Router();
const rateLimit = require('../middlewares/rateLimit');
const ctrl = require('../controllers/public.controller');

// Sin autenticación: es la página de reservas del cliente final.
router.get('/:slug', rateLimit(120, 60000), ctrl.business);
router.get('/:slug/availability', rateLimit(120, 60000), ctrl.availability);
router.post('/:slug/appointments', rateLimit(10, 60000), ctrl.book);

module.exports = router;
