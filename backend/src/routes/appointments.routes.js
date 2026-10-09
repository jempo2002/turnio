const router = require('express').Router();
const { requireAuth } = require('../middlewares/auth');
const ctrl = require('../controllers/appointments.controller');

router.use(requireAuth);
router.get('/', ctrl.listByDay);
router.post('/', ctrl.book);
router.post('/:id/complete', ctrl.complete);
router.patch('/:id/status', ctrl.updateStatus);

module.exports = router;
