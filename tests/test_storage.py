import io
import json
import os
import shutil
import zipfile

import pytest
from cryptography.fernet import Fernet
from PIL import Image
from pypdf import PdfReader

from app.storage import (
    Conflict,
    EncryptionKeyError,
    Invalid,
    Library,
    NotFound,
    page_file_name,
    safe_name,
)

from .conftest import JPEG, PDF, PNG, add_doc, image, pdf, size_of, tree


# --- naming ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("RG / CPF", "RG - CPF"),
        ("Exame 01:09\\2026", "Exame 01-09-2026"),
        ('What? "Yes" <no>|*', "What Yes no"),
        ("..hidden", "hidden"),
        (". .papelada", "papelada"),
        ("trailing. . ", "trailing"),
        ("  lots   of\tspace ", "lots of space"),
        ("CON", "CON_"),
        ("lpt1.txt", "lpt1.txt_"),
        ("???", "Fallback"),
        ("", "Fallback"),
        ("Camíla", "Camíla"),
    ],
)
def test_safe_name(text, expected):
    assert safe_name(text, "Fallback") == expected


def test_safe_name_truncates_by_bytes_without_splitting_characters():
    name = safe_name("ã" * 200, "x")
    assert len(name.encode("utf-8")) <= 150
    assert set(name) == {"ã"}


def test_page_file_name():
    assert page_file_name("RG", 0, 1, ".jpg") == "RG.jpg"
    assert page_file_name("RG", 1, 2, ".jpg") == "RG - 2.jpg"
    assert page_file_name("Exam", 2, 12, ".pdf") == "Exam - 03.pdf"


# --- sections and readable files -------------------------------------------------


def test_documents_are_readable_files_in_their_section_folder(lib, tmp_path):
    alice = lib.create_section("Alice", "user")
    assert (tmp_path / "Alice").is_dir()

    add_doc(lib, alice, "RG")
    add_doc(lib, alice, "CNH", pages=[("f.jpg", "image/jpeg", JPEG), ("b.png", "image/png", PNG)])
    add_doc(lib, alice, "Contract", pages=[("contract.docx", "application/vnd.openxmlformats", b"docx")])

    assert tree(tmp_path) == ["Alice/CNH - 1.jpg", "Alice/CNH - 2.png", "Alice/Contract.docx", "Alice/RG.jpg"]
    assert (tmp_path / "Alice/RG.jpg").read_bytes() == JPEG


def test_same_title_gets_a_numbered_name(lib, tmp_path):
    section = lib.create_section("Home", "house")
    add_doc(lib, section, "Receipt")
    add_doc(lib, section, "receipt")
    doc = add_doc(lib, section, "Receipt")

    assert tree(tmp_path) == ["Home/Receipt (3).jpg", "Home/Receipt.jpg", "Home/receipt (2).jpg"]
    assert doc["title"] == "Receipt"
    assert doc["pages"][0]["path"] == "Home/Receipt (3).jpg"


def test_names_never_clash_with_another_documents_page_files(lib, tmp_path):
    section = lib.create_section("S", "folder")
    add_doc(lib, section, "A", pages=[("1.jpg", "image/jpeg", JPEG), ("2.jpg", "image/jpeg", JPEG)])
    add_doc(lib, section, "A - 1")
    assert tree(tmp_path) == ["S/A - 1 (2).jpg", "S/A - 1.jpg", "S/A - 2.jpg"]


def test_a_file_the_app_didnt_write_is_never_overwritten(lib, tmp_path):
    section = lib.create_section("S", "folder")
    (tmp_path / "S/RG.jpg").write_bytes(b"mine")
    add_doc(lib, section, "RG")
    assert (tmp_path / "S/RG.jpg").read_bytes() == b"mine"
    assert (tmp_path / "S/RG (2).jpg").read_bytes() == JPEG


def test_section_names_are_unique_and_folders_avoid_foreign_ones(lib, tmp_path):
    lib.create_section("Car", "car")
    with pytest.raises(Conflict):
        lib.create_section("car", "car")

    (tmp_path / "Pets").mkdir()
    (tmp_path / "Pets/old.txt").write_text("not ours")
    (tmp_path / "House").mkdir()
    assert lib.create_section("Pets", "cat")["folder"] == "Pets (2)"
    assert lib.create_section("House", "house")["folder"] == "House"  # an empty folder is adopted


def test_section_folder_names_are_sanitized(lib, tmp_path):
    section = lib.create_section("Taxes 2025/2026", "landmark")
    assert section["name"] == "Taxes 2025/2026"
    assert section["folder"] == "Taxes 2025-2026"
    assert (tmp_path / "Taxes 2025-2026").is_dir()


def test_renaming_a_section_renames_its_folder(lib, tmp_path):
    section = lib.create_section("Bob", "user")
    add_doc(lib, section, "Passport")
    (tmp_path / "Bob/notes.txt").write_text("not ours, but it comes along")

    updated = lib.update_section(section["id"], "Bob Jr.", "heart")
    assert updated["name"] == "Bob Jr."
    assert updated["folder"] == "Bob Jr"  # Windows drops trailing dots
    assert updated["icon"] == "heart"
    assert tree(tmp_path) == ["Bob Jr/Passport.jpg", "Bob Jr/notes.txt"]
    assert lib.read_page(*_first_page(lib))[1] == JPEG


def test_renaming_or_moving_a_document_moves_its_files(lib, tmp_path):
    a = lib.create_section("A", "folder")
    b = lib.create_section("B", "folder")
    doc = add_doc(lib, a, "Old", pages=[("1.jpg", "image/jpeg", JPEG), ("2.pdf", "application/pdf", PDF)])

    lib.update_document(doc["id"], "New", "2026-02-03", a["id"], [])
    assert tree(tmp_path) == ["A/New - 1.jpg", "A/New - 2.pdf"]

    add_doc(lib, b, "New")
    moved = lib.update_document(doc["id"], "New", "2026-02-03", b["id"], [])
    assert tree(tmp_path) == ["B/New (2) - 1.jpg", "B/New (2) - 2.pdf", "B/New.jpg"]
    assert moved["section"] == b["id"]
    assert moved["date"] == "2026-02-03"


def test_case_only_rename_keeps_the_same_slot(lib, tmp_path):
    section = lib.create_section("S", "folder")
    doc = add_doc(lib, section, "rg")
    lib.update_document(doc["id"], "RG", doc["date"], section["id"], [])
    assert tree(tmp_path) == ["S/RG.jpg"]


def test_only_empty_sections_can_be_deleted(lib, tmp_path):
    full = lib.create_section("Full", "folder")
    doc = add_doc(lib, full, "Doc")
    with pytest.raises(Conflict):
        lib.delete_section(full["id"])

    lib.delete_document(doc["id"])
    lib.delete_section(full["id"])
    assert not (tmp_path / "Full").exists()
    assert lib.list_sections() == []


def test_deleting_a_section_keeps_a_folder_with_foreign_files(lib, tmp_path):
    section = lib.create_section("S", "folder")
    (tmp_path / "S/keep.txt").write_text("x")
    lib.delete_section(section["id"])
    assert tree(tmp_path) == ["S/keep.txt"]


def test_reorder_sections(lib):
    a, b, c = (lib.create_section(name, "folder") for name in "ABC")
    assert [s["name"] for s in lib.reorder_sections([c["id"], a["id"], b["id"]])] == ["C", "A", "B"]
    with pytest.raises(Invalid):
        lib.reorder_sections([a["id"], b["id"]])


def test_invalid_input_is_rejected(lib):
    section = lib.create_section("S", "folder")
    with pytest.raises(Invalid):
        lib.create_section("   ", "folder")
    with pytest.raises(Invalid):
        lib.create_section("X", "<svg>")
    with pytest.raises(Invalid):
        add_doc(lib, section, " ")
    with pytest.raises(Invalid):
        add_doc(lib, section, "Doc", date="02/01/2026")
    with pytest.raises(Invalid):
        add_doc(lib, section, "Doc", tags=["nope"])
    with pytest.raises(Invalid):
        add_doc(lib, section, "Doc", pages=[("empty.jpg", "image/jpeg", b"")])
    with pytest.raises(NotFound):
        lib.create_document("nope", "Doc", "2026-01-01", [], [("a.jpg", "image/jpeg", JPEG)], "x")


# --- tags --------------------------------------------------------------------------


def test_tags(lib):
    section = lib.create_section("S", "folder")
    health = lib.create_tag("Health")
    taxes = lib.create_tag("Taxes")
    with pytest.raises(Conflict):
        lib.create_tag("health")

    exam = add_doc(lib, section, "Exam", tags=[health["id"]])
    add_doc(lib, section, "Receipt", tags=[taxes["id"], health["id"]])
    add_doc(lib, section, "Other")

    assert {d["title"] for d in lib.list_documents(section["id"], health["id"])} == {"Exam", "Receipt"}
    assert {t["name"]: t["documents"] for t in lib.list_tags()} == {"Health": 2, "Taxes": 1}

    lib.rename_tag(health["id"], "Medical")
    assert [t["name"] for t in lib.list_tags()] == ["Medical", "Taxes"]

    lib.delete_tag(health["id"])
    assert [d["tags"] for d in lib.list_documents() if d["id"] == exam["id"]] == [[]]
    assert [t["name"] for t in lib.list_tags()] == ["Taxes"]


def test_documents_are_listed_newest_first(lib):
    section = lib.create_section("S", "folder")
    add_doc(lib, section, "Old", date="2020-01-01")
    add_doc(lib, section, "New", date="2026-01-01")
    assert [d["title"] for d in lib.list_documents(section["id"])] == ["New", "Old"]


# --- page edits ----------------------------------------------------------------------


def _photo_doc(lib, title="ID", content=None, section=None):
    section = section or lib.create_section("S", "folder")
    doc = add_doc(lib, section, title, pages=[("p.jpg", "image/jpeg", content or image((60, 40)))])
    return section, doc, doc["pages"][0]["id"]


def test_edits_keep_the_upload_once_and_restore_brings_it_back(lib, tmp_path):
    uploaded = image((60, 40))
    _, doc, page_id = _photo_doc(lib, content=uploaded)
    backup = tmp_path / ".papelada/originals" / f"{page_id}.jpg"

    page = lib.edit_page(doc["id"], page_id, {"crop": {"x": 0, "y": 0, "w": 0.5, "h": 1}})
    assert page["edited"] and page["rev"] == 1 and page["edits"] == {"crop": {"x": 0, "y": 0, "w": 0.5, "h": 1}}
    assert size_of((tmp_path / "S/ID.jpg").read_bytes()) == (30, 40)
    assert backup.read_bytes() == uploaded

    # A new recipe starts again from the upload, not from the cropped page.
    lib.edit_page(doc["id"], page_id, {"rotate": 90})
    assert size_of((tmp_path / "S/ID.jpg").read_bytes()) == (40, 60)
    assert backup.read_bytes() == uploaded

    page = lib.restore_page(doc["id"], page_id)
    assert not page["edited"] and "edits" not in page and page["rev"] == 3
    assert (tmp_path / "S/ID.jpg").read_bytes() == uploaded
    assert not backup.exists()
    with pytest.raises(NotFound):
        lib.restore_page(doc["id"], page_id)


def test_rotation_comes_before_the_crop(lib, tmp_path):
    _, doc, page_id = _photo_doc(lib, content=image((60, 40)))
    lib.edit_page(doc["id"], page_id, {"rotate": 90, "crop": {"x": 0, "y": 0, "w": 1, "h": 0.5}})
    assert size_of((tmp_path / "S/ID.jpg").read_bytes()) == (40, 30)


def test_no_edits_is_a_restore(lib, tmp_path):
    uploaded = image()
    _, doc, page_id = _photo_doc(lib, content=uploaded)
    assert lib.edit_page(doc["id"], page_id, {"rotate": 0, "crop": {"x": 0, "y": 0, "w": 1, "h": 1}})["rev"] == 0
    lib.edit_page(doc["id"], page_id, {"filter": "scan"})
    page = lib.edit_page(doc["id"], page_id, {})
    assert not page["edited"]
    assert (tmp_path / "S/ID.jpg").read_bytes() == uploaded


def test_filter_and_reduce(lib, tmp_path):
    _, doc, page_id = _photo_doc(lib, content=image((3000, 1500)))
    lib.edit_page(doc["id"], page_id, {"filter": "scan", "reduce": True})
    with Image.open(tmp_path / "S/ID.jpg") as im:
        assert im.size == (2000, 1000)
        assert im.mode == "L"


def test_converting_renames_the_file_and_restore_renames_it_back(lib, tmp_path):
    uploaded = image()
    _, doc, page_id = _photo_doc(lib, content=uploaded)

    page = lib.edit_page(doc["id"], page_id, {"format": "png"})
    assert (page["mime"], page["ext"], page["path"]) == ("image/png", ".png", "S/ID.png")
    assert tree(tmp_path) == ["S/ID.png"]
    assert (tmp_path / "S/ID.png").read_bytes().startswith(b"\x89PNG")
    assert (tmp_path / ".papelada/originals" / f"{page_id}.jpg").read_bytes() == uploaded

    page = lib.edit_page(doc["id"], page_id, {"format": "pdf", "rotate": 180})
    assert page["mime"] == "application/pdf" and page["editable"]
    assert tree(tmp_path) == ["S/ID.pdf"]
    assert (tmp_path / "S/ID.pdf").read_bytes().startswith(b"%PDF")

    page = lib.restore_page(doc["id"], page_id)
    assert (page["mime"], page["ext"]) == ("image/jpeg", ".jpg")
    assert tree(tmp_path) == ["S/ID.jpg"]
    assert (tmp_path / "S/ID.jpg").read_bytes() == uploaded


def test_converting_never_overwrites_another_file(lib, tmp_path):
    section = lib.create_section("S", "folder")
    doc = add_doc(lib, section, "ID", pages=[("a.jpg", "image/jpeg", image()), ("b.jpg", "image/jpeg", image())])
    (tmp_path / "S/ID - 1.png").write_bytes(b"mine")

    lib.edit_page(doc["id"], doc["pages"][0]["id"], {"format": "png"})
    # The whole document moves to a stem whose names are all free.
    assert tree(tmp_path) == ["S/ID (2) - 1.png", "S/ID (2) - 2.jpg", "S/ID - 1.png"]
    assert (tmp_path / "S/ID - 1.png").read_bytes() == b"mine"


def test_only_images_can_be_edited(lib):
    section = lib.create_section("S", "folder")
    doc = add_doc(lib, section, "Doc", pages=[("a.pdf", "application/pdf", PDF)])
    assert not doc["pages"][0]["editable"]
    with pytest.raises(Invalid) as exc:
        lib.edit_page(doc["id"], doc["pages"][0]["id"], {"rotate": 90})
    assert exc.value.code == "not_an_image"


@pytest.mark.parametrize("edits", [
    {"rotate": 45},
    {"filter": "sepia"},
    {"format": "bmp"},
    {"crop": {"x": 1.5, "y": 0, "w": 0.5, "h": 0.5}},
    {"crop": {"x": 0, "y": 0, "w": 0}},
])
def test_invalid_edits_are_rejected(lib, edits):
    _, doc, page_id = _photo_doc(lib)
    with pytest.raises(Invalid) as exc:
        lib.edit_page(doc["id"], page_id, edits)
    assert exc.value.code == "invalid_edits"


def test_an_unreadable_image_cant_be_edited(lib):
    _, doc, page_id = _photo_doc(lib, content=JPEG)
    with pytest.raises(Invalid) as exc:
        lib.edit_page(doc["id"], page_id, {"rotate": 90})
    assert exc.value.code == "unreadable_image"


def test_deleting_a_document_removes_its_files_and_backups(lib, tmp_path):
    _, doc, page_id = _photo_doc(lib)
    lib.edit_page(doc["id"], page_id, {"rotate": 90})
    lib.thumbnail(doc["id"], page_id)
    lib.delete_document(doc["id"])
    assert tree(tmp_path) == []
    assert list((tmp_path / ".papelada/originals").iterdir()) == []
    assert list((tmp_path / ".papelada/thumbs").iterdir()) == []
    assert (tmp_path / "S").is_dir()


def test_v1_crops_become_edited_pages(lib, tmp_path, key):
    """A v1 index has `cropped` instead of `edited`, and no recipe."""
    _, doc, page_id = _photo_doc(lib)
    index = json.loads((tmp_path / ".papelada/index.json").read_text())
    index["version"] = 1
    page = index["documents"][doc["id"]]["pages"][0]
    del page["edited"]
    page["cropped"] = True
    (tmp_path / ".papelada/index.json").write_text(json.dumps(index))
    (tmp_path / ".papelada/originals" / f"{page_id}.jpg").write_bytes(image((80, 80)))

    reopened = Library(tmp_path, key)
    page = reopened.list_documents()[0]["pages"][0]
    assert page["edited"] and "cropped" not in page
    assert size_of(reopened.thumbnail(doc["id"], page_id)) == (60, 40)  # the crop as it is, not the original
    reopened.restore_page(doc["id"], page_id)
    assert size_of((tmp_path / "S/ID.jpg").read_bytes()) == (80, 80)


# --- thumbnails, previews and PDFs -------------------------------------------------------


@pytest.mark.parametrize("encrypted", [False, True])
def test_thumbnails_follow_the_edits_and_are_cached_per_revision(lib, tmp_path, encrypted):
    lib.set_encrypted(encrypted)
    _, doc, page_id = _photo_doc(lib, content=image((1200, 800)))
    thumbs = tmp_path / ".papelada/thumbs"

    thumb = lib.thumbnail(doc["id"], page_id)
    assert size_of(thumb) == (400, 267)
    assert [p.name for p in thumbs.iterdir()] == [f"{page_id}-0" + (".enc" if encrypted else ".webp")]
    assert lib.thumbnail(doc["id"], page_id) == thumb

    lib.edit_page(doc["id"], page_id, {"rotate": 90, "format": "pdf"})
    assert list(thumbs.iterdir()) == []
    assert size_of(lib.thumbnail(doc["id"], page_id)) == (267, 400)
    assert [p.name.split(".")[0] for p in thumbs.iterdir()] == [f"{page_id}-1"]


def test_switching_encryption_drops_the_thumbnails(lib, tmp_path):
    _, doc, page_id = _photo_doc(lib)
    lib.thumbnail(doc["id"], page_id)
    lib.set_encrypted(True)
    assert list((tmp_path / ".papelada/thumbs").iterdir()) == []


def test_only_images_have_thumbnails(lib):
    section = lib.create_section("S", "folder")
    doc = add_doc(lib, section, "Doc", pages=[("a.pdf", "application/pdf", PDF)])
    with pytest.raises(NotFound):
        lib.thumbnail(doc["id"], doc["pages"][0]["id"])


def test_the_editor_preview_is_the_upload_scaled_down(lib):
    _, doc, page_id = _photo_doc(lib, content=image((4000, 3000)))
    lib.edit_page(doc["id"], page_id, {"crop": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}})
    content, mime = lib.edit_preview(doc["id"], page_id)
    assert mime == "image/jpeg"
    assert size_of(content) == (2048, 1536)


def test_document_pdf_merges_pdfs_and_images(lib):
    section = lib.create_section("S", "folder")
    doc = add_doc(lib, section, "Exam", pages=[
        ("a.jpg", "image/jpeg", image()), ("b.pdf", "application/pdf", pdf(pages=2)), ("c.png", "image/png", image(fmt="PNG")),
    ])
    content, name = lib.document_pdf(doc["id"])
    assert name == "Exam.pdf"
    assert len(PdfReader(io.BytesIO(content)).pages) == 4

    other = add_doc(lib, section, "Notes", pages=[("n.txt", "text/plain", b"hello")])
    with pytest.raises(Invalid) as exc:
        lib.document_pdf(other["id"])
    assert exc.value.code == "not_exportable"


# --- uploads -------------------------------------------------------------------------------


GPS, MAKE, ORIENTATION = 0x8825, 0x010F, 0x0112


def _uploaded(lib, tmp_path, content, mime="image/jpeg", name="p.jpg"):
    section = lib.create_section("S", "folder")
    doc = add_doc(lib, section, "P", pages=[(name, mime, content)])
    return (tmp_path / doc["pages"][0]["path"]).read_bytes()


def _exif(content):
    return dict(Image.open(io.BytesIO(content)).getexif())


def test_uploads_lose_their_metadata_losslessly(lib, tmp_path):
    uploaded = image(exif={MAKE: "Phone"})
    stored = _uploaded(lib, tmp_path, uploaded)
    assert _exif(stored) == {}
    assert b"Phone" not in stored
    # Same image data: only the metadata segment is gone.
    assert stored.endswith(uploaded[uploaded.index(b"\xff\xdb"):])


def test_uploads_are_turned_upright(lib, tmp_path):
    stored = _uploaded(lib, tmp_path, image((60, 40), exif={ORIENTATION: 6, MAKE: "Phone"}))
    assert size_of(stored) == (40, 60)
    assert _exif(stored) == {}


def test_metadata_can_be_kept(lib, tmp_path):
    lib.update_upload_settings(strip_metadata=False)
    uploaded = image(exif={MAKE: "Phone"})
    assert _uploaded(lib, tmp_path, uploaded) == uploaded


def test_kept_metadata_survives_turning_upright(lib, tmp_path):
    lib.update_upload_settings(strip_metadata=False)
    stored = _uploaded(lib, tmp_path, image((60, 40), exif={ORIENTATION: 6, MAKE: "Phone"}))
    assert size_of(stored) == (40, 60)
    assert _exif(stored) == {MAKE: "Phone"}


def test_big_uploads_can_be_reduced(lib, tmp_path, key):
    assert lib.settings()["reduce_uploads"] is False
    lib.update_upload_settings(reduce_uploads=True)
    assert Library(tmp_path, key).settings()["reduce_uploads"] is True
    assert size_of(_uploaded(lib, tmp_path, image((3000, 1000), fmt="PNG"), "image/png", "p.png")) == (2000, 667)


def test_other_files_are_uploaded_as_they_are(lib, tmp_path):
    assert _uploaded(lib, tmp_path, JPEG) == JPEG


# --- encryption ------------------------------------------------------------------------


def _first_page(lib):
    doc = lib.list_documents()[0]
    return doc["id"], doc["pages"][0]["id"]


def _populate(lib):
    alice = lib.create_section("Alice", "user")
    tag = lib.create_tag("Health")
    add_doc(lib, alice, "Blood test", pages=[("a.jpg", "image/jpeg", JPEG), ("b.pdf", "application/pdf", PDF)],
            tags=[tag["id"]])
    cropped = add_doc(lib, alice, "RG", pages=[("rg.jpg", "image/jpeg", image((60, 40)))])
    cropped["pages"][0] = lib.edit_page(cropped["id"], cropped["pages"][0]["id"], {"crop": {"x": 0, "y": 0, "w": 0.5, "h": 1}})
    return alice, cropped


def test_encrypting_leaves_nothing_readable_in_the_volume(lib, tmp_path, key):
    alice, cropped = _populate(lib)
    before = tree(tmp_path)

    assert lib.set_encrypted(True) == 4  # 3 pages + 1 backup of an edited page
    assert tree(tmp_path) == []
    assert not (tmp_path / "Alice").exists()
    assert not (tmp_path / ".papelada/index.json").exists()
    readable = [p for p in (tmp_path / ".papelada").rglob("*") if p.is_file() and p.name != "settings.json"]
    assert all(p.suffix == ".enc" for p in readable)
    assert not any(b"Blood test" in p.read_bytes() or JPEG in p.read_bytes() for p in readable)

    # Still fully usable, and reopens with the same key.
    cropped_content = lib.read_page(cropped["id"], cropped["pages"][0]["id"])[1]
    assert size_of(cropped_content) == (30, 40)
    reopened = Library(tmp_path, key)
    assert reopened.settings()["encrypted"] is True
    assert len(reopened.list_documents(alice["id"])) == 2

    assert reopened.set_encrypted(False) == 4
    assert tree(tmp_path) == before
    assert (tmp_path / "Alice/RG.jpg").read_bytes() == cropped_content
    reopened.restore_page(cropped["id"], cropped["pages"][0]["id"])
    assert size_of((tmp_path / "Alice/RG.jpg").read_bytes()) == (60, 40)


def test_changes_made_while_encrypted_show_up_as_names_when_decrypted(lib, tmp_path):
    lib.set_encrypted(True)
    section = lib.create_section("Car", "car")
    doc = add_doc(lib, section, "Insurance")
    add_doc(lib, section, "Insurance")
    lib.update_section(section["id"], "Car 2026", "car")
    lib.update_document(doc["id"], "Insurance policy", doc["date"], section["id"], [])
    assert tree(tmp_path) == []

    lib.set_encrypted(False)
    assert tree(tmp_path) == ["Car 2026/Insurance (2).jpg", "Car 2026/Insurance policy.jpg"]


def test_encryption_needs_a_key(tmp_path):
    lib = Library(tmp_path, None)
    assert lib.settings() == {
        "encrypted": False, "encryption_available": False, "strip_metadata": True, "reduce_uploads": False,
    }
    with pytest.raises(Invalid):
        lib.set_encrypted(True)


def test_an_encrypted_library_wont_open_without_the_right_key(lib, tmp_path):
    _populate(lib)
    lib.set_encrypted(True)
    with pytest.raises(EncryptionKeyError):
        Library(tmp_path, None)
    with pytest.raises(EncryptionKeyError):
        Library(tmp_path, Fernet.generate_key())


def test_an_interrupted_switch_is_finished_on_the_next_start(lib, tmp_path, key):
    _populate(lib)
    # Crash right after the mode was saved, before any file was converted.
    (tmp_path / ".papelada/settings.json").write_text(json.dumps({"encrypted": True}))
    reopened = Library(tmp_path, key)
    assert tree(tmp_path) == []
    assert not (tmp_path / ".papelada/index.json").exists()

    # Crash after a page was written in the new form but before the old one was removed.
    reopened.set_encrypted(False)
    page = tmp_path / "Alice/RG.jpg"
    reopened.set_encrypted(True)
    page.parent.mkdir()
    page.write_bytes(b"leftover")
    Library(tmp_path, key)
    assert tree(tmp_path) == []


def test_decrypting_never_overwrites_a_file_someone_put_in_the_way(lib, tmp_path):
    section = lib.create_section("S", "folder")
    add_doc(lib, section, "RG")
    lib.set_encrypted(True)
    (tmp_path / "S").mkdir()
    (tmp_path / "S/RG.jpg").write_bytes(b"mine")

    with pytest.raises(Conflict) as exc:
        lib.set_encrypted(False)
    assert exc.value.info == {"path": "S/RG.jpg"}
    assert lib.settings()["encrypted"] is True
    assert (tmp_path / "S/RG.jpg").read_bytes() == b"mine"
    assert lib.read_page(*_first_page(lib))[1] == JPEG

    # Even if a crash had left the library in plain mode, the page is read from the vault.
    lib.encrypted = False
    assert lib.read_page(*_first_page(lib))[1] == JPEG
    lib.encrypted = True

    (tmp_path / "S/RG.jpg").unlink()
    assert lib.set_encrypted(False) == 1
    assert (tmp_path / "S/RG.jpg").read_bytes() == JPEG


# --- export ----------------------------------------------------------------------------------


@pytest.mark.parametrize("encrypted", [False, True])
def test_zip_export_mirrors_the_folder_layout(lib, encrypted):
    alice, cropped = _populate(lib)
    lib.set_encrypted(encrypted)
    data = lib.export_zip([d["id"] for d in lib.list_documents()] + ["missing"])
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert sorted(zf.namelist()) == ["Alice/Blood test - 1.jpg", "Alice/Blood test - 2.pdf", "Alice/RG.jpg"]
        assert size_of(zf.read("Alice/RG.jpg")) == (30, 40)


def test_missing_file_is_reported(lib, tmp_path):
    section = lib.create_section("S", "folder")
    doc = add_doc(lib, section, "Doc")
    shutil.move(tmp_path / "S/Doc.jpg", tmp_path / "S/Renamed by hand.jpg")
    with pytest.raises(NotFound) as exc:
        lib.read_page(doc["id"], doc["pages"][0]["id"])
    assert exc.value.code == "file_missing"


# --- scan ------------------------------------------------------------------------


def test_scan_adopts_files_dropped_into_a_section_folder(lib, tmp_path):
    section = lib.create_section("Alice", "user")
    known = add_doc(lib, section, "Passport")
    (tmp_path / "Alice" / "Blood test.PDF").write_bytes(PDF)
    (tmp_path / "Alice" / ".hidden.jpg").write_bytes(JPEG)
    (tmp_path / "Alice" / "empty.jpg").write_bytes(b"")
    (tmp_path / "Alice" / "subfolder").mkdir()
    os.utime(tmp_path / "Alice" / "Blood test.PDF", (0, 1_000_000_000))  # 2001-09-09 UTC

    # Encrypted libraries have no section folders to scan.
    lib.set_encrypted(True)
    with pytest.raises(Conflict) as err:
        lib.scan()
    assert err.value.code == "scan_needs_plain"
    lib.set_encrypted(False)

    assert lib.scan() == {"sections": 0, "documents": 1}
    docs = {d["title"]: d for d in lib.list_documents(section["id"])}
    assert set(docs) == {"Passport", "Blood test"}
    new = docs["Blood test"]
    assert new["date"].startswith("2001-09-")
    assert new["pages"][0]["path"] == "Alice/Blood test.PDF"
    assert new["pages"][0]["mime"] == "application/pdf"
    assert lib.read_page(new["id"], new["pages"][0]["id"])[1] == PDF
    assert docs["Passport"]["id"] == known["id"]
    assert tree(tmp_path) == ["Alice/.hidden.jpg", "Alice/Blood test.PDF", "Alice/Passport.jpg", "Alice/empty.jpg"]

    assert lib.scan() == {"sections": 0, "documents": 0}


def test_scan_creates_sections_from_new_folders(lib, tmp_path):
    (tmp_path / "Rex").mkdir()
    (tmp_path / "Rex" / "Vaccines.jpg").write_bytes(JPEG)
    (tmp_path / "Empty").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "loose.jpg").write_bytes(JPEG)

    assert lib.scan() == {"sections": 2, "documents": 1}
    sections = {s["name"]: s for s in lib.list_sections()}
    assert set(sections) == {"Empty", "Rex"}
    assert sections["Rex"]["icon"] == "folder" and sections["Rex"]["folder"] == "Rex"
    assert sections["Rex"]["documents"] == 1

    # The adopted section behaves like any other: renaming it moves its folder.
    lib.update_section(sections["Rex"]["id"], "Rex the dog", "dog")
    assert tree(tmp_path) == ["Rex the dog/Vaccines.jpg", "loose.jpg"]


def test_scan_keeps_names_when_stems_clash(lib, key, tmp_path):
    section = lib.create_section("S", "folder")
    (tmp_path / "S" / "scan.jpg").write_bytes(JPEG)
    (tmp_path / "S" / "scan.png").write_bytes(PNG)

    assert lib.scan() == {"sections": 0, "documents": 2}
    paths = sorted(p["path"] for d in lib.list_documents(section["id"]) for p in d["pages"])
    assert paths == ["S/scan.jpg", "S/scan.png"]
    assert tree(tmp_path) == ["S/scan.jpg", "S/scan.png"]

    # Survives an encryption round trip and a restart with the same names.
    lib.set_encrypted(True)
    lib.set_encrypted(False)
    assert tree(tmp_path) == ["S/scan.jpg", "S/scan.png"]
    reopened = Library(tmp_path, key)
    assert sorted(p["path"] for d in reopened.list_documents() for p in d["pages"]) == paths
