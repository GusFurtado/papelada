"""Papelada's library: sections, tags and documents kept in one volume.

Layout of the volume (DATA_DIR, `/data` in the container):

    <Section>/<Document title>.<ext>            a single-page document
    <Section>/<Document title> - 2.<ext>        page 2 of a multi-page one
    .papelada/index.json                        sections, tags, document metadata
    .papelada/settings.json                     {"encrypted": bool}
    .papelada/originals/<page id>.<ext>         pre-crop backup of a page
    .papelada/vault/<page id>.enc               page content while encrypted

Unencrypted, every page is an ordinary file with a human-readable name inside
its section's folder, so the volume can be browsed and copied directly.
Encrypted, the pages move into the vault and the index is encrypted too, so
nothing readable is left in the volume; the key comes from the environment and
never lives in the volume. Switching converts every file, and an interrupted
switch is finished on the next start (or by switching to the same mode again).

The index is the source of truth: the app ignores files it didn't write, and
won't find its own files if they're renamed or moved by hand."""

import io
import itertools
import json
import logging
import mimetypes
import os
import re
import threading
import unicodedata
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

META_DIR_NAME = ".papelada"
INDEX_FILE_NAME = "index.json"
SETTINGS_FILE_NAME = "settings.json"
VAULT_DIR_NAME = "vault"
ORIGINALS_DIR_NAME = "originals"
ENCRYPTED_SUFFIX = ".enc"
INDEX_VERSION = 1

MAX_SECTION_NAME = 60
MAX_TAG_NAME = 40
MAX_TITLE = 200
MAX_NAME_BYTES = 150  # leaves room for " (2) - 10.jpeg" under the usual 255-byte limit

MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/avif": ".avif",
    "application/pdf": ".pdf",
}

_SEPARATORS = re.compile(r"[/\\:]")
_FORBIDDEN = re.compile(r'[*?"<>|\x00-\x1f\x7f]')
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}
_ICON = re.compile(r"[a-z0-9-]{1,40}")
_EXTENSION = re.compile(r"\.[a-z0-9]{1,10}")

log = logging.getLogger("papelada")

Paths = Tuple[Path, Path]  # (encrypted path, plain path) of one stored file


class LibraryError(Exception):
    """An error the API turns into a 4xx response. `code` is a stable slug the
    frontend maps to a translated message; `info` is extra detail for it."""

    status = 400

    def __init__(self, code: str, **info):
        super().__init__(code)
        self.code = code
        self.info = info


class Invalid(LibraryError):
    status = 400


class NotFound(LibraryError):
    status = 404


class Conflict(LibraryError):
    status = 409


class EncryptionKeyError(RuntimeError):
    """The library can't be opened with the configured key (fatal at startup)."""


def load_key_from_env() -> Optional[bytes]:
    """ENCRYPTION_KEY, or the contents of the file at ENCRYPTION_KEY_FILE
    (Docker secrets). None when neither is set: encryption is unavailable."""
    key = os.environ.get("ENCRYPTION_KEY", "").strip()
    key_file = os.environ.get("ENCRYPTION_KEY_FILE", "").strip()
    if not key and key_file:
        key = Path(key_file).read_text().strip()
    if not key:
        return None
    try:
        Fernet(key)
    except ValueError:
        raise EncryptionKeyError(
            "ENCRYPTION_KEY must be 32 url-safe base64-encoded bytes. "
            "Generate one with: openssl rand -base64 32 | tr '+/' '-_'"
        )
    return key.encode()


def safe_name(text: str, fallback: str) -> str:
    """A file/folder name valid on Linux, macOS and Windows (e.g. over SMB) that
    stays as close as possible to `text`: separators become '-', other
    forbidden characters are dropped, and leading dots (hidden files, '..') and
    trailing dots/spaces (which Windows strips) are removed."""
    name = unicodedata.normalize("NFC", text)
    name = re.sub(r"\s+", " ", name)
    name = _SEPARATORS.sub("-", name)
    name = _FORBIDDEN.sub("", name)
    name = name.strip().lstrip(". ").rstrip(". ")
    name = name.encode("utf-8")[:MAX_NAME_BYTES].decode("utf-8", errors="ignore").rstrip(". ")
    if not name:
        name = fallback
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        name += "_"
    return name


def page_file_name(stem: str, index: int, count: int, ext: str) -> str:
    """`RG.jpg` for a single-page document, `RG - 1.jpg`, `RG - 2.jpg`, ... for
    a multi-page one (zero-padded from 10 pages on, so names sort naturally)."""
    if count == 1:
        return f"{stem}{ext}"
    return f"{stem} - {index + 1:0{len(str(count))}d}{ext}"


def extension_for(mime: str, filename: str) -> str:
    """Extension a page is stored with. Fixed at upload (a crop keeps the mime),
    so a page's file name can always be recomputed from its metadata."""
    if mime in MIME_EXTENSIONS:
        return MIME_EXTENSIONS[mime]
    suffix = Path(filename or "").suffix.lower()
    if _EXTENSION.fullmatch(suffix):
        return suffix
    return mimetypes.guess_extension(mime) or ".bin"


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _remove_dir_if_empty(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def _clean_label(value: str, max_length: int, code: str) -> str:
    value = unicodedata.normalize("NFC", re.sub(r"\s+", " ", value or "")).strip()
    if not value:
        raise Invalid(code)
    if len(value) > max_length:
        raise Invalid("too_long", max=max_length)
    return value


def _check_icon(icon: str) -> str:
    if not _ICON.fullmatch(icon or ""):
        raise Invalid("invalid_icon")
    return icon


def _check_date(value: str) -> str:
    try:
        datetime.strptime(value or "", "%Y-%m-%d")
    except ValueError:
        raise Invalid("invalid_date")
    return value


class Library:
    """All state lives in `self.index`, written through to the volume on every
    change. One process owns the volume; `self.lock` serializes requests."""

    def __init__(self, root: Path, key: Optional[bytes] = None):
        self.root = Path(root)
        self.meta_dir = self.root / META_DIR_NAME
        self.vault_dir = self.meta_dir / VAULT_DIR_NAME
        self.originals_dir = self.meta_dir / ORIGINALS_DIR_NAME
        self.settings_path = self.meta_dir / SETTINGS_FILE_NAME
        self.plain_index_path = self.meta_dir / INDEX_FILE_NAME
        self.encrypted_index_path = self.meta_dir / (INDEX_FILE_NAME + ENCRYPTED_SUFFIX)
        self.fernet = Fernet(key) if key else None
        self.lock = threading.RLock()

        try:
            self.vault_dir.mkdir(parents=True, exist_ok=True)
            self.originals_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            raise PermissionError(
                f"Can't write to {self.root}. The folder mounted there must be writable by the user "
                f"the container runs as (uid {os.getuid()}, gid {os.getgid()}); see PUID/PGID in the README."
            )
        settings =json.loads(self.settings_path.read_text()) if self.settings_path.exists() else {}
        self.encrypted = bool(settings.get("encrypted", False))
        if self.encrypted and self.fernet is None:
            raise EncryptionKeyError("This library is encrypted, but ENCRYPTION_KEY is not set.")

        self.index = self._load_index()
        self._save_index()
        try:
            converted = self._converge()
        except (LibraryError, OSError) as exc:
            # Not fatal: reads fall back to whichever form a file is in.
            log.warning("Could not bring every file to the %s form: %r",
                        "encrypted" if self.encrypted else "plain", exc)
        else:
            if converted:
                log.warning("Finished an interrupted encryption switch: converted %d files.", converted)

    # --- index -----------------------------------------------------------

    def _load_index(self) -> dict:
        """Reads whichever form of the index exists, preferring the current
        mode's (both can exist if a switch was interrupted)."""
        candidates = [self.plain_index_path, self.encrypted_index_path]
        if self.encrypted:
            candidates.reverse()
        for path in candidates:
            if not path.exists():
                continue
            data = path.read_bytes()
            if path == self.encrypted_index_path:
                if self.fernet is None:
                    raise EncryptionKeyError("The index is encrypted, but ENCRYPTION_KEY is not set.")
                try:
                    data = self.fernet.decrypt(data)
                except InvalidToken:
                    raise EncryptionKeyError("ENCRYPTION_KEY doesn't match the key this library was encrypted with.")
            return json.loads(data)
        return {"version": INDEX_VERSION, "sections": [], "tags": [], "documents": {}}

    def _save_index(self) -> None:
        data = json.dumps(self.index, indent=2, ensure_ascii=False).encode("utf-8")
        if self.encrypted:
            _atomic_write(self.encrypted_index_path, self.fernet.encrypt(data))
            self.plain_index_path.unlink(missing_ok=True)
        else:
            _atomic_write(self.plain_index_path, data)
            self.encrypted_index_path.unlink(missing_ok=True)

    def _section(self, section_id: str) -> dict:
        for section in self.index["sections"]:
            if section["id"] == section_id:
                return section
        raise NotFound("section_not_found")

    def _tag(self, tag_id: str) -> dict:
        for tag in self.index["tags"]:
            if tag["id"] == tag_id:
                return tag
        raise NotFound("tag_not_found")

    def _doc(self, doc_id: str) -> dict:
        doc = self.index["documents"].get(doc_id)
        if doc is None:
            raise NotFound("document_not_found")
        return doc

    def _page_index(self, doc: dict, page_id: str) -> int:
        for i, page in enumerate(doc["pages"]):
            if page["id"] == page_id:
                return i
        raise NotFound("page_not_found")

    def _check_tags(self, tag_ids: Iterable[str]) -> List[str]:
        known = {tag["id"] for tag in self.index["tags"]}
        result = []
        for tag_id in tag_ids:
            if tag_id not in known:
                raise Invalid("unknown_tag")
            if tag_id not in result:
                result.append(tag_id)
        return result

    @staticmethod
    def _check_unique(items: list, name: str, code: str, exclude: Optional[dict] = None) -> None:
        if any(item is not exclude and item["name"].casefold() == name.casefold() for item in items):
            raise Conflict(code)

    # --- file locations and the encrypted/plain forms ------------------------

    def _file_names(self, doc: dict) -> List[str]:
        count = len(doc["pages"])
        return [page_file_name(doc["stem"], i, count, page["ext"]) for i, page in enumerate(doc["pages"])]

    def _page_paths(self, doc: dict, i: int) -> Paths:
        page = doc["pages"][i]
        folder = self.root / self._section(doc["section"])["folder"]
        return self.vault_dir / f"{page['id']}{ENCRYPTED_SUFFIX}", folder / self._file_names(doc)[i]

    def _original_paths(self, page: dict) -> Paths:
        """Where the first crop keeps the page as uploaded, so it can be restored."""
        return (
            self.originals_dir / f"{page['id']}{ENCRYPTED_SUFFIX}",
            self.originals_dir / f"{page['id']}{page['ext']}",
        )

    def _read(self, paths: Paths) -> Optional[bytes]:
        """Content in whichever form the file is in. Both forms only coexist
        mid-conversion; then the encrypted one wins, since it can only have
        been written by the app (a plain path could hold someone else's file)."""
        encrypted_path, plain_path = paths
        if self.fernet is not None:
            try:
                return self.fernet.decrypt(encrypted_path.read_bytes())
            except FileNotFoundError:
                pass
        try:
            return plain_path.read_bytes()
        except FileNotFoundError:
            return None

    def _write(self, paths: Paths, content: bytes) -> None:
        """Writes in the current mode's form and drops any leftover in the other."""
        encrypted_path, plain_path = paths
        if self.encrypted:
            _atomic_write(encrypted_path, self.fernet.encrypt(content))
            plain_path.unlink(missing_ok=True)
        else:
            plain_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(plain_path, content)
            encrypted_path.unlink(missing_ok=True)

    def _exists(self, paths: Paths) -> bool:
        return any(path.exists() for path in paths)

    @staticmethod
    def _remove(paths: Paths) -> None:
        for path in paths:
            path.unlink(missing_ok=True)

    def _convert(self, paths: Paths) -> bool:
        """Moves one file to the current mode's form; False if it already was.
        The target is written before the source is removed, so a crash in
        between leaves both, and converting again just redoes it."""
        encrypted_path, plain_path = paths
        if self.encrypted:
            if not plain_path.exists():
                return False
            _atomic_write(encrypted_path, self.fernet.encrypt(plain_path.read_bytes()))
            plain_path.unlink()
            return True
        if not encrypted_path.exists() or self.fernet is None:
            return False
        content = self.fernet.decrypt(encrypted_path.read_bytes())
        self._check_not_in_the_way(plain_path, content)
        plain_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(plain_path, content)
        encrypted_path.unlink()
        return True

    def _check_not_in_the_way(self, plain_path: Path, content: bytes) -> None:
        """Someone may have put their own file where a page belongs while the
        library was encrypted; decrypting must never overwrite it. (The same
        content there is just this page, from an interrupted conversion.)"""
        if plain_path.exists() and plain_path.read_bytes() != content:
            raise Conflict("file_in_the_way", path=plain_path.relative_to(self.root).as_posix())

    def _check_decryptable(self) -> None:
        """Runs `_check_not_in_the_way` for every file before decrypting starts,
        so a conflict leaves the library encrypted and untouched."""
        for doc in self.index["documents"].values():
            for i, page in enumerate(doc["pages"]):
                for encrypted_path, plain_path in (self._page_paths(doc, i), self._original_paths(page)):
                    if encrypted_path.exists() and plain_path.exists():
                        self._check_not_in_the_way(plain_path, self.fernet.decrypt(encrypted_path.read_bytes()))

    def _converge(self) -> int:
        """Brings every stored file and section folder in line with the current
        mode. Returns how many files had to be converted."""
        converted = 0
        for doc in self.index["documents"].values():
            for i, page in enumerate(doc["pages"]):
                converted += self._convert(self._page_paths(doc, i))
                converted += self._convert(self._original_paths(page))
        for section in self.index["sections"]:
            folder = self.root / section["folder"]
            if self.encrypted:
                _remove_dir_if_empty(folder)
            else:
                folder.mkdir(exist_ok=True)
        return converted

    def _move(self, moves: List[Tuple[Path, Path]]) -> None:
        """Renames plain files, putting back the ones already moved if one fails."""
        done = []
        try:
            for source, target in moves:
                if source == target or not source.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                done.append((source, target))
        except OSError:
            for source, target in reversed(done):
                os.replace(target, source)
            raise

    # --- naming ----------------------------------------------------------

    def _taken_on_disk(self, folder: Path, exclude: Iterable[str] = ()) -> set:
        """Case-folded names in `folder`, so nothing clashes when the volume is
        browsed from a case-insensitive system. Empty in encrypted mode, where
        no page lives in the tree."""
        if self.encrypted or not folder.is_dir():
            return set()
        excluded = {name.casefold() for name in exclude}
        return {entry.name.casefold() for entry in folder.iterdir()} - excluded

    def _allocate_folder(self, name: str, section: Optional[dict]) -> str:
        """`Name`, or `Name (2)`, ... if another section (or a file, or a
        non-empty folder the app doesn't know) already has it. An empty folder
        that's already there is just adopted."""
        base = safe_name(name, "Section")
        own = section["folder"].casefold() if section else None
        taken = {s["folder"].casefold() for s in self.index["sections"] if s is not section}
        if not self.encrypted:
            for entry in self.root.iterdir():
                if entry.name == META_DIR_NAME or entry.name.casefold() == own:
                    continue
                if not entry.is_dir() or any(entry.iterdir()):
                    taken.add(entry.name.casefold())
        for n in itertools.count(1):
            candidate = base if n == 1 else f"{base} ({n})"
            if candidate.casefold() not in taken:
                return candidate

    def _allocate_stem(self, section: dict, title: str, doc: dict, doc_id: Optional[str]) -> str:
        """File name stem for `doc` in `section`: the title, or `Title (2)`, ...
        if another document there already uses it, or if any of its page files
        would clash with another document's or with a file the app doesn't know."""
        base = safe_name(title, "Document")
        stems, taken = set(), set()
        for other_id, other in self.index["documents"].items():
            if other_id != doc_id and other["section"] == section["id"]:
                stems.add(other["stem"].casefold())
                taken.update(name.casefold() for name in self._file_names(other))
        own = self._file_names(doc) if doc_id and doc["section"] == section["id"] else []
        taken |= self._taken_on_disk(self.root / section["folder"], exclude=own)
        for n in itertools.count(1):
            stem = base if n == 1 else f"{base} ({n})"
            names = self._file_names({**doc, "stem": stem})
            if stem.casefold() not in stems and not any(name.casefold() in taken for name in names):
                return stem

    # --- output ----------------------------------------------------------

    def _doc_out(self, doc_id: str, doc: dict) -> dict:
        folder = self._section(doc["section"])["folder"]
        pages = [
            {**page, "path": f"{folder}/{name}"}
            for page, name in zip(doc["pages"], self._file_names(doc))
        ]
        return {
            "id": doc_id,
            "section": doc["section"],
            "title": doc["title"],
            "date": doc["date"],
            "tags": list(doc["tags"]),
            "uploaded_at": doc["uploaded_at"],
            "pages": pages,
        }

    def _section_out(self, section: dict) -> dict:
        count = sum(1 for doc in self.index["documents"].values() if doc["section"] == section["id"])
        return {**section, "documents": count}

    def _tag_out(self, tag: dict) -> dict:
        count = sum(1 for doc in self.index["documents"].values() if tag["id"] in doc["tags"])
        return {**tag, "documents": count}

    # --- settings ----------------------------------------------------------

    def settings(self) -> dict:
        return {"encrypted": self.encrypted, "encryption_available": self.fernet is not None}

    def set_encrypted(self, enabled: bool) -> int:
        """Turns encryption on/off and converts every stored file (pre-crop
        backups and the index included). Returns how many files were converted.
        Safe to call again with the same value to finish an interrupted switch."""
        with self.lock:
            if enabled and self.fernet is None:
                raise Invalid("encryption_unavailable")
            if not enabled and self.fernet is not None:
                self._check_decryptable()
            self.encrypted = enabled
            _atomic_write(self.settings_path, json.dumps({"encrypted": enabled}).encode())
            self._save_index()
            return self._converge()

    # --- sections ----------------------------------------------------------

    def list_sections(self) -> list:
        with self.lock:
            return [self._section_out(section) for section in self.index["sections"]]

    def create_section(self, name: str, icon: str) -> dict:
        with self.lock:
            name = _clean_label(name, MAX_SECTION_NAME, "name_required")
            self._check_unique(self.index["sections"], name, "section_exists")
            section = {
                "id": uuid.uuid4().hex,
                "name": name,
                "icon": _check_icon(icon),
                "folder": self._allocate_folder(name, None),
            }
            if not self.encrypted:
                (self.root / section["folder"]).mkdir(exist_ok=True)
            self.index["sections"].append(section)
            self._save_index()
            return self._section_out(section)

    def update_section(self, section_id: str, name: str, icon: str) -> dict:
        """Renaming a section renames its folder (and so moves its files along)."""
        with self.lock:
            section = self._section(section_id)
            name = _clean_label(name, MAX_SECTION_NAME, "name_required")
            self._check_unique(self.index["sections"], name, "section_exists", exclude=section)
            icon = _check_icon(icon)
            folder = self._allocate_folder(name, section)
            if folder != section["folder"] and not self.encrypted:
                old, new = self.root / section["folder"], self.root / folder
                if old.exists():
                    old.rename(new)
                else:
                    new.mkdir(exist_ok=True)
            section.update(name=name, icon=icon, folder=folder)
            self._save_index()
            return self._section_out(section)

    def reorder_sections(self, section_ids: List[str]) -> list:
        with self.lock:
            by_id = {section["id"]: section for section in self.index["sections"]}
            if sorted(section_ids) != sorted(by_id):
                raise Invalid("invalid_order")
            self.index["sections"] = [by_id[section_id] for section_id in section_ids]
            self._save_index()
            return self.list_sections()

    def delete_section(self, section_id: str) -> None:
        """Only empty sections can be deleted. The folder goes too, unless
        something the app doesn't know about is still in it."""
        with self.lock:
            section = self._section(section_id)
            if any(doc["section"] == section_id for doc in self.index["documents"].values()):
                raise Conflict("section_not_empty")
            self.index["sections"].remove(section)
            self._save_index()
            if not self.encrypted:
                _remove_dir_if_empty(self.root / section["folder"])

    # --- tags ----------------------------------------------------------------

    def list_tags(self) -> list:
        with self.lock:
            tags = sorted(self.index["tags"], key=lambda tag: tag["name"].casefold())
            return [self._tag_out(tag) for tag in tags]

    def create_tag(self, name: str) -> dict:
        with self.lock:
            name = _clean_label(name, MAX_TAG_NAME, "name_required")
            self._check_unique(self.index["tags"], name, "tag_exists")
            tag = {"id": uuid.uuid4().hex, "name": name}
            self.index["tags"].append(tag)
            self._save_index()
            return self._tag_out(tag)

    def rename_tag(self, tag_id: str, name: str) -> dict:
        with self.lock:
            tag = self._tag(tag_id)
            name = _clean_label(name, MAX_TAG_NAME, "name_required")
            self._check_unique(self.index["tags"], name, "tag_exists", exclude=tag)
            tag["name"] = name
            self._save_index()
            return self._tag_out(tag)

    def delete_tag(self, tag_id: str) -> None:
        """Deleting a tag just takes it off every document that had it."""
        with self.lock:
            tag = self._tag(tag_id)
            self.index["tags"].remove(tag)
            for doc in self.index["documents"].values():
                if tag_id in doc["tags"]:
                    doc["tags"].remove(tag_id)
            self._save_index()

    # --- documents -----------------------------------------------------------

    def list_documents(self, section_id: Optional[str] = None, tag_id: Optional[str] = None) -> list:
        with self.lock:
            items = [
                self._doc_out(doc_id, doc)
                for doc_id, doc in self.index["documents"].items()
                if (section_id is None or doc["section"] == section_id)
                and (tag_id is None or tag_id in doc["tags"])
            ]
        items.sort(key=lambda item: (item["date"], item["uploaded_at"]), reverse=True)
        return items

    def create_document(
        self,
        section_id: str,
        title: str,
        date: str,
        tag_ids: List[str],
        pages: List[Tuple[str, str, bytes]],
        uploaded_at: str,
    ) -> dict:
        """pages: (original filename, mime, content) tuples, in order."""
        with self.lock:
            section = self._section(section_id)
            title = _clean_label(title, MAX_TITLE, "title_required")
            date = _check_date(date)
            tags = self._check_tags(tag_ids)
            if not pages:
                raise Invalid("pages_required")
            if any(not content for _, _, content in pages):
                raise Invalid("empty_file")

            doc_id = uuid.uuid4().hex
            doc = {
                "section": section["id"],
                "title": title,
                "date": date,
                "tags": tags,
                "uploaded_at": uploaded_at,
                "pages": [
                    {
                        "id": uuid.uuid4().hex,
                        "filename": filename,
                        "mime": mime,
                        "ext": extension_for(mime, filename),
                        "size": len(content),
                        "rev": 0,
                        "cropped": False,
                    }
                    for filename, mime, content in pages
                ],
            }
            doc["stem"] = self._allocate_stem(section, title, doc, None)
            written = []
            try:
                for i, (_, _, content) in enumerate(pages):
                    paths = self._page_paths(doc, i)
                    self._write(paths, content)
                    written.append(paths)
            except OSError:
                for paths in written:
                    self._remove(paths)
                raise
            self.index["documents"][doc_id] = doc
            self._save_index()
            return self._doc_out(doc_id, doc)

    def update_document(self, doc_id: str, title: str, date: str, section_id: str, tag_ids: List[str]) -> dict:
        """A new title or section renames/moves the document's files to match."""
        with self.lock:
            doc = self._doc(doc_id)
            section = self._section(section_id)
            title = _clean_label(title, MAX_TITLE, "title_required")
            date = _check_date(date)
            tags = self._check_tags(tag_ids)

            stem = self._allocate_stem(section, title, doc, doc_id)
            moved = {**doc, "section": section["id"], "stem": stem}
            if not self.encrypted:
                self._move([
                    (self._page_paths(doc, i)[1], self._page_paths(moved, i)[1])
                    for i in range(len(doc["pages"]))
                ])
            doc.update(section=section["id"], stem=stem, title=title, date=date, tags=tags)
            self._save_index()
            return self._doc_out(doc_id, doc)

    def delete_document(self, doc_id: str) -> None:
        with self.lock:
            doc = self._doc(doc_id)
            for i, page in enumerate(doc["pages"]):
                self._remove(self._page_paths(doc, i))
                self._remove(self._original_paths(page))
            del self.index["documents"][doc_id]
            self._save_index()

    def read_page(self, doc_id: str, page_id: str) -> Tuple[dict, bytes, str]:
        """(page metadata, content, file name) of one page."""
        with self.lock:
            doc = self._doc(doc_id)
            i = self._page_index(doc, page_id)
            content = self._read(self._page_paths(doc, i))
            if content is None:
                raise NotFound("file_missing")
            return dict(doc["pages"][i]), content, self._file_names(doc)[i]

    def crop_page(self, doc_id: str, page_id: str, content: bytes) -> dict:
        """Replaces a page with a cropped version. The first crop keeps the page
        as uploaded (`originals/`) so it can be restored; later crops only
        replace the current version, never that backup."""
        with self.lock:
            doc = self._doc(doc_id)
            i = self._page_index(doc, page_id)
            page = doc["pages"][i]
            if not page["mime"].startswith("image/"):
                raise Invalid("not_an_image")
            if not content:
                raise Invalid("empty_file")
            paths = self._page_paths(doc, i)
            current = self._read(paths)
            if current is None:
                raise NotFound("file_missing")
            if not self._exists(self._original_paths(page)):
                self._write(self._original_paths(page), current)
            self._write(paths, content)
            page.update(size=len(content), cropped=True, rev=page["rev"] + 1)
            self._save_index()
            return self._doc_out(doc_id, doc)["pages"][i]

    def restore_page(self, doc_id: str, page_id: str) -> dict:
        """Puts back the page as uploaded and drops the backup, so the page is
        back to never having been cropped."""
        with self.lock:
            doc = self._doc(doc_id)
            i = self._page_index(doc, page_id)
            page = doc["pages"][i]
            original = self._read(self._original_paths(page))
            if original is None:
                raise NotFound("no_original")
            self._write(self._page_paths(doc, i), original)
            self._remove(self._original_paths(page))
            page.update(size=len(original), cropped=False, rev=page["rev"] + 1)
            self._save_index()
            return self._doc_out(doc_id, doc)["pages"][i]

    def export_zip(self, doc_ids: List[str]) -> bytes:
        """A zip of the chosen documents laid out like the volume itself
        (`Section/Title.ext`), whatever the encryption mode."""
        buf = io.BytesIO()
        with self.lock, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for doc_id in doc_ids:
                doc = self.index["documents"].get(doc_id)
                if doc is None:
                    continue
                for i, page in enumerate(self._doc_out(doc_id, doc)["pages"]):
                    content = self._read(self._page_paths(doc, i))
                    if content is not None:
                        zf.writestr(page["path"], content)
        return buf.getvalue()
