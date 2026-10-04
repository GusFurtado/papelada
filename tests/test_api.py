import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import Library

from .conftest import JPEG, tree


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


def test_errors_carry_a_code_for_the_frontend(client):
    client.post("/api/sections", json={"name": "Car", "icon": "car"})
    res = client.post("/api/sections", json={"name": "car", "icon": "car"})
    assert res.status_code == 409
    assert res.json() == {"detail": "section_exists"}
    assert client.get("/api/documents/nope/pages/nope/content").json() == {"detail": "document_not_found"}


def test_encryption_settings(client, tmp_path):
    assert client.get("/api/settings").json() == {"encrypted": False, "encryption_available": True}
    section = client.post("/api/sections", json={"name": "S", "icon": "folder"}).json()
    upload(client, section["id"], "Doc", [("a.jpg", JPEG, "image/jpeg")])

    res = client.put("/api/settings", json={"encrypted": True}).json()
    assert res == {"encrypted": True, "encryption_available": True, "converted": 1}
    assert tree(tmp_path) == []


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
