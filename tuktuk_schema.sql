-- ============================================================
-- TUKTUK QUEUE MANAGEMENT — SUPABASE (POSTGRES) SCHEMA
-- ============================================================

-- ------------------------------------------------------------
-- 1. ENUM TYPES
-- ------------------------------------------------------------
create type user_role as enum ('admin', 'monitor', 'driver');
create type queue_status as enum ('waiting', 'loading', 'completed', 'not_ready', 'void');
create type audit_action as enum (
  'joined', 'status_changed', 'reordered', 'overtaken', 'voided'
);

-- ------------------------------------------------------------
-- 2. PROFILES (extends Supabase auth.users for admin/monitor)
-- ------------------------------------------------------------
create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null,
  role user_role not null default 'monitor',
  created_at timestamptz not null default now()
);

-- ------------------------------------------------------------
-- 3. STATIONS & LINES
-- ------------------------------------------------------------
create table stations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

create table lines (
  id uuid primary key default gen_random_uuid(),
  station_id uuid not null references stations(id) on delete cascade,
  line_number int not null,
  is_active boolean not null default true,
  unique (station_id, line_number)
);

-- ------------------------------------------------------------
-- 4. DRIVERS (no login required — looked up by plate number)
-- ------------------------------------------------------------
create table drivers (
  id uuid primary key default gen_random_uuid(),
  plate_number text not null unique,
  name text,
  phone text,
  created_at timestamptz not null default now()
);

create index idx_drivers_plate on drivers (plate_number);

-- ------------------------------------------------------------
-- 5. QUEUE ENTRIES — the live, ordered queue
-- ------------------------------------------------------------
-- position is numeric (not int) so admin can insert a driver
-- BETWEEN two existing positions (e.g. 2.0 and 3.0 -> 2.5)
-- without renumbering the whole line.
create table queue_entries (
  id uuid primary key default gen_random_uuid(),
  line_id uuid not null references lines(id) on delete cascade,
  driver_id uuid not null references drivers(id) on delete cascade,
  status queue_status not null default 'waiting',
  position numeric not null,
  joined_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  updated_by uuid references profiles(id)
);

create index idx_queue_line_position on queue_entries (line_id, position);
create index idx_queue_status on queue_entries (status);

-- Only one ACTIVE entry per driver at a time (can't be in two lines at once)
create unique index uniq_driver_active_entry
  on queue_entries (driver_id)
  where status in ('waiting', 'loading', 'not_ready');

-- ------------------------------------------------------------
-- 6. AUDIT LOG — every change, for dispute resolution
-- ------------------------------------------------------------
create table audit_logs (
  id uuid primary key default gen_random_uuid(),
  queue_entry_id uuid references queue_entries(id) on delete set null,
  action audit_action not null,
  performed_by uuid references profiles(id),
  from_status queue_status,
  to_status queue_status,
  from_position numeric,
  to_position numeric,
  note text,
  created_at timestamptz not null default now()
);

-- ------------------------------------------------------------
-- 7. updated_at trigger
-- ------------------------------------------------------------
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger trg_queue_entries_updated_at
before update on queue_entries
for each row execute function set_updated_at();

-- ============================================================
-- 8. ROW LEVEL SECURITY
-- ============================================================
alter table profiles enable row level security;
alter table stations enable row level security;
alter table lines enable row level security;
alter table drivers enable row level security;
alter table queue_entries enable row level security;
alter table audit_logs enable row level security;

-- Helper: fetch role of the current authenticated user
create or replace function current_user_role()
returns user_role as $$
  select role from profiles where id = auth.uid();
$$ language sql stable security definer;

-- ---- PROFILES ----
create policy "profiles: self read"
  on profiles for select
  using (id = auth.uid());

-- ---- STATIONS / LINES: everyone (incl. anonymous drivers) can read ----
create policy "stations: public read"
  on stations for select
  using (true);

create policy "lines: public read"
  on lines for select
  using (true);

create policy "lines: admin write"
  on lines for insert with check (current_user_role() = 'admin');
create policy "lines: admin update"
  on lines for update using (current_user_role() = 'admin');

-- ---- DRIVERS: public read (so driver search works without login) ----
create policy "drivers: public read"
  on drivers for select
  using (true);

create policy "drivers: admin insert"
  on drivers for insert with check (current_user_role() = 'admin');

-- ---- QUEUE ENTRIES ----
-- Anyone (including anonymous driver-search screen) can read queue state.
create policy "queue: public read"
  on queue_entries for select
  using (true);

-- Only admin can insert new entries (register a tuktuk into a line)
create policy "queue: admin insert"
  on queue_entries for insert
  with check (current_user_role() = 'admin');

-- Admin can update anything (status + position) = reorder / overtake
create policy "queue: admin update"
  on queue_entries for update
  using (current_user_role() = 'admin');

-- Monitor can ONLY flip status to completed/loading — not reorder.
-- Enforced by restricting which columns effectively change via a
-- BEFORE UPDATE trigger (RLS alone can't diff old vs new position),
-- see trg_monitor_guard below.
create policy "queue: monitor update status"
  on queue_entries for update
  using (current_user_role() = 'monitor');

create or replace function guard_monitor_update()
returns trigger as $$
begin
  if current_user_role() = 'monitor' then
    if new.position is distinct from old.position
       or new.line_id is distinct from old.line_id then
      raise exception 'Monitors cannot reorder or move lines';
    end if;
  end if;
  return new;
end;
$$ language plpgsql security definer;

create trigger trg_monitor_guard
before update on queue_entries
for each row execute function guard_monitor_update();

-- Admin can delete/void
create policy "queue: admin delete"
  on queue_entries for delete
  using (current_user_role() = 'admin');

-- ---- AUDIT LOGS: admin + monitor can read, nobody but server writes ----
create policy "audit: staff read"
  on audit_logs for select
  using (current_user_role() in ('admin', 'monitor'));

-- No insert policy for regular clients — only the FastAPI service role
-- (which bypasses RLS) writes audit rows, guaranteeing every mutation
-- that matters is logged server-side rather than trusted to the client.

-- ============================================================
-- 9. RPC FUNCTION EXAMPLE: overtake (not_ready -> back of line)
-- ============================================================
-- Called from FastAPI using the service role, wrapped in a transaction.
-- Kept here too as a Postgres function so it can also be called directly
-- via Supabase RPC if you decide you don't need FastAPI for this one.
create or replace function overtake_driver(p_queue_entry_id uuid, p_actor uuid)
returns void as $$
declare
  v_line_id uuid;
  v_max_position numeric;
begin
  select line_id into v_line_id from queue_entries where id = p_queue_entry_id;

  select coalesce(max(position), 0) into v_max_position
  from queue_entries
  where line_id = v_line_id and status in ('waiting', 'loading', 'not_ready');

  update queue_entries
  set status = 'not_ready',
      position = v_max_position + 1,
      updated_by = p_actor
  where id = p_queue_entry_id;

  insert into audit_logs (queue_entry_id, action, performed_by, to_status, to_position, note)
  values (p_queue_entry_id, 'overtaken', p_actor, 'not_ready', v_max_position + 1,
          'Driver not ready, moved to back of line');
end;
$$ language plpgsql security definer;
