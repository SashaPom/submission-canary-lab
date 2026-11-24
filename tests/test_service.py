import sqlite3

import pytest

import release
from service import create_app


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    path = tmp_path / "submissions.sqlite"
    monkeypatch.setenv("SUBMIT_DB", str(path))
    monkeypatch.setenv("FAIL_CONFIRMATION", "0")
    return path


@pytest.mark.parametrize(
    ("group_code", "expected"),
    [("SE-01", 201), ("SE-99", 201), ("SE-1", 400), ("SE-001", 400), ("se-01", 400), ("SE-٠١", 400), (3, 400)],
)
def test_group_code(isolated_db, group_code, expected):
    client = create_app().test_client()
    response = client.post("/submissions", json={"group_code": group_code, "submission_key": "case"})
    assert response.status_code == expected
    with sqlite3.connect(isolated_db) as db:
        assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == int(expected == 201)


def test_create_read_and_replay(isolated_db):
    client = create_app().test_client()
    payload = {"group_code": "SE-20", "submission_key": "once"}
    first = client.post("/submissions", json=payload)
    number = first.json["id"]
    assert first.status_code == 201
    assert client.get(f"/submissions/{number}").json == {"id": number, **payload}
    repeated = client.post("/submissions", json=payload)
    assert repeated.status_code == 200 and repeated.json["id"] == number
    with sqlite3.connect(isolated_db) as db:
        assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 1


def test_health_reports_release(isolated_db):
    response = create_app().test_client().get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "version": release.VERSION}
