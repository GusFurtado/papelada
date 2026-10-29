"""Papelada's HTTP API and static frontend.

Run with `uvicorn app.main:create_app --factory`. Configuration comes from the
environment: DATA_DIR (default /data), ENCRYPTION_KEY or ENCRYPTION_KEY_FILE, and
USERNAME with PASSWORD or PASSWORD_FILE to turn on the login (see auth.py)."""

import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, File, Form, Path as PathParam, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import COOKIE_NAME, SESSION_SECONDS, Auth, load_credentials_from_env
from .storage import Library, LibraryError, load_key_from_env

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Served inline (previewed in the browser). Anything else is only ever sent as
# a download, so an uploaded HTML/SVG file can't run scripts in the app's origin.
INLINE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif", "application/pdf"}

router = APIRouter(prefix="/api")

# The only API routes reachable without a session when the login is on: the
# health check (Docker's), and what the login screen itself needs.
PUBLIC_API_PATHS = {"/api/health", "/api/session", "/api/login", "/api/logout"}


DESCRIPTION = """
The API behind Papelada's web app: everything the app does goes through it.

- **Documents** belong to one **section** and carry any number of **tags**. A
  document is one or more **pages** (any file type; images and PDFs preview inline).
- **Errors** are `{"detail": "<code>", ...}` with a 4xx status, where `<code>` is a
  stable slug (`section_not_found`, `too_long`...), plus any extra detail for it.
- **Login**, when `USERNAME` and `PASSWORD` are set: `POST /api/login` sets a session
  cookie, and every other route here answers `401 login_required` without it.
"""

TAGS = [
    {"name": "System", "description": "Health check, for Docker and monitoring."},
    {"name": "Login", "description": "Optional single-user login with a session cookie. Without "
     "`USERNAME`/`PASSWORD` set, the app is open and these routes always succeed."},
    {"name": "Settings", "description": "Encryption, upload processing, and adopting files put in the volume by hand."},
    {"name": "Sections", "description": "Where documents live: each is a folder in the volume (in plain mode) with an icon."},
    {"name": "Tags", "description": "A managed list of labels that span sections."},
    {"name": "Documents", "description": "Upload, list, edit, delete and download documents."},
    {"name": "Pages", "description": "One file of a document: its content, thumbnail, and edits "
     "(rotate, crop, filter, reduce, convert), which can always be undone."},
]

NOT_FOUND = {404: {"description": "`document_not_found`, `page_not_found` or `file_missing`."}}
DocId = Annotated[str, PathParam(description="The document's id.")]
PageId = Annotated[str, PathParam(description="The page's id, from the document's `pages`.")]
SectionId = Annotated[str, PathParam(description="The section's id.")]
TagId = Annotated[str, PathParam(description="The tag's id.")]


def get_library(request: Request) -> Library:
    return request.app.state.library


def _content_disposition(kind: str, filename: str) -> str:
    fallback = filename.encode("ascii", "replace").decode().replace('"', "'")
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


def _normalize_mime(mime: Optional[str], filename: str = "") -> str:
    """The upload's type, from the file name when the browser didn't know it."""
    mime = (mime or "").split(";")[0].strip().lower()
    if mime in ("", "application/octet-stream"):
        mime = mimetypes.guess_type(filename)[0] or ""
    return {"image/jpg": "image/jpeg", "": "application/octet-stream"}.get(mime, mime)


@router.get("/health", tags=["System"], summary="Health check")
def health() -> dict:
    """Always `{"ok": true}` while the app is up. Never needs a login."""
    return {"ok": True}


# --- login -------------------------------------------------------------------


class Credentials(BaseModel):
    username: str = Field(description="`USERNAME` from the app's environment.")
    password: str = Field(description="`PASSWORD` (or the contents of `PASSWORD_FILE`).")


def _auth(request: Request) -> Optional[Auth]:
    return request.app.state.auth


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


@router.get("/session", tags=["Login"], summary="Session status")
def get_session(request: Request) -> dict:
    """`login_required`: whether the app has a login at all. `authenticated`: whether
    this request's cookie is a valid session (always true without a login)."""
    auth = _auth(request)
    if auth is None:
        return {"login_required": False, "authenticated": True}
    return {"login_required": True, "authenticated": auth.valid_session(request.cookies.get(COOKIE_NAME))}


@router.post(
    "/login",
    tags=["Login"],
    summary="Log in",
    responses={
        401: {"description": "`invalid_credentials`."},
        429: {"description": "`too_many_attempts`: wait `retry_after` seconds (also in `Retry-After`)."},
    },
)
def login(body: Credentials, request: Request) -> JSONResponse:
    """Sets the session cookie (`HttpOnly`, `SameSite=Strict`), valid for 14 days or
    until the app restarts. Failed attempts are throttled per client address."""
    auth = _auth(request)
    if auth is None:
        return JSONResponse({"ok": True})
    client = _client(request)
    wait = auth.throttle.retry_after(client)
    if wait:
        return JSONResponse(
            status_code=429, content={"detail": "too_many_attempts", "retry_after": wait}, headers={"Retry-After": str(wait)}
        )
    if not auth.check(body.username, body.password):
        auth.throttle.fail(client)
        return JSONResponse(status_code=401, content={"detail": "invalid_credentials"})
    auth.throttle.succeed(client)
    response = JSONResponse({"ok": True})
    # No Path: the cookie then covers /api (under any proxy prefix) and nothing else.
    # Strict also keeps other sites from making authenticated requests.
    response.set_cookie(
        COOKIE_NAME, auth.new_session(), max_age=SESSION_SECONDS, httponly=True, samesite="strict",
        secure=_is_https(request), path=None,
    )
    return response


@router.post("/logout", tags=["Login"], summary="Log out")
def logout(request: Request) -> JSONResponse:
    """Deletes the session cookie."""
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="strict", secure=_is_https(request), path=None)
    return response


# --- settings ----------------------------------------------------------------


class SettingsUpdate(BaseModel):
    """Only the fields sent are changed."""
    encrypted: Optional[bool] = Field(
        None, description="Encrypt (or decrypt) every stored file. Needs `ENCRYPTION_KEY` to turn on."
    )
    strip_metadata: Optional[bool] = Field(
        None, description="Remove EXIF and other metadata from uploaded photos (default on)."
    )
    reduce_uploads: Optional[bool] = Field(
        None, description="Scale uploaded photos down to 2000 px on the longest side (default off)."
    )


@router.get("/settings", tags=["Settings"], summary="Get settings")
def get_settings(lib: Library = Depends(get_library)) -> dict:
    """The current settings, plus `encryption_available`: whether an encryption key
    is configured (without one, `encrypted` can't be turned on)."""
    return lib.settings()


@router.put(
    "/settings",
    tags=["Settings"],
    summary="Change settings",
    responses={
        400: {"description": "`encryption_unavailable`: no encryption key is configured."},
        409: {"description": "`file_in_the_way`: decrypting would overwrite a file the app didn't write (`path`)."},
    },
)
def update_settings(body: SettingsUpdate, lib: Library = Depends(get_library)) -> dict:
    """Returns the new settings. Changing `encrypted` converts every stored file
    right away and also returns `converted`, how many files that touched; sending
    the same value again finishes an interrupted switch."""
    lib.update_upload_settings(body.strip_metadata, body.reduce_uploads)
    if body.encrypted is None:
        return lib.settings()
    converted = lib.set_encrypted(body.encrypted)
    return {**lib.settings(), "converted": converted}


@router.post(
    "/scan",
    tags=["Settings"],
    summary="Adopt files from the volume",
    responses={409: {"description": "`scan_needs_plain`: an encrypted library has no folders to scan."}},
)
def scan(lib: Library = Depends(get_library)) -> dict:
    """Turns files put in the volume by hand into documents: a file in a section's
    folder joins that section, and a new top-level folder becomes a section. Files
    keep their names. Returns how many `sections` and `documents` were added."""
    return lib.scan()


# --- sections ----------------------------------------------------------------


class SectionBody(BaseModel):
    name: str = Field(description="Shown in the app and used as the folder's name in the volume.")
    icon: str = Field("folder", description="A Lucide icon name from the app's icon picker.")


class SectionOrder(BaseModel):
    ids: List[str] = Field(description="Every section's id, in the new order.")


@router.get("/sections", tags=["Sections"], summary="List sections")
def list_sections(lib: Library = Depends(get_library)) -> list:
    """In the user's order, each with `documents`, its document count."""
    return lib.list_sections()


@router.post(
    "/sections",
    tags=["Sections"],
    summary="Create a section",
    responses={400: {"description": "`name_required`, `too_long` or `invalid_icon`."}, 409: {"description": "`section_exists`."}},
)
def create_section(body: SectionBody, lib: Library = Depends(get_library)) -> dict:
    """Creates the section (and its folder, in plain mode) at the end of the list."""
    return lib.create_section(body.name, body.icon)


@router.post(
    "/sections/reorder",
    tags=["Sections"],
    summary="Reorder sections",
    responses={400: {"description": "`invalid_order`: `ids` isn't exactly the existing sections."}},
)
def reorder_sections(body: SectionOrder, lib: Library = Depends(get_library)) -> list:
    """Returns the sections in their new order."""
    return lib.reorder_sections(body.ids)


@router.put(
    "/sections/{section_id}",
    tags=["Sections"],
    summary="Rename a section or change its icon",
    responses={
        400: {"description": "`name_required`, `too_long` or `invalid_icon`."},
        404: {"description": "`section_not_found`."},
        409: {"description": "`section_exists`."},
    },
)
def update_section(section_id: SectionId, body: SectionBody, lib: Library = Depends(get_library)) -> dict:
    """Renaming a section renames its folder, so its files move along."""
    return lib.update_section(section_id, body.name, body.icon)


@router.delete(
    "/sections/{section_id}",
    tags=["Sections"],
    summary="Delete a section",
    responses={404: {"description": "`section_not_found`."}, 409: {"description": "`section_not_empty`."}},
)
def delete_section(section_id: SectionId, lib: Library = Depends(get_library)) -> dict:
    """Only an empty section can be deleted. Its folder goes too, unless it still
    holds files the app doesn't know about."""
    lib.delete_section(section_id)
    return {"ok": True}


# --- tags --------------------------------------------------------------------


class TagBody(BaseModel):
    name: str = Field(description="The tag's name.")


@router.get("/tags", tags=["Tags"], summary="List tags")
def list_tags(lib: Library = Depends(get_library)) -> list:
    """Alphabetical, each with `documents`, how many documents have it."""
    return lib.list_tags()


@router.post(
    "/tags",
    tags=["Tags"],
    summary="Create a tag",
    responses={400: {"description": "`name_required` or `too_long`."}, 409: {"description": "`tag_exists`."}},
)
def create_tag(body: TagBody, lib: Library = Depends(get_library)) -> dict:
    return lib.create_tag(body.name)


@router.put(
    "/tags/{tag_id}",
    tags=["Tags"],
    summary="Rename a tag",
    responses={
        400: {"description": "`name_required` or `too_long`."},
        404: {"description": "`tag_not_found`."},
        409: {"description": "`tag_exists`."},
    },
)
def rename_tag(tag_id: TagId, body: TagBody, lib: Library = Depends(get_library)) -> dict:
    return lib.rename_tag(tag_id, body.name)


@router.delete(
    "/tags/{tag_id}", tags=["Tags"], summary="Delete a tag", responses={404: {"description": "`tag_not_found`."}}
)
def delete_tag(tag_id: TagId, lib: Library = Depends(get_library)) -> dict:
    """Takes the tag off every document that had it; the documents stay."""
    lib.delete_tag(tag_id)
    return {"ok": True}


# --- documents -----------------------------------------------------------------


class DocumentUpdate(BaseModel):
    title: str = Field(description="Also the file name of its pages in the volume.")
    date: str = Field(description="The document's own date, `YYYY-MM-DD`.", examples=["2026-10-25"])
    expires: Optional[str] = Field(
        None, description="When the document expires, `YYYY-MM-DD`, or none. Leaving it out clears it."
    )
    section: str = Field(description="The section's id. Changing it moves the files.")
    tags: List[str] = Field([], description="Tag ids. This replaces the document's tags.")


class DownloadRequest(BaseModel):
    ids: List[str] = Field(description="The documents' ids.")


class PdfDownloadRequest(DownloadRequest):
    merge: bool = Field(False, description="All the documents in one PDF, in the order of `ids`, "
                        "instead of a zip with one PDF per document.")


class CropBox(BaseModel):
    """Fractions (0 to 1) of the image after rotation."""
    x: float = Field(description="Left edge.")
    y: float = Field(description="Top edge.")
    w: float = Field(description="Width.")
    h: float = Field(description="Height.")


class PageEdits(BaseModel):
    """See app/images.py: rotation and crop, filter, size and format."""
    rotate: int = Field(0, description="Clockwise degrees: 0, 90, 180 or 270. Applied before `crop`.")
    crop: Optional[CropBox] = None
    filter: Optional[str] = Field(None, description="`scan` (a photo of paper: grayscale, contrast stretched), or none.")
    reduce: bool = Field(False, description="Scale down to 2000 px on the longest side.")
    format: Optional[str] = Field(None, description="Convert to `png` or `pdf`, or keep the upload's format.")


@router.get("/documents", tags=["Documents"], summary="List documents")
def list_documents(
    section: Annotated[Optional[str], Query(description="Only this section's documents (its id).")] = None,
    tag: Annotated[Optional[str], Query(description="Only documents with this tag (its id).")] = None,
    q: Annotated[Optional[str], Query(description="Only documents whose title has every word of this, "
                                      "ignoring case and accents.")] = None,
    lib: Library = Depends(get_library),
) -> list:
    """Newest first, by `date` and then upload time. `expires` is the document's
    expiry date, or null. Each page lists its `path` in the volume, its `mime`,
    `size` and `rev` (bumped on every edit, so it can key caches), whether it was
    `edited`, and whether it's `editable` (an image the editor can open)."""
    return lib.list_documents(section, tag, q)


@router.post(
    "/documents",
    tags=["Documents"],
    summary="Upload a document",
    responses={
        400: {"description": "`title_required`, `too_long`, `invalid_date`, `invalid_expiry`, `unknown_tag`, "
              "`pages_required` or `empty_file`."},
        404: {"description": "`section_not_found`."},
    },
)
def create_document(
    section: str = Form(..., description="The section's id."),
    title: str = Form(..., description="Also the pages' file name in the volume."),
    date: str = Form(..., description="The document's own date, `YYYY-MM-DD`."),
    expires: Optional[str] = Form(None, description="When the document expires, `YYYY-MM-DD`, if it does."),
    tags: List[str] = Form([], description="Tag ids."),
    files: List[UploadFile] = File(..., description="The pages, in order. Any file type."),
    lib: Library = Depends(get_library),
) -> dict:
    """A multipart upload, one file per page. Photos are turned upright and, per
    the settings, lose their metadata and are scaled down. Returns the document."""
    pages = [
        (file.filename or "", _normalize_mime(file.content_type, file.filename or ""), file.file.read()) for file in files
    ]
    uploaded_at = datetime.now(timezone.utc).isoformat()
    return lib.create_document(section, title, date, tags, pages, uploaded_at, expires)


@router.post(
    "/documents/download",
    tags=["Documents"],
    summary="Download documents as a zip",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}, **NOT_FOUND},
)
def download_documents(body: DownloadRequest, lib: Library = Depends(get_library)) -> Response:
    """`papelada.zip`, laid out like the volume (`Section/Title.ext`), whether or not
    the library is encrypted."""
    return Response(
        content=lib.export_zip(body.ids),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition("attachment", "papelada.zip")},
    )


@router.post(
    "/documents/pdf",
    tags=["Documents"],
    summary="Download documents as PDFs",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {}, "application/pdf": {}}},
        400: {"description": "`not_exportable`: a page of the document `title` is neither an image the editor "
              "can open nor a valid PDF."},
        **NOT_FOUND,
    },
)
def download_pdfs(body: PdfDownloadRequest, lib: Library = Depends(get_library)) -> Response:
    """Each document as one PDF, like `GET /documents/{doc_id}/pdf`: `papelada.zip`
    with one PDF per document (`Section/Title.pdf`), or with `merge`, one PDF of
    them all (`papelada.pdf`, or the document's name when there's only one)."""
    content, filename = lib.export_pdfs(body.ids, body.merge)
    return Response(
        content=content,
        media_type="application/pdf" if body.merge else "application/zip",
        headers={"Content-Disposition": _content_disposition("attachment", filename), "Cache-Control": "no-cache"},
    )


@router.put(
    "/documents/{doc_id}",
    tags=["Documents"],
    summary="Change a document's details",
    responses={
        400: {"description": "`title_required`, `too_long`, `invalid_date`, `invalid_expiry` or `unknown_tag`."},
        404: {"description": "`document_not_found` or `section_not_found`."},
    },
)
def update_document(doc_id: DocId, body: DocumentUpdate, lib: Library = Depends(get_library)) -> dict:
    """A new title or section renames or moves the document's files to match.
    Returns the document."""
    return lib.update_document(doc_id, body.title, body.date, body.section, body.tags, body.expires)


@router.delete(
    "/documents/{doc_id}",
    tags=["Documents"],
    summary="Delete a document",
    responses={404: {"description": "`document_not_found`."}},
)
def delete_document(doc_id: DocId, lib: Library = Depends(get_library)) -> dict:
    """Deletes its files too, including backups of edited pages."""
    lib.delete_document(doc_id)
    return {"ok": True}


@router.get(
    "/documents/{doc_id}/pages/{page_id}/content",
    tags=["Pages"],
    summary="Page file",
    response_class=Response,
    responses={200: {"description": "The file as stored.", "content": {"*/*": {}}}, **NOT_FOUND},
)
def page_content(
    doc_id: DocId,
    page_id: PageId,
    download: Annotated[bool, Query(description="Send as an attachment even if it could preview inline.")] = False,
    lib: Library = Depends(get_library),
) -> Response:
    """Images and PDFs are served inline with their own type; anything else is
    always an `application/octet-stream` attachment, so an uploaded HTML or SVG
    file can't run scripts in the app."""
    page, content, filename = lib.read_page(doc_id, page_id)
    inline = page["mime"] in INLINE_MIME_TYPES
    headers = {
        "Content-Disposition": _content_disposition("inline" if inline and not download else "attachment", filename),
        "X-Content-Type-Options": "nosniff",
        # The frontend's URLs carry the page's revision, so a cached copy never goes stale.
        "Cache-Control": "no-cache" if download else "private, max-age=31536000, immutable",
    }
    media_type = page["mime"] if inline else "application/octet-stream"
    return Response(content=content, media_type=media_type, headers=headers)


@router.get(
    "/documents/{doc_id}/pdf",
    tags=["Documents"],
    summary="Download a document as one PDF",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}},
        400: {"description": "`not_exportable`: some page is neither an image the editor can open nor a valid PDF."},
        **NOT_FOUND,
    },
)
def document_pdf(doc_id: DocId, lib: Library = Depends(get_library)) -> Response:
    """Every page in order joined into one PDF: PDFs as they are, images one page each."""
    content, filename = lib.document_pdf(doc_id)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition("attachment", filename), "Cache-Control": "no-cache"},
    )


# Derived images: the URLs carry the page's revision too, so they can be cached for good.
_IMMUTABLE = {"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"}


@router.get(
    "/documents/{doc_id}/pages/{page_id}/thumbnail",
    tags=["Pages"],
    summary="Page thumbnail",
    response_class=Response,
    responses={
        200: {"content": {"image/webp": {}}},
        404: {"description": "`no_thumbnail` (not an image or PDF), `document_not_found`, `page_not_found` or `file_missing`."},
    },
)
def page_thumbnail(doc_id: DocId, page_id: PageId, lib: Library = Depends(get_library)) -> Response:
    """A small WebP of the page as it is now, cached per revision."""
    return Response(content=lib.thumbnail(doc_id, page_id), media_type="image/webp", headers=_IMMUTABLE)


@router.get(
    "/documents/{doc_id}/pages/{page_id}/preview",
    tags=["Pages"],
    summary="Page as uploaded, for the editor",
    response_class=Response,
    responses={
        200: {"content": {"image/*": {}}},
        400: {"description": "`not_an_image` or `unreadable_image`."},
        **NOT_FOUND,
    },
)
def page_preview(doc_id: DocId, page_id: PageId, lib: Library = Depends(get_library)) -> Response:
    """The page as uploaded (before any edits), upright and at most 2048 px: what
    the editor draws the crop box on."""
    content, mime = lib.edit_preview(doc_id, page_id)
    return Response(content=content, media_type=mime, headers=_IMMUTABLE)


@router.put(
    "/documents/{doc_id}/pages/{page_id}/edits",
    tags=["Pages"],
    summary="Edit a page",
    responses={
        400: {"description": "`not_an_image`, `invalid_edits` or `unreadable_image`."},
        **NOT_FOUND,
    },
)
def edit_page(doc_id: DocId, page_id: PageId, body: PageEdits, lib: Library = Depends(get_library)) -> dict:
    """Applies the edits to the page as uploaded, never to an earlier edit, so
    quality doesn't drop. The first edit keeps a backup of the upload; sending no
    edits at all restores it. Returns the page."""
    return lib.edit_page(doc_id, page_id, body.model_dump())


@router.post(
    "/documents/{doc_id}/pages/{page_id}/restore",
    tags=["Pages"],
    summary="Undo a page's edits",
    responses={404: {"description": "`no_original` (the page wasn't edited), `document_not_found` or `page_not_found`."}},
)
def restore_page(doc_id: DocId, page_id: PageId, lib: Library = Depends(get_library)) -> dict:
    """Puts back the page as uploaded and drops the backup. Returns the page."""
    return lib.restore_page(doc_id, page_id)


# --- app ---------------------------------------------------------------------


def create_app(library: Optional[Library] = None, credentials: Optional[Tuple[str, str]] = None) -> FastAPI:
    """`library` and `credentials` are for tests; by default they come from the environment."""
    if credentials is None:
        credentials = load_credentials_from_env()
    if library is None:
        library = Library(Path(os.environ.get("DATA_DIR", "/data")), load_key_from_env())

    app = FastAPI(
        title="Papelada",
        description=DESCRIPTION,
        openapi_tags=TAGS,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.library = library
    app.state.auth = Auth(*credentials) if credentials else None

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        auth = app.state.auth
        path = request.url.path
        if (
            auth is not None
            and (path == "/api" or path.startswith("/api/"))
            and path not in PUBLIC_API_PATHS
            and not auth.valid_session(request.cookies.get(COOKIE_NAME))
        ):
            return JSONResponse(status_code=401, content={"detail": "login_required"})
        return await call_next(request)

    @app.exception_handler(LibraryError)
    def library_error(request: Request, exc: LibraryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.code, **exc.info})

    app.include_router(router)
    # Mounted last so it doesn't shadow the API. The frontend only uses relative
    # URLs, so the app also works behind a reverse proxy under a path prefix.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app
