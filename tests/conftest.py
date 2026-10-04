from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.storage import META_DIR_NAME, Library

JPEG = b"\xff\xd8\xff\xe0 not really a jpeg"
PNG = b"\x89PNG not really a png"
PDF = b"%PDF-1.4 not really a pdf"


@pytest.fixture
def key() -> bytes:
    return Fernet.generate_key()


@pytest.fixture
def lib(tmp_path: Path, key: bytes) -> Library:
    return Library(tmp_path, key)


def tree(root: Path) -> list:
    """Every file in the volume outside the app's own folder, as relative paths."""
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.relative_to(root).parts[0] != META_DIR_NAME
    )


def add_doc(lib: Library, section: dict, title: str, pages=None, tags=(), date="2026-01-02") -> dict:
    pages = pages or [("scan.jpg", "image/jpeg", JPEG)]
    return lib.create_document(section["id"], title, date, list(tags), pages, "2026-01-02T10:00:00+00:00")
