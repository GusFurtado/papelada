"""Papelada's library: sections, tags and documents kept in one volume.

Layout of the volume (DATA_DIR, `/data` in the container):

    <Section>/<Document title>.<ext>            a single-page document
    <Section>/<Document title> - 2.<ext>        page 2 of a multi-page one
    .papelada/index.json                        sections, tags, document metadata
    .papelada/settings.json                     encryption and upload preferences
    .papelada/originals/<page id>.<ext>         an edited page as uploaded
    .papelada/thumbs/<page id>-<rev>.webp       grid thumbnail cache (disposable)
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

from . import images

META_DIR_NAME = ".papelada"
INDEX_FILE_NAME = "index.json"
SETTINGS_FILE_NAME = "settings.json"
VAULT_DIR_NAME = "vault"
ORIGINALS_DIR_NAME = "originals"
THUMBS_DIR_NAME = "thumbs"
ENCRYPTED_SUFFIX = ".enc"
INDEX_VERSION = 2

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
_MIME_BY_EXTENSION = {ext: mime for mime, ext in MIME_EXTENSIONS.items()}
_MIME_BY_EXTENSION.update({".jpeg": "image/jpeg", ".jpe": "image/jpeg", ".tif": "image/tiff"})
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
    """Extension a page is stored with. Set at upload and changed only when an
    edit converts the page, so a page's file name can always be recomputed
    from its metadata."""
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


def _check_expires(value: Optional[str]) -> Optional[str]:
    """An optional expiry date: empty means the document doesn't expire."""
    if not value:
        return None
    try:
        return _check_date(value)
    except Invalid:
        raise Invalid("invalid_expiry")


def fold(text: str) -> str:
    """`text` for matching: case-folded and without accents ("Certidão" -> "certidao")."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


class Library:
    """All state lives in `self.index`, written through to the volume on every
    change. One process owns the volume; `self.lock` serializes requests."""

    def __init__(self, root: Path, key: Optional[bytes] = None):
        self.root = Path(root)
        self.meta_dir = self.root / META_DIR_NAME
        self.vault_dir = self.meta_dir / VAULT_DIR_NAME
        self.originals_dir = self.meta_dir / ORIGINALS_DIR_NAME
        self.thumbs_dir = self.meta_dir / THUMBS_DIR_NAME
        self.settings_path = self.meta_dir / SETTINGS_FILE_NAME
        self.plain_index_path = self.meta_dir / INDEX_FILE_NAME
        self.encrypted_index_path = self.meta_dir / (INDEX_FILE_NAME + ENCRYPTED_SUFFIX)
        self.fernet = Fernet(key) if key else None
        self.lock = threading.RLock()

        try:
            self.vault_dir.mkdir(parents=True, exist_ok=True)
            self.originals_dir.mkdir(parents=True, exist_ok=True)
            self.thumbs_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            raise PermissionError(
                f"Can't write to {self.root}. The folder mounted there must be writable by the user "
                f"the container runs as (uid {os.getuid()}, gid {os.getgid()}); see PUID/PGID in the README."
            )
        settings = json.loads(self.settings_path.read_text()) if self.settings_path.exists() else {}
        self.encrypted = bool(settings.get("encrypted", False))
        self.strip_metadata = bool(settings.get("strip_metadata", True))
        self.reduce_uploads = bool(settings.get("reduce_uploads", False))
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
            return self._migrate(json.loads(data))
        return {"version": INDEX_VERSION, "sections": [], "tags": [], "documents": {}}

    @staticmethod
    def _migrate(index: dict) -> dict:
        """Brings an index written by an older version up to date."""
        if index.get("version", 1) < 2:
            # v1 only had crops, made in the browser: `cropped` pages have an
            # original but no recipe, so their current file is all there is.
            for doc in index["documents"].values():
                for page in doc["pages"]:
                    page["edited"] = page.pop("cropped", False)
        index["version"] = INDEX_VERSION
        return index

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
        """Where the first edit keeps the page as uploaded, so it can be restored
        (with its own extension: an edit may have converted the page)."""
        return (
            self.originals_dir / f"{page['id']}{ENCRYPTED_SUFFIX}",
            self.originals_dir / f"{page['id']}{page.get('original_ext', page['ext'])}",
        )

    def _thumb_paths(self, page: dict) -> Paths:
        name = f"{page['id']}-{page['rev']}"
        return self.thumbs_dir / f"{name}{ENCRYPTED_SUFFIX}", self.thumbs_dir / f"{name}.webp"

    def _drop_thumbs(self, page: dict) -> None:
        for path in self.thumbs_dir.glob(f"{page['id']}-*"):
            path.unlink(missing_ok=True)

    @staticmethod
    def _source_mime(page: dict) -> str:
        """The mime of the page as uploaded, which is what edits start from."""
        return page.get("original_mime", page["mime"])

    def _editable(self, page: dict) -> bool:
        return images.is_readable(self._source_mime(page))

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

    def _allocate_stem(
        self, section: dict, title: str, doc: dict, doc_id: Optional[str],
        keep: Optional[str] = None, own: Optional[List[str]] = None,
    ) -> str:
        """File name stem for `doc` in `section`: the title, or `Title (2)`, ...
        if another document there already uses it, or if any of its page files
        would clash with another document's or with a file the app doesn't know.
        `keep` is tried first, so a stem that still fits isn't renamed. `own` are
        the file names the document has on disk now (by default, the ones `doc`
        computes to), which don't count as taken."""
        base = safe_name(title, "Document")
        stems, taken = set(), set()
        for other_id, other in self.index["documents"].items():
            if other_id != doc_id and other["section"] == section["id"]:
                stems.add(other["stem"].casefold())
                taken.update(name.casefold() for name in self._file_names(other))
        if own is None:
            own = self._file_names(doc) if doc_id and doc["section"] == section["id"] else []
        taken |= self._taken_on_disk(self.root / section["folder"], exclude=own)
        candidates = (base if n == 1 else f"{base} ({n})" for n in itertools.count(1))
        for stem in itertools.chain([keep] if keep else [], candidates):
            names = self._file_names({**doc, "stem": stem})
            if stem.casefold() not in stems and not any(name.casefold() in taken for name in names):
                return stem

    # --- output ----------------------------------------------------------

    def _doc_out(self, doc_id: str, doc: dict) -> dict:
        folder = self._section(doc["section"])["folder"]
        pages = [
            {**page, "path": f"{folder}/{name}", "editable": self._editable(page)}
            for page, name in zip(doc["pages"], self._file_names(doc))
        ]
        return {
            "id": doc_id,
            "section": doc["section"],
            "title": doc["title"],
            "date": doc["date"],
            "expires": doc.get("expires"),
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
        return {
            "encrypted": self.encrypted,
            "encryption_available": self.fernet is not None,
            "strip_metadata": self.strip_metadata,
            "reduce_uploads": self.reduce_uploads,
        }

    def _save_settings(self) -> None:
        data = {"encrypted": self.encrypted, "strip_metadata": self.strip_metadata, "reduce_uploads": self.reduce_uploads}
        _atomic_write(self.settings_path, json.dumps(data).encode())

    def update_upload_settings(self, strip_metadata: Optional[bool] = None, reduce_uploads: Optional[bool] = None) -> dict:
        with self.lock:
            if strip_metadata is not None:
                self.strip_metadata = strip_metadata
            if reduce_uploads is not None:
                self.reduce_uploads = reduce_uploads
            self._save_settings()
            return self.settings()

    def set_encrypted(self, enabled: bool) -> int:
        """Turns encryption on/off and converts every stored file (backups of
        edited pages and the index included). Returns how many files were
        converted. Safe to call again with the same value to finish an
        interrupted switch."""
        with self.lock:
            if enabled and self.fernet is None:
                raise Invalid("encryption_unavailable")
            if not enabled and self.fernet is not None:
                self._check_decryptable()
            self.encrypted = enabled
            self._save_settings()
            self._save_index()
            # Thumbnails are just a cache: dropping them is simpler than
            # converting them, and a plain one must never outlive encrypting.
            for path in self.thumbs_dir.iterdir():
                path.unlink(missing_ok=True)
            return self._converge()

    def scan(self) -> dict:
        """Picks up what someone put in the volume by hand: every file in a
        section's folder that no document owns becomes a document of that
        section, and every top-level folder that's no section's becomes a
        section (default icon) with its files as documents. Files keep their
        names (a document's stem and extension are taken from the file name, so
        nothing is renamed) and dated from the file. Plain mode only, since an
        encrypted library has no section folders. Returns what was added."""
        with self.lock:
            if self.encrypted:
                raise Conflict("scan_needs_plain")
            added = {"sections": 0, "documents": 0}
            known = {section["folder"].casefold() for section in self.index["sections"]}
            for folder in sorted(self._visible(self.root, dirs=True), key=lambda e: e.name.casefold()):
                if folder.name.casefold() in known:
                    continue
                name = self._unique_section_name(folder.name)
                if name is None:
                    continue
                self.index["sections"].append(
                    {"id": uuid.uuid4().hex, "name": name, "icon": "folder", "folder": folder.name}
                )
                added["sections"] += 1
            for section in self.index["sections"]:
                added["documents"] += self._adopt_files(section)
            if added["sections"] or added["documents"]:
                self._save_index()
            return added

    @staticmethod
    def _visible(folder: Path, dirs: bool) -> List[Path]:
        if not folder.is_dir():
            return []
        return [
            entry for entry in folder.iterdir()
            if not entry.name.startswith(".") and (entry.is_dir() if dirs else entry.is_file())
        ]

    def _unique_section_name(self, folder_name: str) -> Optional[str]:
        base = unicodedata.normalize("NFC", re.sub(r"\s+", " ", folder_name)).strip()[:MAX_SECTION_NAME].strip()
        if not base:
            return None
        for n in itertools.count(1):
            candidate = base if n == 1 else f"{base[:MAX_SECTION_NAME - 4].rstrip()} ({n})"
            if not any(s["name"].casefold() == candidate.casefold() for s in self.index["sections"]):
                return candidate

    def _adopt_files(self, section: dict) -> int:
        """Turns the section folder's unknown files into documents."""
        owned, stems = set(), set()
        for doc in self.index["documents"].values():
            if doc["section"] == section["id"]:
                stems.add(doc["stem"].casefold())
                owned.update(name.casefold() for name in self._file_names(doc))
        count = 0
        for entry in sorted(self._visible(self.root / section["folder"], dirs=False), key=lambda e: e.name.casefold()):
            if entry.name.casefold() in owned:
                continue
            size = entry.stat().st_size
            if not size:
                continue
            # A document's stem is unique per section; "a.jpg" next to "a.png" is
            # the second one's whole file name, with no extension of its own.
            suffix = entry.suffix if _EXTENSION.fullmatch(entry.suffix.lower()) else ""
            stem, ext = entry.name[: len(entry.name) - len(suffix)], suffix
            if stem.casefold() in stems:
                stem, ext = entry.name, ""
                if stem.casefold() in stems:
                    continue
            title = unicodedata.normalize("NFC", re.sub(r"\s+", " ", stem)).strip()[:MAX_TITLE].strip() or stem
            mtime = datetime.fromtimestamp(entry.stat().st_mtime)
            self.index["documents"][uuid.uuid4().hex] = {
                "section": section["id"],
                "title": title,
                "date": mtime.strftime("%Y-%m-%d"),
                "tags": [],
                "uploaded_at": datetime.now().astimezone().isoformat(),
                "stem": stem,
                "pages": [{
                    "id": uuid.uuid4().hex,
                    "filename": entry.name,
                    "mime": _MIME_BY_EXTENSION.get(suffix.lower())
                    or mimetypes.guess_type(entry.name)[0]
                    or "application/octet-stream",
                    "ext": ext,
                    "size": size,
                    "rev": 0,
                    "edited": False,
                }],
            }
            stems.add(stem.casefold())
            owned.add(entry.name.casefold())
            count += 1
        return count

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

    def list_documents(
        self, section_id: Optional[str] = None, tag_id: Optional[str] = None, query: Optional[str] = None,
    ) -> list:
        """`query` keeps the documents whose title has every one of its words,
        ignoring case and accents."""
        words = fold(query or "").split()
        with self.lock:
            items = [
                self._doc_out(doc_id, doc)
                for doc_id, doc in self.index["documents"].items()
                if (section_id is None or doc["section"] == section_id)
                and (tag_id is None or tag_id in doc["tags"])
                and all(word in fold(doc["title"]) for word in words)
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
        expires: Optional[str] = None,
    ) -> dict:
        """pages: (original filename, mime, content) tuples, in order."""
        with self.lock:
            section = self._section(section_id)
            title = _clean_label(title, MAX_TITLE, "title_required")
            date = _check_date(date)
            expires = _check_expires(expires)
            tags = self._check_tags(tag_ids)
            if not pages:
                raise Invalid("pages_required")
            if any(not content for _, _, content in pages):
                raise Invalid("empty_file")
            pages = [
                (filename, mime, images.prepare_upload(content, mime, self.strip_metadata, self.reduce_uploads))
                for filename, mime, content in pages
            ]

            doc_id = uuid.uuid4().hex
            doc = {
                "section": section["id"],
                "title": title,
                "date": date,
                "expires": expires,
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
                        "edited": False,
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

    def update_document(
        self, doc_id: str, title: str, date: str, section_id: str, tag_ids: List[str], expires: Optional[str] = None,
    ) -> dict:
        """A new title or section renames/moves the document's files to match."""
        with self.lock:
            doc = self._doc(doc_id)
            section = self._section(section_id)
            title = _clean_label(title, MAX_TITLE, "title_required")
            date = _check_date(date)
            expires = _check_expires(expires)
            tags = self._check_tags(tag_ids)

            stem = self._allocate_stem(section, title, doc, doc_id)
            moved = {**doc, "section": section["id"], "stem": stem}
            if not self.encrypted:
                self._move([
                    (self._page_paths(doc, i)[1], self._page_paths(moved, i)[1])
                    for i in range(len(doc["pages"]))
                ])
            doc.update(section=section["id"], stem=stem, title=title, date=date, expires=expires, tags=tags)
            self._save_index()
            return self._doc_out(doc_id, doc)

    def delete_document(self, doc_id: str) -> None:
        with self.lock:
            doc = self._doc(doc_id)
            for i, page in enumerate(doc["pages"]):
                self._remove(self._page_paths(doc, i))
                self._remove(self._original_paths(page))
                self._drop_thumbs(page)
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

    # --- page edits ----------------------------------------------------------------

    def _replace_page(self, doc_id: str, doc: dict, i: int, content: bytes, updated: dict) -> None:
        """Writes `content` as page `i` and makes `updated` its metadata (size and
        rev are filled in). A new extension renames the page's file, and if that
        name is taken the document gets a new stem (all its pages move). Nothing
        in `doc` changes until the files are in place. Saves the index."""
        page = doc["pages"][i]
        updated = {**updated, "size": len(content), "rev": page["rev"] + 1}
        new = {**doc, "pages": [updated if j == i else p for j, p in enumerate(doc["pages"])]}
        if updated["ext"] != page["ext"]:
            new["stem"] = self._allocate_stem(
                self._section(doc["section"]), doc["title"], new, doc_id, keep=doc["stem"], own=self._file_names(doc)
            )
        count = len(doc["pages"])
        old_paths = [self._page_paths(doc, j) for j in range(count)]
        new_paths = [self._page_paths(new, j) for j in range(count)]
        if not self.encrypted:
            self._move([(old_paths[j][1], new_paths[j][1]) for j in range(count) if j != i])
        self._write(new_paths[i], content)
        doc["stem"] = new["stem"]
        doc["pages"][i] = updated
        self._save_index()
        self._drop_thumbs(page)
        # Encrypted, the plain path is no file of ours: leave whatever is there alone.
        if not self.encrypted and old_paths[i][1] != new_paths[i][1]:
            old_paths[i][1].unlink(missing_ok=True)

    def _edit_source(self, doc: dict, i: int) -> bytes:
        """The page as uploaded: its backup if it was edited, else the page itself."""
        content = self._read(self._original_paths(doc["pages"][i])) or self._read(self._page_paths(doc, i))
        if content is None:
            raise NotFound("file_missing")
        return content

    def edit_page(self, doc_id: str, page_id: str, edits: dict) -> dict:
        """Applies `edits` (see images.py) to the page as uploaded. The first edit
        keeps that upload in `originals/`; later ones start from it again, so
        quality doesn't drop with each edit. No edits at all is a restore."""
        with self.lock:
            doc = self._doc(doc_id)
            i = self._page_index(doc, page_id)
            page = doc["pages"][i]
            if not self._editable(page):
                raise Invalid("not_an_image")
            try:
                edits = images.check_edits(edits)
            except ValueError:
                raise Invalid("invalid_edits")
            if not edits:
                return self.restore_page(doc_id, page_id) if page["edited"] else self._doc_out(doc_id, doc)["pages"][i]

            source = self._edit_source(doc, i)
            source_mime, source_ext = self._source_mime(page), page.get("original_ext", page["ext"])
            try:
                content, mime = images.render(source, source_mime, edits)
            except images.ImageError:
                raise Invalid("unreadable_image")
            if not self._exists(self._original_paths(page)):
                self._write(self._original_paths(page), source)
            self._replace_page(doc_id, doc, i, content, {
                **page,
                "mime": mime,
                "ext": source_ext if mime == source_mime else extension_for(mime, ""),
                "original_mime": source_mime,
                "original_ext": source_ext,
                "edits": edits,
                "edited": True,
            })
            return self._doc_out(doc_id, doc)["pages"][i]

    def restore_page(self, doc_id: str, page_id: str) -> dict:
        """Puts back the page as uploaded and drops the backup, so the page is
        back to never having been edited."""
        with self.lock:
            doc = self._doc(doc_id)
            i = self._page_index(doc, page_id)
            page = doc["pages"][i]
            original_paths = self._original_paths(page)
            original = self._read(original_paths)
            if original is None:
                raise NotFound("no_original")
            updated = {key: value for key, value in page.items() if key not in ("edits", "original_mime", "original_ext")}
            updated.update(mime=self._source_mime(page), ext=page.get("original_ext", page["ext"]), edited=False)
            self._replace_page(doc_id, doc, i, original, updated)
            self._remove(original_paths)
            return self._doc_out(doc_id, doc)["pages"][i]

    def edit_preview(self, doc_id: str, page_id: str) -> Tuple[bytes, str]:
        """The page as uploaded, upright and scaled down, for the editor to draw on."""
        with self.lock:
            doc = self._doc(doc_id)
            i = self._page_index(doc, page_id)
            if not self._editable(doc["pages"][i]):
                raise Invalid("not_an_image")
            source = self._edit_source(doc, i)
        try:
            return images.preview(source)
        except images.ImageError:
            raise Invalid("unreadable_image")

    def thumbnail(self, doc_id: str, page_id: str) -> bytes:
        """A small WebP of the page as it is now, cached per revision. Rendered
        outside the lock, so a grid full of new thumbnails doesn't hold up
        everything else."""
        with self.lock:
            doc = self._doc(doc_id)
            i = self._page_index(doc, page_id)
            page = dict(doc["pages"][i])
            if not self._editable(page):
                raise NotFound("no_thumbnail")
            cached = self._read(self._thumb_paths(page))
            if cached is not None:
                return cached
            # Pages edited before recipes existed (v1 crops) have none to replay.
            if page.get("edits"):
                source, edits = self._edit_source(doc, i), page["edits"]
            else:
                source, edits = self._read(self._page_paths(doc, i)), {}
            if source is None:
                raise NotFound("file_missing")
        try:
            thumb = images.thumbnail(source, edits)
        except images.ImageError:
            raise NotFound("no_thumbnail")
        with self.lock:
            current = self.index["documents"].get(doc_id)
            if current and any(p["id"] == page_id and p["rev"] == page["rev"] for p in current["pages"]):
                self._drop_thumbs(page)
                self._write(self._thumb_paths(page), thumb)
        return thumb

    def _pdf_sources(self, doc: dict) -> List[Tuple[bytes, str]]:
        """(content, mime) of each of the document's pages, for images.document_pdf."""
        pages = []
        for i, page in enumerate(doc["pages"]):
            content = self._read(self._page_paths(doc, i))
            if content is None:
                raise NotFound("file_missing")
            pages.append((content, page["mime"]))
        return pages

    @staticmethod
    def _pdf(pages: List[Tuple[bytes, str]], title: Optional[str] = None) -> bytes:
        try:
            return images.document_pdf(pages)
        except images.ImageError:
            raise Invalid("not_exportable", **({"title": title} if title else {}))

    def document_pdf(self, doc_id: str) -> Tuple[bytes, str]:
        """(content, file name) of the whole document as one PDF."""
        with self.lock:
            doc = self._doc(doc_id)
            pages = self._pdf_sources(doc)
            name = f"{doc['stem']}.pdf"
        return self._pdf(pages), name

    def export_pdfs(self, doc_ids: List[str], merge: bool) -> Tuple[bytes, str]:
        """(content, file name) of the chosen documents as PDFs: with `merge`, all
        of them in one PDF, in the order given; otherwise a zip with one PDF per
        document, laid out like the volume (`Section/Title.pdf`). Unknown ids are
        skipped, like in export_zip. Any page that can't go in a PDF fails the
        whole export (`not_exportable`, with the document's `title`), checked by
        type before any work is done."""
        with self.lock:
            docs = []
            for doc_id in doc_ids:
                doc = self.index["documents"].get(doc_id)
                if doc is not None:
                    folder = self._section(doc["section"])["folder"]
                    docs.append((f"{folder}/{doc['stem']}.pdf", doc["title"], self._pdf_sources(doc)))
        if not docs:
            raise NotFound("document_not_found")
        for _, title, pages in docs:
            if not all(mime == "application/pdf" or images.is_readable(mime) for _, mime in pages):
                raise Invalid("not_exportable", title=title)
        pdfs = [(path, self._pdf(pages, title)) for path, title, pages in docs]
        if merge:
            name = pdfs[0][0].split("/")[-1] if len(pdfs) == 1 else "papelada.pdf"
            return self._pdf([(content, "application/pdf") for _, content in pdfs]), name
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, content in pdfs:
                zf.writestr(path, content)
        return buf.getvalue(), "papelada.zip"

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
