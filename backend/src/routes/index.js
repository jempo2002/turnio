const router = require('express').Router();

router.use('/public', require('./public.routes'));
router.use('/appointments', require('./appointments.routes'));
router.use('/users', require('./users.routes'));

module.exports = router;
