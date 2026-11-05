"""TailChat: one private, persistent workshop room. Run with `python app.py`."""
from gevent import monkey
monkey.patch_all()  # Patch before networking imports; one gevent worker owns presence.

import hmac
import os
import re
import secrets
import sqlite3
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, session
from flask_socketio import SocketIO, emit
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
MAX_FILE = 10 * 1024 * 1024
MAX_MESSAGE = 2000
ALLOWED = {"txt", "csv", "pdf", "png", "jpg", "jpeg", "gif", "webp"}


def now():
    return datetime.now(timezone.utc).isoformat()


def create_app(data_dir=None):
    """Factory keeps test data separate from workshop messages."""
    app = Flask(__name__)
    root = Path(data_dir or os.environ.get("TAILCHAT_DATA_DIR", BASE / "instance"))
    root.mkdir(parents=True, exist_ok=True)
    uploads = root / "uploads"
    uploads.mkdir(exist_ok=True)
    key_file = root / "secret.key"
    if not key_file.exists():
        key_file.write_bytes(secrets.token_bytes(32))
    app.config.update(SECRET_KEY=key_file.read_bytes(), MAX_CONTENT_LENGTH=MAX_FILE + 65536,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      DEBUG=False, DATABASE=str(root / "chat.sqlite3"))
    sio = SocketIO(app, async_mode="gevent", max_http_buffer_size=32768,
                   ping_interval=10, ping_timeout=15, manage_session=False,
                   logger=False, engineio_logger=False)
    connections = {}  # sid -> {id, name}; several tabs may share one identity.
    typing = {}  # sid -> expiry; stale indicators expire on every client too.
    limits = defaultdict(deque)

    @contextmanager
    def db():
        conn = sqlite3.connect(app.config["DATABASE"], timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    with db() as conn:
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS people (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, last_seen TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
                name TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                client_id TEXT NOT NULL, file_key TEXT, filename TEXT, file_size INTEGER,
                UNIQUE(user_id, client_id));
        """)

    def limited(key, maximum, seconds):
        stamp = time.monotonic()
        bucket = limits[key]
        while bucket and bucket[0] < stamp - seconds:
            bucket.popleft()
        if len(bucket) >= maximum:
            return True
        bucket.append(stamp)
        # Remove old rate-limit entries to keep a long-running room bounded.
        if len(limits) > 1000:
            for old in list(limits):
                if not limits[old] or limits[old][-1] < stamp - 120:
                    del limits[old]
        return False

    def message(row):
        result = dict(row)
        key = result.pop("file_key")
        result["attachment"] = ({"url": f"/files/{key}", "name": result.pop("filename"),
                                 "size": result.pop("file_size")} if key else None)
        result.pop("filename", None)
        result.pop("file_size", None)
        return result

    def history():
        with db() as conn:
            rows = conn.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 100").fetchall()
        return [message(row) for row in reversed(rows)]

    def people():
        active = {p["id"] for p in connections.values()}
        with db() as conn:
            rows = conn.execute("SELECT * FROM people ORDER BY last_seen DESC LIMIT 100").fetchall()
        return [dict(row, online=row["id"] in active) for row in rows]

    def broadcast_people():
        sio.emit("participants", people())

    def broadcast_typing():
        stamp = time.monotonic()
        users = {connections[sid]["id"]: connections[sid] for sid, expiry in typing.items()
                 if sid in connections and expiry > stamp}
        sio.emit("typing", list(users.values()))

    def csrf_ok():
        token = session.get("csrf", "")
        return bool(token) and hmac.compare_digest(token, request.headers.get("X-CSRF-Token", ""))

    @app.before_request
    def same_origin():
        # Socket.IO independently enforces the same-origin policy on its endpoint.
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                return jsonify(error="This request must come from TailChat."), 403

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self' ws: wss:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if request.path.startswith(("/api/", "/files/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        detail = "Files must be 10 MB or smaller." if error.code == 413 else error.description
        return jsonify(error=detail), error.code

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception("Request failed")
        return jsonify(error="The server could not finish that request. Please try again."), 500

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/status")
    def status():
        return jsonify(ok=True, team="Workshop team", online=len({p["id"] for p in connections.values()}))

    @app.post("/api/join")
    def join():
        if limited(("join", request.remote_addr), 30, 60):
            return jsonify(error="Too many join attempts. Wait a minute."), 429
        data = request.get_json(silent=True)
        name = data.get("name") if isinstance(data, dict) else None
        if not isinstance(name, str):
            return jsonify(error="Enter a display name."), 400
        name = " ".join(name.split())
        if not 1 <= len(name) <= 32 or any(ord(c) < 32 or ord(c) == 127 for c in name):
            return jsonify(error="Use a name between 1 and 32 characters, without control characters."), 400
        user_id = session.get("user_id", str(uuid.uuid4()))
        if any(p["id"] == user_id and p["name"] != name for p in connections.values()):
            return jsonify(error="Close your other TailChat tabs before changing your name."), 409
        session.update(user_id=user_id, name=name, csrf=session.get("csrf", secrets.token_hex(24)))
        with db() as conn:
            conn.execute("INSERT INTO people VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, last_seen=excluded.last_seen",
                         (user_id, name, now()))
        return jsonify(id=user_id, name=name, csrf=session["csrf"])

    @sio.on("connect")
    def connect(auth=None):
        if "user_id" not in session:
            return False
        user = {"id": session["user_id"], "name": session["name"]}
        first = not any(p["id"] == user["id"] for p in connections.values())
        connections[request.sid] = user
        emit("snapshot", {"messages": history(), "participants": people(), "you": user})
        broadcast_people()
        if first:
            sio.emit("system", {"text": f'{user["name"]} joined the room', "created_at": now()})

    @sio.on("disconnect")
    def disconnect(reason=None):
        user = connections.pop(request.sid, None)
        typing.pop(request.sid, None)
        broadcast_typing()
        if user and not any(p["id"] == user["id"] for p in connections.values()):
            with db() as conn:
                conn.execute("UPDATE people SET last_seen=? WHERE id=?", (now(), user["id"]))
            sio.emit("system", {"text": f'{user["name"]} left the room', "created_at": now()})
        broadcast_people()

    @sio.on("typing")
    def on_typing(data):
        if request.sid not in connections:
            return {"error": "Join the room first."}
        if limited(("typing", request.sid), 10, 5):
            return {"ok": True}
        if isinstance(data, dict) and data.get("active") is True:
            typing[request.sid] = time.monotonic() + 4
        else:
            typing.pop(request.sid, None)
        broadcast_typing()
        return {"ok": True}

    @sio.on("message")
    def on_message(data):
        user = connections.get(request.sid)
        if not user:
            return {"error": "Join the room first."}
        if not isinstance(data, dict) or not isinstance(data.get("text"), str):
            return {"error": "Send a text message."}
        text = data["text"].strip()
        client_id = data.get("client_id")
        if not text or len(text) > MAX_MESSAGE or any(ord(c) < 32 and c not in "\n\t" for c in text):
            return {"error": "Messages must contain 1–2000 characters without control characters."}
        if not isinstance(client_id, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", client_id):
            return {"error": "Invalid message identifier."}
        with db() as conn:
            old = conn.execute("SELECT * FROM messages WHERE user_id=? AND client_id=?", (user["id"], client_id)).fetchone()
            if old:
                return {"ok": True, "message": message(old)}
            if limited(("message", user["id"]), 30, 10):
                return {"error": "Sending too quickly. Wait a few seconds."}
            cursor = conn.execute("INSERT INTO messages(user_id,name,text,created_at,client_id) VALUES (?,?,?,?,?)",
                                  (user["id"], user["name"], text, now(), client_id))
            row = conn.execute("SELECT * FROM messages WHERE id=?", (cursor.lastrowid,)).fetchone()
        result = message(row)
        typing.pop(request.sid, None)
        broadcast_typing()
        sio.emit("message", result)
        return {"ok": True, "message": result}

    @sio.on_error_default
    def socket_error(error):
        app.logger.exception("Socket event failed")
        return {"error": "The server could not save your message. Please try again."}

    @app.post("/api/upload")
    def upload():
        if "user_id" not in session or not csrf_ok():
            return jsonify(error="Join the room again before sharing a file."), 403
        if limited(("upload", session["user_id"]), 5, 60):
            return jsonify(error="You can share five files per minute. Please wait."), 429
        file = request.files.get("file")
        if not file or not file.filename:
            return jsonify(error="Choose a file to upload."), 400
        filename = secure_filename(file.filename)[:160]
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        content = file.read(MAX_FILE + 1)
        if len(content) > MAX_FILE:
            return jsonify(error="Files must be 10 MB or smaller."), 413
        if ext not in ALLOWED or not valid_file(ext, content):
            return jsonify(error="Allowed: UTF-8 TXT/CSV, PDF, PNG, JPG, GIF and WebP. The content must match its type."), 400
        key = uuid.uuid4().hex
        path = uploads / key
        try:
            path.write_bytes(content)
            with db() as conn:
                cursor = conn.execute("INSERT INTO messages(user_id,name,created_at,client_id,file_key,filename,file_size) VALUES (?,?,?,?,?,?,?)",
                                      (session["user_id"], session["name"], now(), key, key, filename, len(content)))
                row = conn.execute("SELECT * FROM messages WHERE id=?", (cursor.lastrowid,)).fetchone()
        except Exception:
            path.unlink(missing_ok=True)
            raise
        result = message(row)
        sio.emit("message", result)
        return jsonify(ok=True, message=result), 201

    @app.get("/files/<key>")
    def download(key):
        if "user_id" not in session:
            return jsonify(error="Join TailChat before downloading files."), 403
        if not re.fullmatch(r"[a-f0-9]{32}", key):
            return jsonify(error="File not found."), 404
        with db() as conn:
            row = conn.execute("SELECT filename FROM messages WHERE file_key=?", (key,)).fetchone()
        if not row or not (uploads / key).is_file():
            return jsonify(error="File not found."), 404
        return send_file(uploads / key, as_attachment=True, download_name=row["filename"],
                         mimetype="application/octet-stream", conditional=True)

    return app, sio


def valid_file(ext, content):
    """Conservative type checks, not antivirus. Downloads are always attachments."""
    if not content or content.startswith((b"MZ", b"\x7fELF", b"#!")):
        return False
    if ext in {"txt", "csv"}:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return False
        return not any(ord(c) < 32 and c not in "\r\n\t" for c in text)
    if ext == "pdf":
        return content.startswith(b"%PDF-") and b"%%EOF" in content[-1024:]
    if ext == "png":
        return content.startswith(b"\x89PNG\r\n\x1a\n") and b"IHDR" in content[:32] and b"IEND" in content[-16:]
    if ext in {"jpg", "jpeg"}:
        return content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9")
    if ext == "gif":
        return content.startswith((b"GIF87a", b"GIF89a")) and content.endswith(b";")
    return len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"


if __name__ == "__main__":
    app, socketio = create_app()
    port = int(os.environ.get("PORT", "5000"))
    print(f"\nTailChat | http://localhost:{port}\nListening on 0.0.0.0:{port}")
    print(f"Run 'tailscale ip -4' and share http://YOUR_TAILSCALE_IP:{port}")
    print("Trusted workshop participants only. Press Ctrl+C to stop.\n", flush=True)
    socketio.run(app, host="0.0.0.0", port=port, debug=False, use_reloader=False, log_output=False)
