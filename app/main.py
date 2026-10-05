"""Papelada's HTTP API and static frontend.

Run with `uvicorn app.main:create_app --factory`. Configuration comes from the
environment: DATA_DIR (default /data), ENCRYPTION_KEY or ENCRYPTION_KEY_FILE, and
USERNAME with PASSWORD or PASSWORD_FILE to turn on the login (see auth.py)."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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


def get_library(request: Request) -> Library:
    return request.app.state.library


def _content_disposition(kind: str, filename: str) -> str:
    fallback = filename.encode("ascii", "replace").decode().replace('"', "'")
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


def _normalize_mime(mime: Optional[str]) -> str:
    mime = (mime or "").split(";")[0].strip().lower()
    return {"image/jpg": "image/jpeg", "": "application/octet-stream"}.get(mime, mime)


@router.get("/health")
def health() -> dict:
    return {"ok": True}


# --- login -------------------------------------------------------------------


class Credentials(BaseModel):
    username: str
    password: str


def _auth(request: Request) -> Optional[Auth]:
    return request.app.state.auth


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


@router.get("/session")
def get_session(request: Request) -> dict:
    auth = _auth(request)
    if auth is None:
        return {"login_required": False, "authenticated": True}
    return {"login_required": True, "authenticated": auth.valid_session(request.cookies.get(COOKIE_NAME))}


@router.post("/login")
def login(body: Credentials, request: Request) -> JSONResponse:
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


@router.post("/logout")
def logout(request: Request) -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="strict", secure=_is_https(request), path=None)
    return response


# --- settings ----------------------------------------------------------------


class SettingsUpdate(BaseModel):
    encrypted: bool


@router.get("/settings")
def get_settings(lib: Library = Depends(get_library)) -> dict:
    return lib.settings()


@router.put("/settings")
def update_settings(body: SettingsUpdate, lib: Library = Depends(get_library)) -> dict:
    converted = lib.set_encrypted(body.encrypted)
    return {**lib.settings(), "converted": converted}


@router.post("/scan")
def scan(lib: Library = Depends(get_library)) -> dict:
    return lib.scan()


# --- sections ----------------------------------------------------------------


class SectionBody(BaseModel):
    name: str
    icon: str = "folder"


class SectionOrder(BaseModel):
    ids: List[str]


@router.get("/sections")
def list_sections(lib: Library = Depends(get_library)) -> list:
    return lib.list_sections()


@router.post("/sections")
def create_section(body: SectionBody, lib: Library = Depends(get_library)) -> dict:
    return lib.create_section(body.name, body.icon)


@router.post("/sections/reorder")
def reorder_sections(body: SectionOrder, lib: Library = Depends(get_library)) -> list:
    return lib.reorder_sections(body.ids)


@router.put("/sections/{section_id}")
def update_section(section_id: str, body: SectionBody, lib: Library = Depends(get_library)) -> dict:
    return lib.update_section(section_id, body.name, body.icon)


@router.delete("/sections/{section_id}")
def delete_section(section_id: str, lib: Library = Depends(get_library)) -> dict:
    lib.delete_section(section_id)
    return {"ok": True}


# --- tags --------------------------------------------------------------------


class TagBody(BaseModel):
    name: str


@router.get("/tags")
def list_tags(lib: Library = Depends(get_library)) -> list:
    return lib.list_tags()


@router.post("/tags")
def create_tag(body: TagBody, lib: Library = Depends(get_library)) -> dict:
    return lib.create_tag(body.name)


@router.put("/tags/{tag_id}")
def rename_tag(tag_id: str, body: TagBody, lib: Library = Depends(get_library)) -> dict:
    return lib.rename_tag(tag_id, body.name)


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: str, lib: Library = Depends(get_library)) -> dict:
    lib.delete_tag(tag_id)
    return {"ok": True}


# --- documents -----------------------------------------------------------------


class DocumentUpdate(BaseModel):
    title: str
    date: str
    section: str
    tags: List[str] = []


class DownloadRequest(BaseModel):
    ids: List[str]


@router.get("/documents")
def list_documents(
    section: Optional[str] = None, tag: Optional[str] = None, lib: Library = Depends(get_library)
) -> list:
    return lib.list_documents(section, tag)


@router.post("/documents")
def create_document(
    section: str = Form(...),
    title: str = Form(...),
    date: str = Form(...),
    tags: List[str] = Form([]),
    files: List[UploadFile] = File(...),
    lib: Library = Depends(get_library),
) -> dict:
    pages = [(file.filename or "", _normalize_mime(file.content_type), file.file.read()) for file in files]
    uploaded_at = datetime.now(timezone.utc).isoformat()
    return lib.create_document(section, title, date, tags, pages, uploaded_at)


@router.post("/documents/download")
def download_documents(body: DownloadRequest, lib: Library = Depends(get_library)) -> Response:
    return Response(
        content=lib.export_zip(body.ids),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition("attachment", "papelada.zip")},
    )


@router.put("/documents/{doc_id}")
def update_document(doc_id: str, body: DocumentUpdate, lib: Library = Depends(get_library)) -> dict:
    return lib.update_document(doc_id, body.title, body.date, body.section, body.tags)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, lib: Library = Depends(get_library)) -> dict:
    lib.delete_document(doc_id)
    return {"ok": True}


@router.get("/documents/{doc_id}/pages/{page_id}/content")
def page_content(doc_id: str, page_id: str, download: bool = False, lib: Library = Depends(get_library)) -> Response:
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


@router.post("/documents/{doc_id}/pages/{page_id}/crop")
def crop_page(doc_id: str, page_id: str, file: UploadFile = File(...), lib: Library = Depends(get_library)) -> dict:
    return lib.crop_page(doc_id, page_id, file.file.read())


@router.post("/documents/{doc_id}/pages/{page_id}/restore")
def restore_page(doc_id: str, page_id: str, lib: Library = Depends(get_library)) -> dict:
    return lib.restore_page(doc_id, page_id)


# --- app ---------------------------------------------------------------------


def create_app(library: Optional[Library] = None, credentials: Optional[Tuple[str, str]] = None) -> FastAPI:
    """`library` and `credentials` are for tests; by default they come from the environment."""
    if credentials is None:
        credentials = load_credentials_from_env()
    if library is None:
        library = Library(Path(os.environ.get("DATA_DIR", "/data")), load_key_from_env())

    app = FastAPI(title="Papelada", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
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
