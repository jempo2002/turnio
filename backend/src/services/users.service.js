const pool = require('../config/db');

// Lista explícita de columnas: password_hash jamás sale de aquí hacia la API.
async function listStaff(tenantId) {
  const { rows } = await pool.query(
    `select id, full_name, role, active
     from users
     where tenant_id = $1
     order by full_name`,
    [tenantId]
  );
  return rows;
}

module.exports = { listStaff };
