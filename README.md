# HomeSphere — personal cloud demo

A compact dark-themed personal cloud: React + FastAPI + PostgreSQL + Alembic + Docker Compose. Existing accounts, file bytes, metadata and historical `homes` rows are retained.

## Run

For the existing project in Ubuntu WSL:

```sh
cd ~/projects/homesphere
docker compose up -d --build
```

Open http://localhost:8080 and sign in with your existing owner account. API documentation is at http://localhost:8080/docs. PostgreSQL readiness → migration → API → Nginx is handled by Compose. A completed `migrate` container is normal.

For a fresh checkout, copy `.env.example` to `.env`, set `POSTGRES_PASSWORD` and the matching URL-encoded `DATABASE_URL`, then start Compose. Create the owner interactively:

```sh
docker compose exec api python -m app.create_owner
```

Never replace the existing `.env` or run `docker compose down -v` on your personal deployment. To stop safely, use `docker compose stop`.

## What works

- Upload (25 MiB per file), byte-exact attachment download, preview, rename, categories, search, grid/list and upload progress.
- Create nested folders, browse with breadcrumbs, and upload into the current folder. Existing files start at **My files**.
- **Recent uploads** shows the latest ten active uploads across all folders. Rename and restore do not change upload time.
- **Recycle bin** retains bytes and original folder, supports restore, and asks before permanent deletion. Bin files continue to consume storage.
- **Share** creates an anonymous attachment-download link, valid for 1 hour, 24 hours or 7 days. Copy a new link before closing; existing links can be revoked. Trashing a file revokes all its links, and restoring it does not reactivate them.
- Searching from **Folders** spans active files in every folder; searching in Recent or Recycle bin filters that view.

The charcoal dashboard, sphere, login, previews and existing architecture are preserved. Public links use the current server address. The existing deployment binds to loopback: a localhost link works on this machine; sharing with another device requires a deliberate HTTPS/network deployment.

## API changes

All private routes require the existing owner session; writes require an exact same Origin. IDs are UUIDs. `/public/{token}` alone is anonymous and read-only.

| Method | Route | Behavior |
|---|---|---|
| POST | `/folders` | `{name, parent_id: UUID or null}` |
| GET | `/folders?parent_id=root&skip=0&limit=100` | Child folders; `parent_id` may also be a folder UUID |
| POST | `/files?folder_id=UUID` | Existing multipart upload; omit folder for root |
| GET | `/files?folder_id=root&q=notes&trashed=false` | Optional folder/search/bin filters; omit folder for all folders |
| GET | `/files/recent?limit=10` | Newest active files, stable timestamp/ID order |
| DELETE | `/files/{id}` | Move to recycle bin; replaces immediate permanent deletion |
| POST | `/files/{id}/restore` | Restore to original folder if content still exists |
| DELETE | `/files/{id}/permanent` | Permanently remove a file already in the bin |
| POST | `/files/{id}/shares` | `{expires_in_hours: 1..168}`; returns the random link once |
| GET | `/files/{id}/shares` | Link IDs, creation/expiry/revocation; no secrets |
| DELETE | `/files/{id}/shares/{share_id}` | Revoke a link (repeat revocation is safe) |
| GET | `/public/{token}` | Attachment bytes only while link and file remain active |

The existing list pagination is retained: `skip >= 0`, `limit` 1–100. API search treats `%` and `_` literally. Duplicate file display names remain supported. Sibling folder names are unique under PostgreSQL `lower(name)` after filename normalization.

## Data and security decisions

This remains a **single-owner local demo**, with explicit resource ownership checks. There is no registration, team collaboration or multi-user UI. Existing files are assigned to the established owner by the additive `c84e72a190fd` migration; a populated pre-auth database without that owner is rejected before changes. No bytes move during migration. A destructive downgrade is refused; roll back deliberately from the saved source/database/uploads backup.

Folders are virtual database records, never disk paths. The shared filename validator rejects traversal, separators, controls and unsafe portable names. File bytes use random storage keys with no-follow opens. Upload and permanent deletion use the existing durable intent journal, volume lock and restart recovery. Soft delete/revocation is one database transaction. Restore checks the stored payload before exposing metadata. Missing content keeps metadata for recovery and returns 409.

Share tokens use `secrets.token_urlsafe(32)` (256 random bits); only SHA-256 digests are stored. Expiration and revocation are checked on each download, under the same lock as deletion. Downloads have attachment disposition, `nosniff`, `no-store` and `no-referrer`. Nginx suppresses public-link access logging; the API image disables access logging to keep tokens out of request logs. Use the same settings if running Uvicorn manually.

Private cookies keep the existing HttpOnly/SameSite session design. For a remote deployment, configure HTTPS, Secure cookies and permitted hosts/Origins intentionally; do not simply expose the debug port.

## Verify

```sh
docker compose exec -T api python -m pytest -q -p no:cacheprovider
docker compose exec -T api alembic check
python3 scripts/smoke_test.py
```

The smoke test asks for credentials privately and removes only its own uploaded file, including the new bin/restore/permanent-delete lifecycle.

Normal tests use temporary SQLite/storage and can run with networking disabled. PostgreSQL tests are opt-in and **drop/recreate tables only in a disposable database named `homesphere_test_*`**:

```sh
# Run these in a disposable test container/network; never use the personal database.
HOMESPHERE_TEST_DATABASE_URL=postgresql+psycopg://USER:PASS@HOST/homesphere_test_suite \
  python -m pytest tests/test_cloud.py tests/test_files.py tests/test_auth.py tests/test_homes.py -q
HOMESPHERE_MIGRATION_TEST_URL=postgresql+psycopg://USER:PASS@HOST/homesphere_test_migrations \
  python -m pytest tests/test_migrations.py -q
```

The migration tests cover both a fresh database and preserved populated rows. They also verify refusal to guess ownership of pre-auth files and refusal of a destructive downgrade.

`frontend/tests/cloud.e2e.cjs` is a reusable Playwright browser check. Install Playwright in a test environment (`npm install --no-save playwright`, `npx playwright install chromium`), set `HOMESPHERE_E2E_URL`, `HOMESPHERE_E2E_USERNAME`, `HOMESPHERE_E2E_PASSWORD` to an isolated demo account, then run `node tests/cloud.e2e.cjs` from `frontend`. It creates its own nested test folders and file, verifies the complete flow, and permanently removes its own file. Empty test folders remain in the isolated demo. Optional `HOMESPHERE_SCREENSHOTS` saves desktop/mobile captures; `HOMESPHERE_CHROMIUM` selects an existing browser binary.

## Interview walkthrough and limits

1. Create Projects → Design and upload a text file there.
2. Return to My files and search for it across folders; open Recent uploads.
3. Create a one-hour link, download without a session, revoke it and show the 404.
4. Move the file to Recycle bin, restore it to Design, then demonstrate confirmed permanent deletion with a disposable file.
5. Explain virtual folders, session/ownership checks, token hashing, Alembic preservation and the storage recovery journal.

Intentionally omitted: folder move/rename/delete, file moving between existing folders, automatic bin retention, folder sharing, upload resumption and large-library server pagination in the UI. The UI loads metadata pages for this compact demo. Share revocation prevents new downloads; an already-open download may finish. Single-host `flock` is not a distributed lock. There is no public-share abuse throttling; this loopback demo is not an internet file-hosting service. Existing Three.js build-size and TestClient deprecation warnings remain.
