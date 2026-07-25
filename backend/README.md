# MyPets Backend

This directory contains the runnable FastAPI modular monolith for MyPets.
It owns account authentication, persistent device credentials, server-authoritative pet
snapshots, account-pet relations, friendship, shared care, asynchronous visits, append-only
semantic synchronization events, the user Web portal, administrator-reviewed pet asset
publishing, administrator governance, and the administrator console.

The desktop SQLite database remains a rebuildable offline cache. It must not be treated as
the authority for pet growth, ownership, presence, or cross-device read state.

## Local development

```powershell
cd backend
python -m pip install -e ".[dev]"
$env:MYPETS_JWT_SECRET = "replace-with-at-least-24-random-characters"
$env:MYPETS_ADMIN_USERNAMES = "local_admin"
python -m uvicorn mypets_backend.main:app --reload
```

Open the user portal at:

```text
http://127.0.0.1:8000/portal
```

Open the administrator console at:

```text
http://127.0.0.1:8000/admin
```

The default database is SQLite for development. Production deployment must set
`MYPETS_DATABASE_URL` to PostgreSQL, set a unique `MYPETS_JWT_SECRET`, configure
administrator roles, and replace the development filesystem object store with managed
object storage.

## Authentication model

1. An account signs in with a short-lived account access token.
2. The account binds a physical device and receives a high-entropy device secret once.
3. The client stores the device secret in the operating-system credential store.
4. The device exchanges that secret for a time-limited device access token.
5. Synchronization endpoints accept device access tokens only.

Raw passwords and raw device secrets are never stored in the database.

The user portal stores its short-lived account token only in browser `sessionStorage`.
It does not use persistent `localStorage` or authentication cookies.

## User Web portal

The `/portal` application supports:

- account registration and login;
- display-name and password maintenance;
- pet creation and account-level Web pet selection;
- safe pet name and personality configuration;
- pet visibility and remote-care settings;
- friend requests, friend removal, blocking, and unblocking;
- caregiver and viewer invitation maintenance;
- asynchronous visit requests, decisions, recall, paired read-only pet status cards, and
  visit history;
- responsive visit forms and stacked pet cards for narrow mobile layouts.

Web pet selection is independent from each physical device's `active_pet_id`. Pet
configuration and visit presence changes publish the same semantic synchronization events
used by the PC client. The portal only lists host pets already filtered by the friendship and
privacy API.

See `../docs/Web用户门户.md`.

## Asynchronous pet visits

Friend accounts can request a bounded visit between one self-managed visitor pet and one
friend-visible host pet. The host accepts or rejects the request. An accepted visitor pet
moves to `visiting`, cannot receive normal care actions, and returns to `home` when the visit
expires, its owner recalls it, the accounts block each other, or friendship is removed.

Visit settlement is lazy and server-authoritative. Pet list, bootstrap, portal dashboard,
visit list, and care requests settle due visits before returning a snapshot or applying a
mutation. Pending requests expire after 24 hours.

```text
POST /api/v1/visits
GET  /api/v1/visits
POST /api/v1/visits/{visit_id}/accept
POST /api/v1/visits/{visit_id}/reject
POST /api/v1/visits/{visit_id}/cancel
POST /api/v1/visits/{visit_id}/recall
```

See `../docs/异步串门.md`.

## Administrator roles

`MYPETS_ADMIN_USERNAMES` remains a backward-compatible super-administrator list. For
production separation of duties, configure explicit roles:

```powershell
$env:MYPETS_ADMIN_EDITORS = "pet_editor"
$env:MYPETS_ADMIN_REVIEWERS = "pet_reviewer"
$env:MYPETS_ADMIN_PUBLISHERS = "pet_publisher"
$env:MYPETS_ADMIN_AUDITORS = "pet_auditor"
$env:MYPETS_ADMIN_SUPERADMINS = "platform_admin"
$env:MYPETS_ASSET_STORAGE_DIR = "D:\MyPetsData\assets"
```

The server enforces these permissions even when a client manually calls an endpoint:

- editors create templates and versions, upload packages, and submit review;
- reviewers approve or reject submitted versions;
- publishers publish immutable releases and switch the stable deployment pointer;
- auditors read administrative audit logs;
- super-administrators have all permissions.

## Administrator pet publishing

The publishing API validates ZIP path safety, required actions, fallback cycles, image
decoding, spritesheet dimensions, optional per-file hashes, and package limits. Approved
releases are immutable and exposed through the public pet asset catalog.

Every new release moves the template's `stable` deployment channel to the new immutable
release. A publisher can roll the channel back to an older release without deleting or
rewriting any package. The public stable lookup is:

```text
GET /api/v1/catalog/pet-assets/latest?template_id=official.cat.white
```

The web console provides template creation, version management, upload progress, protected
visual preview, continuous frame playback, action matrices, version comparison, device
aspect-ratio simulation, review decisions, release history, safe rollback, and audit queries.
Browser tokens are session-only and preview images require Bearer authentication.

See:

- `../docs/管理员宠物发布链路.md`
- `../docs/管理员Web管理台.md`
- `../docs/管理员分权与视觉验收.md`
