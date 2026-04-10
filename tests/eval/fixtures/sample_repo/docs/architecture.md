# Sample API architecture

- `app/handlers/` — FastAPI routers, thin glue
- `app/services/` — business logic (auth, db)
- `app/models/` — SQLAlchemy models
- `app/workers/` — background jobs (cleanup of expired sessions)

## Auth flow

1. `POST /auth/login` → `authenticate` → `issue_tokens` → returns access+refresh
2. `POST /auth/refresh` → `refresh_access_token` → returns new access
3. `current_user` resolves access tokens via the `sessions` table

The cleanup worker periodically deletes expired Session rows.
