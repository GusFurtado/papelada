import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import Library

from .conftest import JPEG, image, size_of, tree


@pytest.fixture
def client(lib: Library) -> TestClient:
    return TestClient(create_app(lib))


def upload(client, section_id, title, files, tags=()):
    data = {"section": section_id, "title": title, "date": "2026-03-04", "tags": list(tags)}
    res = client.post("/api/documents", data=data, files=[("files", f) for f in files])
    assert res.status_code == 200, res.text
    return res.json()


def test_document_lifecycle(client, tmp_path):
    section = client.post("/api/sections", json={"name": "Rex", "icon": "cat"}).json()
    tag = client.post("/api/tags", json={"name": "Vet"}).json()
    doc = upload(client, section["id"], "Ultrassom", [("u.jpg", JPEG, "image/jpeg")], tags=[tag["id"]])

    assert doc["tags"] == [tag["id"]]
    assert doc["pages"][0]["path"] == "Rex/Ultrassom.jpg"
    assert tree(tmp_path) == ["Rex/Ultrassom.jpg"]
    assert client.get("/api/sections").json()[0]["documents"] == 1
    assert [d["id"] for d in client.get("/api/documents", params={"section": section["id"], "tag": tag["id"]}).json()] == [doc["id"]]

    res = client.put(f"/api/documents/{doc['id']}",
                     json={"title": "Ultrassom abdominal", "date": "2026-03-05", "section": section["id"], "tags": []})
    assert res.status_code == 200
    assert tree(tmp_path) == ["Rex/Ultrassom abdominal.jpg"]

    content_url = f"/api/documents/{doc['id']}/pages/{doc['pages'][0]['id']}/content"
    res = client.get(content_url)
    assert res.content == JPEG
    assert res.headers["content-type"] == "image/jpeg"
    assert res.headers["content-disposition"].startswith("inline")
    res = client.get(content_url, params={"download": 1})
    assert res.headers["content-disposition"].startswith("attachment")
    assert "filename*=UTF-8''Ultrassom%20abdominal.jpg" in res.headers["content-disposition"]

    assert client.delete(f"/api/documents/{doc['id']}").status_code == 200
    assert client.delete(f"/api/sections/{section['id']}").status_code == 200
    assert tree(tmp_path) == []


def test_files_that_could_run_scripts_are_never_served_inline(client):
    section = client.post("/api/sections", json={"name": "S", "icon": "folder"}).json()
    for name, mime in [("x.html", "text/html"), ("x.svg", "image/svg+xml")]:
        doc = upload(client, section["id"], name, [(name, b"<script>alert(1)</script>", mime)])
        res = client.get(f"/api/documents/{doc['id']}/pages/{doc['pages'][0]['id']}/content")
        assert res.headers["content-type"] == "application/octet-stream"
        assert res.headers["content-disposition"].startswith("attachment")
        assert res.headers["x-content-type-options"] == "nosniff"


def test_an_unknown_upload_type_is_guessed_from_the_name(client):
    section = client.post("/api/sections", json={"name": "S", "icon": "folder"}).json()
    doc = upload(client, section["id"], "Scan", [("scan.tif", image(fmt="TIFF"), "application/octet-stream")])
    assert doc["pages"][0]["mime"] == "image/tiff" and doc["pages"][0]["editable"]


def test_errors_carry_a_code_for_the_frontend(client):
    client.post("/api/sections", json={"name": "Car", "icon": "car"})
    res = client.post("/api/sections", json={"name": "car", "icon": "car"})
    assert res.status_code == 409
    assert res.json() == {"detail": "section_exists"}
    assert client.get("/api/documents/nope/pages/nope/content").json() == {"detail": "document_not_found"}


def test_encryption_settings(client, tmp_path):
    assert client.get("/api/settings").json() == {
        "encrypted": False, "encryption_available": True, "strip_metadata": True, "reduce_uploads": False,
    }
    section = client.post("/api/sections", json={"name": "S", "icon": "folder"}).json()
    upload(client, section["id"], "Doc", [("a.jpg", JPEG, "image/jpeg")])

    res = client.put("/api/settings", json={"encrypted": True}).json()
    assert res["encrypted"] is True and res["converted"] == 1
    assert tree(tmp_path) == []


def test_upload_settings_dont_touch_encryption(client):
    res = client.put("/api/settings", json={"strip_metadata": False, "reduce_uploads": True}).json()
    assert res == {"encrypted": False, "encryption_available": True, "strip_metadata": False, "reduce_uploads": True}


def test_page_editing(client, tmp_path):
    section = client.post("/api/sections", json={"name": "S", "icon": "folder"}).json()
    doc = upload(client, section["id"], "RG", [("rg.jpg", image((60, 40)), "image/jpeg")])
    base = f"/api/documents/{doc['id']}/pages/{doc['pages'][0]['id']}"
    assert doc["pages"][0]["editable"]

    res = client.get(base + "/thumbnail")
    assert res.headers["content-type"] == "image/webp"
    assert "immutable" in res.headers["cache-control"]

    page = client.put(base + "/edits", json={"rotate": 90, "crop": {"x": 0, "y": 0, "w": 1, "h": 0.5}, "format": "png"}).json()
    assert (page["path"], page["edited"], page["rev"]) == ("S/RG.png", True, 1)
    assert size_of(client.get(base + "/content").content) == (40, 30)
    assert size_of(client.get(base + "/preview").content) == (60, 40)  # the upload, for the editor

    assert client.put(base + "/edits", json={"rotate": 45}).json() == {"detail": "invalid_edits"}
    assert client.post(base + "/restore").json()["path"] == "S/RG.jpg"


def test_document_pdf(client):
    section = client.post("/api/sections", json={"name": "S", "icon": "folder"}).json()
    doc = upload(client, section["id"], "RG", [("a.jpg", image(), "image/jpeg"), ("b.png", image(fmt="PNG"), "image/png")])
    res = client.get(f"/api/documents/{doc['id']}/pdf")
    assert res.headers["content-type"] == "application/pdf"
    assert "filename*=UTF-8''RG.pdf" in res.headers["content-disposition"]
    assert res.content.startswith(b"%PDF")


def test_search_and_expiry(client):
    section = client.post("/api/sections", json={"name": "S", "icon": "folder"}).json()
    res = client.post("/api/documents", data={"section": section["id"], "title": "Passaporte", "date": "2026-03-04",
                                              "expires": "2030-01-02"}, files=[("files", ("p.jpg", JPEG, "image/jpeg"))])
    doc = res.json()
    assert doc["expires"] == "2030-01-02"
    upload(client, section["id"], "Certidão", [("c.jpg", JPEG, "image/jpeg")])

    assert [d["title"] for d in client.get("/api/documents", params={"q": "PASSA"}).json()] == ["Passaporte"]
    assert [d["title"] for d in client.get("/api/documents", params={"q": "certidao", "section": section["id"]}).json()] == ["Certidão"]

    body = {"title": "Passaporte", "date": "2026-03-04", "section": section["id"], "tags": []}
    assert client.put(f"/api/documents/{doc['id']}", json=body).json()["expires"] is None
    res = client.put(f"/api/documents/{doc['id']}", json={**body, "expires": "soon"})
    assert res.json() == {"detail": "invalid_expiry"}


def test_pdf_download(client):
    section = client.post("/api/sections", json={"name": "S", "icon": "folder"}).json()
    a = upload(client, section["id"], "A", [("a.jpg", image(), "image/jpeg")])
    b = upload(client, section["id"], "B", [("b.png", image(fmt="PNG"), "image/png")])

    res = client.post("/api/documents/pdf", json={"ids": [a["id"], b["id"]]})
    assert res.headers["content-type"] == "application/zip"
    assert res.content[:2] == b"PK"

    res = client.post("/api/documents/pdf", json={"ids": [a["id"], b["id"]], "merge": True})
    assert res.headers["content-type"] == "application/pdf"
    assert "filename*=UTF-8''papelada.pdf" in res.headers["content-disposition"]

    notes = upload(client, section["id"], "Notes", [("n.txt", b"hi", "text/plain")])
    res = client.post("/api/documents/pdf", json={"ids": [a["id"], notes["id"]], "merge": True})
    assert (res.status_code, res.json()) == (400, {"detail": "not_exportable", "title": "Notes"})


def test_zip_download(client):
    section = client.post("/api/sections", json={"name": "S", "icon": "folder"}).json()
    doc = upload(client, section["id"], "Doc", [("a.jpg", JPEG, "image/jpeg")])
    res = client.post("/api/documents/download", json={"ids": [doc["id"]]})
    assert res.headers["content-type"] == "application/zip"
    assert res.content[:2] == b"PK"


def test_frontend_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "<title>Papelada</title>" in res.text
