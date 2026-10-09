-- Turnio — esquema multi-tenant (PostgreSQL / Supabase)
-- Aislamiento de datos: tenant_id en cada tabla operativa + Row Level Security.

create extension if not exists "pgcrypto";

-- ===== tenants =====
create table tenants (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  slug       text not null unique,
  active     boolean not null default true,
  created_at timestamptz not null default now()
);

-- ===== users (empleados / roles) =====
create table users (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  email         text not null,
  password_hash text not null,          -- bcrypt/argon2; nunca se expone en respuestas
  full_name     text not null,
  role          text not null check (role in ('owner','admin','staff')),
  active        boolean not null default true,
  created_at    timestamptz not null default now(),
  unique (tenant_id, email)
);

-- ===== services (catálogo) =====
create table services (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenants(id) on delete cascade,
  name               text not null,
  duration_minutes   int  not null check (duration_minutes > 0),
  price_cents        int  not null check (price_cents >= 0),
  staff_payout_cents int  not null check (staff_payout_cents >= 0),
  active             boolean not null default true,
  created_at         timestamptz not null default now()
);

-- ===== appointments (citas) =====
create table appointments (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  service_id      uuid references services(id) on delete set null,
  staff_id        uuid references users(id) on delete set null,
  customer_name   text,
  customer_phone  text,
  scheduled_at    timestamptz not null,
  status          text not null check (status in ('available','booked','completed','blocked','cancelled')) default 'available',
  price_cents     int not null default 0 check (price_cents >= 0),
  created_at      timestamptz not null default now()
);

-- ===== inventory (productos) =====
create table inventory (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  barcode     text not null,
  emoji       text,
  name        text not null,
  quantity    int  not null default 0 check (quantity >= 0),
  cost_cents  int  not null check (cost_cents >= 0),
  price_cents int  not null check (price_cents >= 0),
  units_sold  int  not null default 0 check (units_sold >= 0),
  created_at  timestamptz not null default now(),
  unique (tenant_id, barcode)
);

-- ===== transactions (caja) =====
create table transactions (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenants(id) on delete cascade,
  type               text not null check (type in ('income','expense')),
  concept            text not null,
  amount_cents       int  not null check (amount_cents >= 0),
  method             text not null check (method in ('cash','transfer')),
  staff_id           uuid references users(id) on delete set null,
  appointment_id     uuid references appointments(id) on delete set null,
  staff_payout_cents int,
  created_at         timestamptz not null default now()
);

-- ===== índices para consultas recurrentes (agenda del día, caja por rango) =====
create index idx_appointments_tenant_date on appointments (tenant_id, scheduled_at);
create index idx_transactions_tenant_date on transactions (tenant_id, created_at);
create index idx_inventory_tenant_barcode on inventory (tenant_id, barcode);
create index idx_users_tenant_email       on users (tenant_id, email);

-- ===== Row Level Security: aislamiento duro por tenant =====
-- Requiere que el JWT (Supabase auth) lleve tenant_id en app_metadata.
alter table users        enable row level security;
alter table services     enable row level security;
alter table appointments enable row level security;
alter table inventory    enable row level security;
alter table transactions enable row level security;

create policy tenant_isolation_users        on users        using (tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid);
create policy tenant_isolation_services     on services     using (tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid);
create policy tenant_isolation_appointments on appointments using (tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid);
create policy tenant_isolation_inventory    on inventory    using (tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid);
create policy tenant_isolation_transactions on transactions using (tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid);

-- El backend (pool con service_role) hace doble candado: además de RLS,
-- cada query parametrizada incluye "and tenant_id = $1" (ver src/middlewares/tenant.js).
