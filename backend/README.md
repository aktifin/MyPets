# MyPets Backend

This directory contains the first runnable FastAPI modular-monolith slice for MyPets.
It owns account authentication, persistent device credentials, server-authoritative pet
snapshots, account-pet relations, and append-only semantic synchronization events.

The desktop SQLite database remains a rebuildable offline cache. It must not be treated as
the authority for pet growth, ownership, presence, or cross-device read state.

## Local development

```powershell
cd backend
python -m pip install -e ".[dev]"
$env:MYPETS_JWT_SECRET = "replace-with-at-least-24-random-characters"
python -m uvicorn mypets_backend.main:app --reload
```

The default database is SQLite for development. Production deployment must set
`MYPETS_DATABASE_URL` to PostgreSQL and set a unique `MYPETS_JWT_SECRET`.

## Authentication model

1. An account signs in with a short-lived account access token.
2. The account binds a physical device and receives a high-entropy device secret once.
3. The client stores the device secret in the operating-system credential store.
4. The device exchanges that secret for a time-limited device access token.
5. Synchronization endpoints accept device access tokens only.

Raw passwords and raw device secrets are never stored in the database.
