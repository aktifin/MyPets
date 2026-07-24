# MyPets Backend

This directory contains the first runnable FastAPI modular-monolith slice for MyPets.
It owns account authentication, persistent device credentials, server-authoritative pet
snapshots, account-pet relations, append-only semantic synchronization events, and administrator-reviewed pet asset publishing.

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
`MYPETS_DATABASE_URL` to PostgreSQL, set a unique `MYPETS_JWT_SECRET`, configure `MYPETS_ADMIN_USERNAMES`, and replace the development filesystem object store with managed object storage.

## Authentication model

1. An account signs in with a short-lived account access token.
2. The account binds a physical device and receives a high-entropy device secret once.
3. The client stores the device secret in the operating-system credential store.
4. The device exchanges that secret for a time-limited device access token.
5. Synchronization endpoints accept device access tokens only.

Raw passwords and raw device secrets are never stored in the database.


## Administrator pet publishing

Configure at least two administrator usernames for editor/reviewer separation:

```powershell
$env:MYPETS_ADMIN_USERNAMES = "pet_editor,pet_reviewer"
$env:MYPETS_ASSET_STORAGE_DIR = "D:\MyPetsData\assets"
```

The publishing API validates ZIP path safety, required actions, fallback cycles, image decoding, spritesheet dimensions, optional per-file hashes, and package limits. Approved releases are immutable and exposed through the public pet asset catalog. See `../docs/管理员宠物发布链路.md`.
