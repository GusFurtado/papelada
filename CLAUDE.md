# Papelada: working notes

Decisions and context that don't belong in the README. Read `app/storage.py`'s
module docstring first: it is the reference for the volume layout.

## Origin (2026-10-04)

A public, generalized successor to the author's private `carteira-docs` app
(a household document wallet with fixed owners and fixed categories, in pt-BR).
What changed on purpose:

- **Nothing hard-coded.** Fixed owners became user-created *sections* (each with a
  Lucide icon picked from `SECTION_ICONS` in `frontend/icons.js`), and fixed
  categories became user-created *tags* that span sections. Tags are a managed list
  (create, rename, delete), not freeform text per document: in carteira-docs, a
  freeform category ended up with one chip per document, which made the filter
  useless.
- **A browsable volume.** carteira-docs stored `files/{page_id}.enc`. Here, in plain
  mode, a page is `<section folder>/<title>.<ext>`, so the volume can be used
  without the app. The user mounts it in docker compose (`DOCUMENTS_PATH`).
- **The key never lives in the volume.** carteira-docs generated `secret.key` next to
  the data, which made encryption useless against anyone holding a backup. Here it
  comes from `ENCRYPTION_KEY` / `ENCRYPTION_KEY_FILE`; without it, the encryption
  toggle is hidden.
- **Encrypted means opaque.** Encrypting moves pages to `.papelada/vault/<page id>.enc`
  and encrypts the index too, since a plaintext index or readable file names would
  leak titles. The browsable tree only exists in plain mode.
- Any file type is accepted, not just images and PDFs. Only images and PDFs are
  served inline; everything else (HTML, SVG...) is sent as an
  `application/octet-stream` attachment with `nosniff`, so an upload can't run
  script in the app's origin.
- English + pt-BR (`frontend/i18n.js`), picked from `navigator.languages`.
- Fonts and Cropper.js are vendored (`frontend/vendor/`), because a self-hosted app
  shouldn't call Google Fonts or a CDN.

## Storage invariants

- `index.json` is the source of truth. A document stores its `stem` (the file name
  without the page suffix); every page's path is *computed* from the section's
  `folder`, the doc's `stem`, the page's position and its fixed `ext`. Never store
  paths per page; recompute them.
- A page's `ext` is fixed at upload, and crops keep the mime, so the name never drifts.
- Name allocation (`_allocate_folder`, `_allocate_stem`) compares case-folded, so
  names don't clash on case-insensitive systems browsing over SMB. It also checks
  existing files on disk (plain mode) so it never overwrites a file the app didn't
  write. Stems are unique per section, and so is every resulting file name.
- `safe_name` keeps names valid on Windows too: no separators, no `*?"<>|`, no
  leading dots (hidden files), no trailing dots or spaces, no `CON`/`NUL`...
- Converting between modes writes the target before deleting the source. Reads prefer
  the vault copy when both exist: only the app writes there, while a plain path
  could hold someone else's file. Decrypting first checks every target
  (`_check_decryptable`) and refuses (409 `file_in_the_way`) rather than overwrite a
  foreign file. On startup, `_converge` finishes an interrupted switch.
- Single process only (one uvicorn worker): the index is kept in memory and writes
  are serialized by `Library.lock`. Don't add workers.
- The container never runs as root (`USER 1000` in the Dockerfile, `PUID`/`PGID` in
  compose) so files in the volume belong to the person browsing them. carteira-docs
  left root-owned files in its bind mount that needed `sudo rm`.

## Login, scan and themes (v0.2.0)

- **Login** (`app/auth.py`) is optional and single-user: `USERNAME` + `PASSWORD`
  (`PASSWORD_FILE`), both or neither (one alone aborts startup). A session is a signed
  cookie (`expiry.hmac`) under a random per-process key, so nothing about the login
  touches the volume, and a restart (how credentials are changed) ends all sessions.
  The key is deliberately not derived from the password: a stolen cookie would allow
  offline guessing. One middleware guards everything under `/api` except
  `PUBLIC_API_PATHS`, which also covers `/api/docs`; new routes are protected by default.
  The cookie has no `Path` on purpose: the browser then scopes it to `<prefix>/api`, which
  keeps it working behind a path-prefix proxy without leaking to sibling apps.
  `X-Forwarded-For` is not trusted for throttling (spoofable), so behind a proxy the
  limits are effectively global.
- **Scan** (`Library.scan`) adopts files as they are: a document's `stem` and `ext` come from
  the file name, so nothing is renamed and the computed-path invariant holds. When two
  files share a stem (`a.jpg`, `a.png`), the second takes its whole name as the stem with an
  empty `ext`. Plain mode only.
- **Themes** are `:root[data-theme=...]` blocks in `style.css`; `frontend/theme.js` (loaded
  in `<head>`, no flash) holds the list and the swatch colors. Overlays on photos use fixed
  white text, not `--ink`, so they work on light themes.

## Frontend conventions

- ES5-style vanilla JS, no build step. Only relative URLs (`fetch('api/...')`), so
  the app works under a path prefix behind a reverse proxy.
- API errors come back as `{"detail": "<code>", ...info}`; the frontend maps
  `errors.<code>` in `i18n.js` and falls back to `errors.generic`. When adding a new
  `LibraryError` code the user can hit, add both translations.
- `frontend/icons.js` is generated from `lucide-static` (`icon-nodes.json`). To add
  icons, regenerate it rather than hand-editing the SVG strings, and check the name
  exists in that Lucide version (several were renamed, e.g. `trash-2` → `trash`,
  `lock-open`, `square-check-big`).
- Photos are added one at a time (`capture="environment"` input) because
  `multiple` + `capture` is unreliable on phones; "Add files" is a separate
  `multiple` input.

## Releases

The Docker image is published only from GitHub releases whose tag is a version
(`v1.2.3` or `1.2.3`, optionally `-rc.1`...), never from pushes to `main`. This is
deliberate: `latest` is what the README tells people to run, so it must always be a
release. A full release gets `1.2.3`, `1.2` and `latest`. A release marked as a
pre-release gets only `1.2.3-rc.1`. Releases with any other tag publish nothing.
See `.github/workflows/docker.yml`.

## Testing

`pytest` covers storage (naming, collisions, renames, tags, crop, every encryption
path including interrupted switches and foreign files) and the API. For UI changes,
also drive it in a browser at phone width (390px): the main use is a phone camera.
