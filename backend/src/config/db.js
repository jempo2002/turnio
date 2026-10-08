const { Pool } = require('pg');

// ponytail: un solo pool, sin capa ORM. Toda query es parametrizada ($1, $2...) -> cero inyección SQL.
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: process.env.DATABASE_URL?.includes('supabase') ? { rejectUnauthorized: false } : false,
});

module.exports = pool;
