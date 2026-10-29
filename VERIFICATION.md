# HomeSphere verification — 26 October 2026

Status: implemented in `/home/dev/projects/homesphere` and running at **http://localhost:8080**. API, web and PostgreSQL are healthy; the migration service exits successfully. Existing architecture, charcoal dashboard, login, sphere and file previews are retained.

## Delivered in priority order

1. **Folders:** create nested virtual folders, browse children and breadcrumbs, upload into the selected folder. Existing files remain at My files.
2. **Recent uploads:** ten newest active files across all folders, excluding recycled files. Upload timestamps survive rename and restore.
3. **Recycle bin:** reversible deletion, restore to the original folder, and confirmed permanent deletion. Recycling preserves bytes and revokes all existing sharing links. Restore does not reactivate them.
4. **Public links:** anonymous attachment downloads, random 256-bit URL-safe secrets, hashed token storage, mandatory expiry, owner-only management and immediate revocation for subsequent requests.

Private resource access checks the authenticated owner. Writes retain exact-Origin protection. Folder names reuse the portable filename/path validator; virtual folder IDs never form filesystem paths. Permanent deletion retains the original durable recovery journal. A failed soft-delete transaction rolls back revocation and deletion together. Restore refuses missing payloads while retaining the metadata.

## Evidence

| Check | Result |
|---|---|
| Original backend suite before edits | **54 passed** |
| Original live API through Nginx | Upload, metadata, byte-exact download, rename and delete passed |
| Original live browser behavior | Upload, case-insensitive search, no-match state, exact download and delete passed |
| Expanded suite with temporary SQLite/storage | **72 passed**, 2 PostgreSQL-only migration checks skipped |
| Expanded suite against isolated PostgreSQL 17 | **72 passed** |
| Real PostgreSQL Alembic migration checks | **2 passed**: fresh install and populated upgrade |
| Browser feature flow against isolated built app | Passed login, nested folders, upload, breadcrumbs, global search, Recent, anonymous download/revoke, keyboard focus, recycle/restore/download/purge and logout |
| Responsive checks | Passed at 1440, 768, 375 and 812-pixel landscape widths; no page overflow; file actions remain at least 44×44 and unclipped in grid/list views |
| Reduced motion and browser errors | Reduced-motion flow passed; no uncaught page errors |
| Final frontend production build | Passed |
| Frontend lint | 0 errors; 2 existing warnings |
| Updated live web app | **28 feature checks passed**, including >1 MiB nested upload, search, share/revoke, trash/restore/purge and access controls |
| Current Alembic schema | Revision **c84e72a190fd**, no new upgrade operations detected |
| Data preservation after migration and smoke checks | Original file metadata and bytes, owner credentials and both legacy rows unchanged |
| Public-link request logging | Public bearer paths absent from the new API/web access logs |

The PostgreSQL upgrade test retains original file metadata, owner password hash and legacy data, and verifies that existing files become root-level files owned by the established owner. It also verifies that a populated pre-auth database with no owner is rejected before migration, and that a destructive downgrade is refused.

The original live baseline had **one file and payload, one owner, and two legacy homes rows**. Before/after inventories compare every original file metadata column, stored payload SHA-256, owner row and legacy row. These comparisons passed again after live feature testing. Temporary live test files, links, folders and sessions were removed; the isolated test containers and network were removed.

## Backups and recovery

Private pre-update source/settings, PostgreSQL dump, upload archive and preservation inventories remain at:

```text
/home/dev/projects/homesphere/.homesphere-backups/cloud-features-20261026-154222/
```

The timestamp is UTC. The directory is private; its settings and database backup are not included in the downloadable source. Previous API/web images also retain `pre-cloud-20261026-154222` tags. No personal data volume was removed or recreated.

Do not downgrade or delete volumes as a rollback shortcut. A rollback must stop writes and deliberately restore the matching source/image, database and uploads backup together. The ordinary start/stop commands and test instructions are in README.md.

## Deliberate limits and remaining warnings

- This remains a single-owner, loopback demo. Generated localhost sharing links work on this machine. Access from another device requires deliberate HTTPS, cookie and host/network configuration.
- Folder move/rename/delete, moving existing files between folders, folder sharing and automatic bin retention are outside this compact increment.
- The UI fetches metadata pages for a small personal library. There is no large-library UI pagination or distributed storage lock.
- Revoking a link prevents new downloads; an already-open download can finish. Public-share abuse throttling is not included.
- The existing Three.js chunk-size warning and TestClient deprecation warning remain. Lint retains the existing FilePreview fast-refresh warning and App data-loading effect warning; no new lint warnings remain.

The reusable browser test requires a separate Playwright installation and an isolated demo account. PostgreSQL test variables explicitly require a disposable `homesphere_test_*` database because those tests rebuild its schema. See README.md before running them.

## Implementation references

Token generation follows Python's [secrets documentation](https://docs.python.org/3.15/library/secrets.html). Migration preservation follows the application's existing Alembic history; the [Alembic cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html) discusses migration and data-preservation tradeoffs. The implementation and automated tests, rather than those references alone, establish the behavior reported above.
