# Tuktuk Queue API (FastAPI + Supabase)

## Architecture

- **Supabase (Postgres + Auth + Realtime)** is the source of truth. Flutter
  reads queue state and subscribes to realtime changes **directly** from
  Supabase - no need to route plain reads through this API.
- **This FastAPI service** owns only the privileged, multi-step actions that
  shouldn't be trusted to the client: joining the queue, reordering a line,
  the overtake cascade, status changes, and voiding an entry. It talks to
  Postgres using the Supabase **service role key**, which bypasses Row Level
  Security - that's exactly why these actions live in a trusted server
  instead of being raw client writes.

Run the SQL in `tuktuk_schema.sql` (from the earlier step) against your
Supabase project before starting this API - the tables, RLS policies, and
the `overtake_driver()` function all need to exist first.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# then fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_JWT_SECRET
# (all three are on Supabase Dashboard -> Project Settings -> API)
```

## Run

```bash
uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000/docs` for the interactive Swagger UI (auto-
generated - this is one of the reasons FastAPI was chosen over Flask).

## Auth model

- **Admin / Monitor**: log in via Supabase Auth from Flutter
  (`supabase_flutter`'s `signInWithPassword`, etc.). Flutter then sends the
  resulting `session.accessToken` as a `Bearer` token on every request to
  this API. `app/dependencies.py` verifies that JWT and looks up the
  caller's role from the `profiles` table.
- **Driver**: no login. `/driver/search/{plate_number}` is public by design.

## Endpoints

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/admin/queue/join` | admin | Register a tuktuk into a line |
| POST | `/admin/queue/reorder` | admin | Persist a drag-and-drop reorder |
| POST | `/admin/queue/void` | admin | Remove a driver from the queue |
| PATCH | `/monitor/queue/{id}/status` | monitor, admin | waiting → loading → completed |
| POST | `/queue/overtake` | admin, monitor | Mark not-ready, move to back of line |
| GET | `/driver/search/{plate_number}` | public | Driver checks their own position |
| GET | `/health` | public | Health check |

## Next step

Flutter app: `supabase_flutter` for auth + realtime reads, this API's base
URL for the privileged POST/PATCH actions above.
# tuktuk
# tuktuk
