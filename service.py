import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import Flask, Response, g, request
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, generate_latest

import release

GROUP = re.compile(r"SE-[0-9]{2}")


def create_app():
    app = Flask(__name__)
    database = Path(os.getenv("SUBMIT_DB", "submissions.sqlite"))
    database.parent.mkdir(parents=True, exist_ok=True)
    fail_confirmation = os.getenv("FAIL_CONFIRMATION", "0") == "1"
    registry = CollectorRegistry()
    counts = Counter(
        "submission_responses_total",
        "Completed POST /submissions requests",
        ("version", "status"),
        registry=registry,
    )

    def connect():
        connection = sqlite3.connect(database, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    with closing(connect()) as db, db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY,
                group_code TEXT NOT NULL,
                submission_key TEXT NOT NULL UNIQUE
            )
            """
        )

    def audit(event, status):
        entry = {
            "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "version": release.VERSION,
            "request_id": g.request_id,
            "event": event,
            "status": status,
        }
        if getattr(g, "submission_id", None) is not None:
            entry["submission_id"] = g.submission_id
        print(json.dumps(entry, separators=(",", ":")), flush=True)

    @app.before_request
    def assign_request_id():
        g.request_id = uuid4().hex

    @app.after_request
    def record_response(response):
        response.headers["X-Request-Id"] = g.request_id
        if request.method == "POST" and request.path == "/submissions":
            counts.labels(release.VERSION, str(response.status_code)).inc()
            audit("submission_response", response.status_code)
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "version": release.VERSION}

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)

    @app.post("/submissions")
    def submit():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return {"error": "JSON object required"}, 400
        code, key = body.get("group_code"), body.get("submission_key")
        if not isinstance(code, str) or GROUP.fullmatch(code) is None:
            return {"error": "group_code must match SE-NN"}, 400
        if not isinstance(key, str) or not key.strip() or len(key) > 64:
            return {"error": "invalid submission_key"}, 400

        with closing(connect()) as db, db:
            created = db.execute(
                "INSERT INTO submissions (group_code, submission_key) VALUES (?, ?) "
                "ON CONFLICT(submission_key) DO NOTHING",
                (code, key),
            ).rowcount == 1
            entry = db.execute(
                "SELECT id, group_code FROM submissions WHERE submission_key = ?",
                (key,),
            ).fetchone()

        g.submission_id = entry["id"]
        if entry["group_code"] != code:
            return {"error": "submission_key belongs to another group"}, 409
        if not created:
            return {"id": entry["id"]}, 200

        audit("submission_saved", 201)
        status = release.after_save(fail_confirmation, audit)
        if status == 503:
            return {"id": entry["id"], "error": "confirmation unavailable"}, status
        return {"id": entry["id"]}, status

    @app.get("/submissions/<int:submission_id>")
    def lookup(submission_id):
        with closing(connect()) as db:
            entry = db.execute(
                "SELECT id, group_code, submission_key FROM submissions WHERE id = ?",
                (submission_id,),
            ).fetchone()
        if entry is None:
            return {"error": "submission not found"}, 404
        return dict(entry)

    return app
