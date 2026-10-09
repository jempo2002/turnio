const router = require('express').Router();
const { requireAuth } = require('../middlewares/auth');
const ctrl = require('../controllers/users.controller');

router.use(requireAuth);
router.get('/staff', ctrl.listStaff);

module.exports = router;
