#!/usr/bin/env python3
"""Servidor RyxHistory: base de datos, API de la app y agente del panel.

Un solo proceso en el servidor host atiende tres cosas:

  * La base de datos de la app (SQLite) y su API: registro, entrada, refresco de
    sesion, sincronizacion de notificaciones y borrado del historial.
  * El inicio de sesion con Discord (OAuth2) usando la direccion de este
    servidor como redirect_uri.
  * El agente que usa RyxHistory.exe para ver el estado y transferir archivos.

    python ryx_server.py --root C:\\ryx --port 8787 --discord-id 123 --discord-secret xyz

La clave del panel se pasa con --token, con RYX_TOKEN o se genera sola y queda en
ryx_token.txt. Las credenciales de Discord tambien valen por entorno
(RYX_DISCORD_ID / RYX_DISCORD_SECRET) o con --discord-id / --discord-secret.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import shutil
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = "RyxHistory"
VERSION = "1.1.0"
STARTED = time.time()
DB_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".db3", ".realm", ".mdb", ".accdb", ".sql", ".dump")
MAX_UPLOAD = 512 * 1024 * 1024
MAX_BATCH = 500
ACCESS_TTL = 30 * 24 * 3600
REFRESH_TTL = 180 * 24 * 3600
CODE_TTL = 120
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEEP_LINK = "ryxhistory://auth"


def _json_bytes(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _now() -> int:
    return int(time.time())


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256$120000${salt}${digest.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algorithm, iterations, salt, expected = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
    return hmac.compare_digest(digest.hex(), expected)


# ---------------------------------- base de datos ----------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    email       TEXT UNIQUE,
    name        TEXT,
    password    TEXT,
    discord_id  TEXT UNIQUE,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    access          TEXT PRIMARY KEY,
    refresh         TEXT UNIQUE NOT NULL,
    user_id         TEXT NOT NULL,
    created_at      INTEGER NOT NULL,
    access_expires  INTEGER NOT NULL,
    refresh_expires INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS notifications (
    user_id      TEXT NOT NULL,
    uuid         TEXT NOT NULL,
    package_name TEXT,
    app_name     TEXT,
    title        TEXT,
    text         TEXT,
    sub_text     TEXT,
    big_text     TEXT,
    category     TEXT,
    channel      TEXT,
    posted_at    INTEGER NOT NULL,
    created_at   INTEGER NOT NULL,
    PRIMARY KEY (user_id, uuid)
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, posted_at);
CREATE TABLE IF NOT EXISTS devices (
    user_id    TEXT NOT NULL,
    device_id  TEXT NOT NULL,
    model      TEXT,
    android    TEXT,
    last_seen  INTEGER NOT NULL,
    PRIMARY KEY (user_id, device_id)
);
CREATE TABLE IF NOT EXISTS login_codes (
    code       TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    expires    INTEGER NOT NULL
);
"""


class Store:
    """Acceso a la base de datos SQLite del servidor."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with self._connect() as con:
            con.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=20)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    # --- usuarios ---

    def user_by_email(self, email: str):
        with self.lock, self._connect() as con:
            row = con.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
            return dict(row) if row else None

    def user_by_discord(self, discord_id: str):
        with self.lock, self._connect() as con:
            row = con.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,)).fetchone()
            return dict(row) if row else None

    def user_by_id(self, user_id: str):
        with self.lock, self._connect() as con:
            row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def create_user(self, email: str | None, name: str | None, password: str | None,
                    discord_id: str | None) -> dict:
        user_id = uuid.uuid4().hex
        with self.lock, self._connect() as con:
            con.execute(
                "INSERT INTO users (id, email, name, password, discord_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, email.lower() if email else None, name or "", password, discord_id, _now()),
            )
        return self.user_by_id(user_id) or {}

    def link_discord(self, user_id: str, discord_id: str) -> None:
        with self.lock, self._connect() as con:
            con.execute("UPDATE users SET discord_id = ? WHERE id = ?", (discord_id, user_id))

    # --- sesiones ---

    def create_session(self, user_id: str) -> dict:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        stamp = _now()
        with self.lock, self._connect() as con:
            con.execute(
                "INSERT INTO sessions (access, refresh, user_id, created_at, access_expires, refresh_expires) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_hash_token(access), _hash_token(refresh), user_id, stamp,
                 stamp + ACCESS_TTL, stamp + REFRESH_TTL),
            )
        return {"access": access, "refresh": refresh}

    def user_by_access(self, token: str):
        with self.lock, self._connect() as con:
            row = con.execute(
                "SELECT u.id AS id, u.email AS email, u.name AS name, s.user_id AS user_id, "
                "s.access_expires AS access_expires FROM sessions s "
                "JOIN users u ON u.id = s.user_id WHERE s.access = ?",
                (_hash_token(token),),
            ).fetchone()
            if not row or row["access_expires"] < _now():
                return None
            return dict(row)

    def refresh_session(self, refresh: str):
        """Devuelve (usuario, sesion nueva) o None si el refresh no vale."""
        with self.lock, self._connect() as con:
            row = con.execute("SELECT * FROM sessions WHERE refresh = ?", (_hash_token(refresh),)).fetchone()
            if not row or row["refresh_expires"] < _now():
                return None
            user_id = row["user_id"]
            con.execute("DELETE FROM sessions WHERE refresh = ?", (_hash_token(refresh),))
        return user_id

    def drop_session(self, refresh: str) -> None:
        with self.lock, self._connect() as con:
            con.execute("DELETE FROM sessions WHERE refresh = ?", (_hash_token(refresh),))

    def drop_expired(self) -> None:
        with self.lock, self._connect() as con:
            stamp = _now()
            con.execute("DELETE FROM sessions WHERE refresh_expires < ?", (stamp,))
            con.execute("DELETE FROM login_codes WHERE expires < ?", (stamp,))

    # --- codigos de Discord ---

    def save_code(self, user_id: str) -> str:
        code = secrets.token_urlsafe(32)
        with self.lock, self._connect() as con:
            con.execute(
                "INSERT INTO login_codes (code, user_id, expires) VALUES (?, ?, ?)",
                (code, user_id, _now() + CODE_TTL),
            )
        return code

    def take_code(self, code: str) -> str | None:
        with self.lock, self._connect() as con:
            row = con.execute("SELECT * FROM login_codes WHERE code = ?", (code,)).fetchone()
            if not row:
                return None
            con.execute("DELETE FROM login_codes WHERE code = ?", (code,))
            if row["expires"] < _now():
                return None
            return row["user_id"]

    # --- notificaciones ---

    def save_notifications(self, user_id: str, device: dict, items: list) -> list:
        accepted: list = []
        stamp = _now()
        with self.lock, self._connect() as con:
            if device.get("id"):
                con.execute(
                    "INSERT INTO devices (user_id, device_id, model, android, last_seen) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(user_id, device_id) DO UPDATE SET "
                    "model = excluded.model, android = excluded.android, last_seen = excluded.last_seen",
                    (user_id, str(device.get("id"))[:120], str(device.get("model") or "")[:120],
                     str(device.get("android") or "")[:60], stamp),
                )
            for item in items:
                uuid_text = str(item.get("uuid") or "").strip()
                if not uuid_text:
                    continue
                con.execute(
                    "INSERT OR IGNORE INTO notifications (user_id, uuid, package_name, app_name, title, text, "
                    "sub_text, big_text, category, channel, posted_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id, uuid_text[:120], str(item.get("packageName") or "")[:200],
                        str(item.get("appName") or "")[:200], item.get("title"), item.get("text"),
                        item.get("subText"), item.get("bigText"), item.get("category"),
                        item.get("channelId"), int(item.get("postedAt") or stamp), stamp,
                    ),
                )
                accepted.append(uuid_text)
        return accepted

    def count_notifications(self, user_id: str) -> int:
        with self.lock, self._connect() as con:
            return int(con.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (user_id,)
            ).fetchone()[0])

    def delete_notifications(self, user_id: str) -> int:
        with self.lock, self._connect() as con:
            return int(con.execute(
                "DELETE FROM notifications WHERE user_id = ?", (user_id,)
            ).rowcount)

    def stats(self) -> dict:
        with self.lock, self._connect() as con:
            users = int(con.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            notes = int(con.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])
        try:
            size = self.path.stat().st_size
        except OSError:
            size = 0
        return {"path": str(self.path), "users": users, "notifications": notes, "size": size}

    def public_stats(self) -> dict:
        """Sin rutas: el panel no necesita saber donde esta el archivo."""
        data = self.stats()
        data.pop("path", None)
        return data

    # --- consultas del panel (registro de usuarios) ---

    def list_users(self) -> list:
        with self.lock, self._connect() as con:
            rows = con.execute(
                "SELECT u.id, u.name, u.email, u.discord_id, u.created_at, "
                "  (SELECT COUNT(*) FROM notifications n WHERE n.user_id = u.id) AS notifications, "
                "  (SELECT MAX(posted_at) FROM notifications n WHERE n.user_id = u.id) AS last_note, "
                "  (SELECT COUNT(*) FROM devices d WHERE d.user_id = u.id) AS devices, "
                "  (SELECT MAX(last_seen) FROM devices d WHERE d.user_id = u.id) AS last_seen "
                "FROM users u ORDER BY u.created_at DESC"
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["discord"] = bool(item.pop("discord_id", None))
            item["password"] = None
            result.append(item)
        return result

    def user_row(self, user_id: str):
        user = self.user_by_id(user_id)
        if not user:
            return None
        return {
            "id": user["id"],
            "name": user.get("name") or "",
            "email": user.get("email") or "",
            "discord": bool(user.get("discord_id")),
            "created_at": user.get("created_at") or 0,
        }

    def user_notifications(self, user_id: str, query: str = "", limit: int = 200) -> list:
        limit = max(1, min(int(limit or 200), 1000))
        query = (query or "").strip()
        sql = (
            "SELECT uuid, package_name, app_name, title, text, sub_text, big_text, category, "
            "channel, posted_at FROM notifications WHERE user_id = ?"
        )
        params: list = [user_id]
        if query:
            sql += (
                " AND (title LIKE ? OR text LIKE ? OR big_text LIKE ? OR app_name LIKE ?)"
            )
            like = f"%{query}%"
            params += [like, like, like, like]
        sql += " ORDER BY posted_at DESC LIMIT ?"
        params.append(limit)
        with self.lock, self._connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [
            {
                "uuid": row["uuid"],
                "package": row["package_name"],
                "app": row["app_name"],
                "title": row["title"],
                "text": row["text"],
                "sub": row["sub_text"],
                "big": row["big_text"],
                "category": row["category"],
                "channel": row["channel"],
                "posted_at": row["posted_at"],
            }
            for row in rows
        ]


class Limitador:
    """Limite de peticiones por IP para que nadie pueda probar claves en bucle."""

    def __init__(self):
        self.lock = threading.Lock()
        self.hits: dict = {}
        self.blocked: dict = {}

    def espera(self, key: str) -> int:
        with self.lock:
            return max(0, int(self.blocked.get(key, 0) - time.time()))

    def permite(self, key: str, limite: int, ventana: int, castigo: int = 0) -> bool:
        ahora = time.time()
        with self.lock:
            if self.blocked.get(key, 0) > ahora:
                return False
            marcas = [t for t in self.hits.get(key, []) if ahora - t < ventana]
            marcas.append(ahora)
            self.hits[key] = marcas
            if len(marcas) > limite:
                if castigo:
                    self.blocked[key] = ahora + castigo
                    self.hits.pop(key, None)
                return False
            return True


LIMITES = Limitador()
MAX_JSON = 4 * 1024 * 1024


def _databases(root: Path) -> list:
    found: list = []
    for path in sorted(root.rglob("*")):
        if len(found) >= 200:
            break
        try:
            if not path.is_file() or path.suffix.lower() not in DB_SUFFIXES:
                continue
            stat = path.stat()
        except OSError:
            continue
        found.append(
            {
                "name": path.name,
                "path": path.relative_to(root).as_posix(),
                "size": stat.st_size,
                "modified": int(stat.st_mtime),
            }
        )
    return found


def _disk() -> tuple:
    try:
        usage = shutil.disk_usage(str(Path.cwd()))
        return usage.total, usage.free
    except OSError:
        return 0, 0


# ----------------------------------- discord ---------------------------------

def discord_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify email",
        "state": state,
        "prompt": "consent",
    }
    return "https://discord.com/oauth2/authorize?" + urllib.parse.urlencode(params)


def _http_json(request) -> dict:
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def discord_token(code: str, redirect_uri: str, client_id: str, client_secret: str) -> dict:
    payload = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://discord.com/api/oauth2/token",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": f"{APP}/{VERSION}",
            "Accept": "application/json",
        },
    )
    return _http_json(request)


def discord_me(access_token: str) -> dict:
    request = urllib.request.Request(
        "https://discord.com/api/users/@me",
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": f"{APP}/{VERSION}",
            "Accept": "application/json",
        },
    )
    return _http_json(request)


# ----------------------------------- servidor --------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = f"{APP}/{VERSION}"
    root: Path = Path(".").resolve()
    token: str = ""
    node: str = socket.gethostname()
    store: Store | None = None
    discord_id: str = ""
    discord_secret: str = ""
    public_url: str = ""

    # ------------------------------ utilidades ------------------------------

    def log_message(self, fmt, *args):
        stamp = datetime.now().strftime("%H:%M:%S")
        sys.stdout.write(f"[{stamp}] {self.client_address[0]}  {fmt % args}\n")
        sys.stdout.flush()

    def _send(self, status: int, body: bytes, content_type: str = "application/json", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Server", APP)
        if "html" in content_type:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';",
            )
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status: int = 200):
        self._send(status, _json_bytes(payload), "application/json; charset=utf-8")

    def _error(self, status: int, message: str):
        self._json({"ok": False, "error": message}, status)

    def _html(self, title: str, message: str, status: int = 200):
        body = (
            "<!doctype html><meta charset='utf-8'>"
            "<title>" + title + "</title>"
            "<body style='background:#14100C;color:#FFF6DC;font-family:Segoe UI,sans-serif;"
            "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
            "<div style='text-align:center;max-width:520px'>"
            f"<h1 style='color:#FFC400;margin:0 0 12px'>{title}</h1><p>{message}</p></div></body>"
        )
        self._send(status, body.encode("utf-8"), "text/html; charset=utf-8")

    def _redirect(self, location: str):
        self._send(302, b"", "text/plain", {"Location": location})

    def _query(self, name: str, default: str = "") -> str:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return (query.get(name) or [default])[0]

    def _read_body(self) -> bytes:
        """Lee el cuerpo una sola vez (tambien al rechazar, para no cortar la conexion)."""
        if getattr(self, "_raw_body", None) is None:
            length = int(self.headers.get("Content-Length") or 0)
            self._raw_body = self.rfile.read(length) if length > 0 else b""
        return self._raw_body

    def _body_json(self) -> dict:
        raw = self._read_body()
        if not raw.strip():
            return {}
        data = json.loads(raw.decode("utf-8", "replace"))
        return data if isinstance(data, dict) else {}

    def _base_url(self) -> str:
        if self.public_url:
            return self.public_url.rstrip("/")
        host = self.headers.get("Host") or f"127.0.0.1:8787"
        return f"http://{host}"

    # --- claves ---

    def _token_ok(self) -> bool:
        # Solo por cabecera: en la URL quedaria escrita en los registros del proxy.
        given = self.headers.get("X-Ryx-Token") or ""
        return bool(self.token) and hmac.compare_digest(given, self.token)

    def _bearer_user(self):
        header = self.headers.get("Authorization") or ""
        if not header.lower().startswith("bearer "):
            return None
        return self.store.user_by_access(header[7:].strip())

    def _require_user(self):
        user = self._bearer_user()
        if user is None:
            self._error(401, "Sesion no valida o vencida")
        return user

    def _session_payload(self, user: dict) -> dict:
        session = self.store.create_session(user["id"])
        return {
            "ok": True,
            "accessToken": session["access"],
            "refreshToken": session["refresh"],
            "user": {"id": user["id"], "email": user.get("email") or "", "name": user.get("name") or ""},
        }

    # ------------------------------ rutas de app -----------------------------

    def _auth_register(self):
        ip = self.client_address[0]
        if not LIMITES.permite(f"reg:{ip}", 5, 900, castigo=300):
            return self._error(429, "Demasiadas cuentas desde esta conexion. Espera unos minutos.")
        data = self._body_json()
        email = str(data.get("email") or "").strip().lower()
        password = str(data.get("password") or "")
        name = str(data.get("name") or "").strip()
        if not EMAIL_RE.match(email):
            return self._error(400, "Escribe un correo valido")
        if len(password) < 6:
            return self._error(400, "La contrasena necesita 6 caracteres o mas")
        if self.store.user_by_email(email):
            return self._error(409, "Ya existe una cuenta con ese correo")
        user = self.store.create_user(email, name or email.split("@")[0], hash_password(password), None)
        self.log_message("registro nuevo: %s", email)
        return self._json(self._session_payload(user))

    def _auth_login(self):
        ip = self.client_address[0]
        if not LIMITES.permite(f"login:{ip}", 8, 300, castigo=600):
            espera = max(60, LIMITES.espera(f"login:{ip}"))
            return self._error(429, f"Demasiados intentos. Espera {espera // 60 + 1} minutos.")
        data = self._body_json()
        email = str(data.get("email") or "").strip().lower()
        password = str(data.get("password") or "")
        user = self.store.user_by_email(email)
        if not user or not check_password(password, user.get("password")):
            return self._error(401, "Correo o contrasena incorrectos")
        return self._json(self._session_payload(user))

    def _auth_refresh(self):
        data = self._body_json()
        refresh = str(data.get("refreshToken") or "")
        user_id = self.store.refresh_session(refresh) if refresh else None
        if not user_id:
            return self._error(401, "La sesion vencio: vuelve a entrar")
        user = self.store.user_by_id(user_id)
        if not user:
            return self._error(401, "La cuenta ya no existe")
        return self._json(self._session_payload(user))

    def _auth_logout(self):
        data = self._body_json()
        refresh = str(data.get("refreshToken") or "")
        if refresh:
            self.store.drop_session(refresh)
        return self._json({"ok": True})

    def _auth_discord_exchange(self):
        data = self._body_json()
        code = str(data.get("code") or "").strip()
        user_id = self.store.take_code(code) if code else None
        if not user_id:
            return self._error(400, "El codigo de Discord ya se uso o caduco")
        user = self.store.user_by_id(user_id)
        if not user:
            return self._error(400, "La cuenta ya no existe")
        return self._json(self._session_payload(user))

    def _sync(self):
        user = self._require_user()
        if user is None:
            return
        data = self._body_json()
        items = data.get("notifications") or []
        if not isinstance(items, list):
            return self._error(400, "Formato de notificaciones no valido")
        if len(items) > MAX_BATCH:
            return self._error(413, f"Maximo {MAX_BATCH} notificaciones por envio")
        accepted = self.store.save_notifications(user["id"], data.get("device") or {}, items)
        return self._json({"ok": True, "accepted": accepted})

    def _delete_history(self):
        user = self._require_user()
        if user is None:
            return
        deleted = self.store.delete_notifications(user["id"])
        self.log_message("historial borrado: %s notificaciones", deleted)
        return self._json({"ok": True, "deleted": deleted})

    # ------------------------------ discord ---

    def _discord_ready(self) -> bool:
        return bool(self.discord_id and self.discord_secret)

    def _discord_start(self):
        if not self._discord_ready():
            return self._html(
                "Discord sin configurar",
                "Falta la aplicacion de Discord en el servidor. Arrancalo con "
                "--discord-id y --discord-secret (o las variables RYX_DISCORD_ID y "
                "RYX_DISCORD_SECRET) y vuelve a intentarlo.",
                503,
            )
        app_state = self._query("app_state") or self._query("state")
        redirect_uri = self._base_url() + "/auth/discord/callback"
        self._redirect(discord_authorize_url(self.discord_id, redirect_uri, app_state))

    def _discord_callback(self):
        app_state = self._query("state")
        error = self._query("error")
        if error:
            self._redirect(f"{DEEP_LINK}?error={urllib.parse.quote(error)}&state={urllib.parse.quote(app_state)}")
            return
        code = self._query("code")
        if not code:
            if not self._discord_ready():
                return self._html("Discord sin configurar", "El servidor no tiene credenciales de Discord.", 503)
            return self._html("Falta el codigo", "Discord no devolvio un codigo de autorizacion.", 400)
        if not self._discord_ready():
            return self._html("Discord sin configurar", "El servidor no tiene credenciales de Discord.", 503)
        redirect_uri = self._base_url() + "/auth/discord/callback"
        try:
            token = discord_token(code, redirect_uri, self.discord_id, self.discord_secret)
            profile = discord_me(str(token.get("access_token") or ""))
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:200]
            self.log_message("discord rechazo el canje: %s %s", err.code, detail)
            return self._html(
                "Discord rechazo la entrada",
                "Revisa que el redirect_uri registrado sea exactamente "
                f"<b>{redirect_uri}</b> y que el client secret sea correcto.",
                400,
            )
        except Exception as err:  # red caida
            self.log_message("discord no respondio: %s", err)
            return self._html("Discord no respondio", "Intentalo de nuevo en unos segundos.", 502)

        discord_id = str(profile.get("id") or "")
        if not discord_id:
            return self._html("Discord no devolvio el usuario", "Intentalo de nuevo.", 400)
        username = str(profile.get("global_name") or profile.get("username") or "Discord")
        email = str(profile.get("email") or "").strip().lower()

        user = self.store.user_by_discord(discord_id)
        if not user and email:
            existing = self.store.user_by_email(email)
            if existing:
                self.store.link_discord(existing["id"], discord_id)
                user = self.store.user_by_id(existing["id"])
        if not user:
            user = self.store.create_user(email or None, username, None, discord_id)
            self.log_message("cuenta nueva por Discord: %s", username)
        one_time = self.store.save_code(user["id"])
        target = (
            f"{DEEP_LINK}?code={urllib.parse.quote(one_time)}"
            f"&state={urllib.parse.quote(app_state)}"
        )
        self.log_message("entrada Discord ok: %s", username)
        link = target.replace("&", "&amp;")
        body = (
            "<!doctype html><meta charset='utf-8'><title>RyxHistory</title>"
            "<body style='background:#14100C;color:#FFF6DC;font-family:Segoe UI,sans-serif;"
            "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
            "<div style='text-align:center;max-width:520px'>"
            "<h1 style='color:#FFC400;margin:0 0 12px'>Listo</h1>"
            "<p>Vuelve a RyxHistory. Si no se abre sola, toca aquí:</p>"
            f"<p><a style='color:#FFC400;font-size:18px' href='{link}'>Abrir RyxHistory</a></p>"
            "<script>location.replace(" + json.dumps(target) + ")</script>"
            "</div></body>"
        )
        self._send(302, body.encode("utf-8"), "text/html; charset=utf-8", {"Location": target})

    # ------------------------------ rutas de archivos -------------------------

    def _target(self, raw: str) -> Path:
        clean = urllib.parse.unquote(raw or "").strip().replace("\\", "/").lstrip("/")
        target = (self.root / clean).resolve()
        if target != self.root and self.root not in target.parents:
            raise PermissionError("Ruta fuera de la carpeta del servidor")
        return target

    def _relative(self, target: Path) -> str:
        try:
            rel = target.relative_to(self.root).as_posix()
        except ValueError:
            return ""
        return "" if rel == "." else rel

    def _ping(self):
        self._json({"ok": True, "app": APP, "node": self.node, "version": VERSION})

    def _info(self):
        total, free = _disk()
        # Sin rutas absolutas ni nombres de carpeta: el panel solo necesita numeros.
        databases = [
            {"name": item["name"], "size": item["size"], "modified": item["modified"]}
            for item in _databases(self.root)
        ]
        payload = {
            "ok": True,
            "app": APP,
            "node": self.node,
            "version": VERSION,
            "system": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "uptime": int(time.time() - STARTED),
            "disk_total": total,
            "disk_free": free,
            "databases": databases,
            "database": self.store.public_stats() if self.store else {},
            "discord": bool(self.discord_id and self.discord_secret),
        }
        self._json(payload)

    # --- registro de usuarios (solo con la clave del panel) ---

    def _admin_users(self):
        users = self.store.list_users()
        self._json({"ok": True, "total": len(users), "users": users})

    def _admin_notifications(self):
        user_id = self._query("user")
        user = self.store.user_row(user_id) if user_id else None
        if not user:
            self._error(404, "Ese usuario no existe")
            return
        try:
            limite = int(self._query("limit") or 200)
        except ValueError:
            limite = 200
        items = self.store.user_notifications(user_id, self._query("q"), limite)
        self._json({"ok": True, "user": user, "count": len(items), "notifications": items})

    def _file_route(self, route: str, post: bool) -> bool:
        if not self._token_ok():
            self._error(401, "Clave del servidor incorrecta o ausente")
            return True
        if route == "/api/info" and not post:
            self._info()
            return True
        if route == "/api/admin/users" and not post:
            self._admin_users()
            return True
        if route == "/api/admin/notifications" and not post:
            self._admin_notifications()
            return True
        if route == "/api/list" and not post:
            target = self._target(self._query("path"))
            if not target.exists():
                self._error(404, "Esa carpeta no existe")
                return True
            if not target.is_dir():
                self._error(400, "No es una carpeta")
                return True
            entries = []
            for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                try:
                    stat = child.stat()
                except OSError:
                    continue
                entries.append(
                    {
                        "name": child.name,
                        "dir": child.is_dir(),
                        "size": stat.st_size,
                        "modified": int(stat.st_mtime),
                    }
                )
            self._json({"ok": True, "path": self._relative(target), "entries": entries})
            return True
        if route == "/api/download" and not post:
            target = self._target(self._query("path"))
            if not target.is_file():
                self._error(404, "Ese archivo no existe")
                return True
            data = target.read_bytes()
            self._send(
                200, data, "application/octet-stream",
                {"Content-Disposition": f'attachment; filename="{target.name}"'},
            )
            return True
        if route == "/api/upload" and post:
            target = self._target(self._query("path"))
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                self._error(400, "El archivo llego vacio")
                return True
            if length > MAX_UPLOAD:
                self._error(413, "El archivo es demasiado grande")
                return True
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".ryx-part")
            remaining = length
            with temp.open("wb") as handle:
                while remaining > 0:
                    chunk = self.rfile.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    handle.write(chunk)
                    remaining -= len(chunk)
            temp.replace(target)
            self._json({"ok": True, "path": self._relative(target), "size": target.stat().st_size})
            return True
        if route == "/api/mkdir" and post:
            target = self._target(self._query("path"))
            target.mkdir(parents=True, exist_ok=True)
            self._json({"ok": True, "path": self._relative(target)})
            return True
        if route == "/api/delete" and post:
            target = self._target(self._query("path"))
            if target == self.root:
                self._error(400, "No se puede borrar la carpeta del servidor")
                return True
            if not target.exists():
                self._error(404, "Ese archivo no existe")
                return True
            if target.is_dir():
                if self._query("recursive") == "1":
                    shutil.rmtree(target)
                else:
                    target.rmdir()
            else:
                target.unlink()
            self._json({"ok": True})
            return True
        if route == "/api/rename" and post:
            source = self._target(self._query("path"))
            destination = self._target(self._query("to"))
            if not source.exists():
                self._error(404, "Ese archivo no existe")
                return True
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
            self._json({"ok": True, "path": self._relative(destination)})
            return True
        self._error(404, "Ruta desconocida")
        return True

    def _limpio(self, text) -> str:
        """Nunca devolver rutas del disco en un mensaje de error."""
        return str(text).replace(str(self.root), "…")

    def _dispatch(self, post: bool) -> None:
        route = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        ip = self.client_address[0]
        if not LIMITES.permite(f"all:{ip}", 300, 60, castigo=60):
            espera = LIMITES.espera(f"all:{ip}") or 60
            self._error(429, f"Demasiadas peticiones. Espera {espera} segundos.")
            return
        if route in ("/api/ping", "/ping", "/"):
            self._ping()
            return
        if route == "/auth/discord/start" and not post:
            self._discord_start()
            return
        if route == "/auth/discord/callback" and not post:
            self._discord_callback()
            return
        if self.store is None:
            self._error(503, "Base de datos no disponible")
            return
        app_routes = {
            "/api/auth/register": self._auth_register,
            "/api/auth/login": self._auth_login,
            "/api/auth/refresh": self._auth_refresh,
            "/api/auth/logout": self._auth_logout,
            "/api/auth/discord/exchange": self._auth_discord_exchange,
            "/api/sync": self._sync,
        }
        if post and route in app_routes:
            app_routes[route]()
            return
        if self.command == "DELETE" and route == "/api/me/history":
            self._delete_history()
            return
        self._file_route(route, post)

    # ------------------------------- peticiones ------------------------------

    def do_GET(self):  # noqa: N802
        try:
            self._dispatch(post=False)
        except PermissionError as error:
            self._error(403, self._limpio(error))
        except FileNotFoundError:
            self._error(404, "Ese archivo no existe")
        except Exception as error:  # pragma: no cover
            self.log_message("error interno: %s", error)
            self._error(500, "Error interno del servidor")

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_POST(self):  # noqa: N802
        route = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        try:
            # Las subidas se leen en streaming; el resto se lee aqui para poder
            # responder 401/400 sin dejar el cuerpo sin consumir.
            length = int(self.headers.get("Content-Length") or 0)
            if route != "/api/upload" and length > MAX_JSON:
                self.close_connection = True
                self._error(413, "La peticion es demasiado grande")
                return
            if route != "/api/upload":
                self._read_body()
            self._dispatch(post=True)
        except PermissionError as error:
            self._error(403, self._limpio(error))
        except json.JSONDecodeError:
            self._error(400, "El cuerpo de la peticion no es JSON valido")
        except OSError as error:
            self.log_message("error de disco: %s", error)
            self._error(409, self._limpio(f"{type(error).__name__}: {error}"))
        except Exception as error:  # pragma: no cover
            self.log_message("error interno: %s", error)
            self._error(500, "Error interno del servidor")

    def do_DELETE(self):  # noqa: N802
        try:
            self._dispatch(post=False)
        except Exception as error:  # pragma: no cover
            self.log_message("error interno: %s", error)
            self._error(500, "Error interno del servidor")


def _load_token(value: str, folder: Path) -> str:
    if value:
        return value.strip()
    if os.environ.get("RYX_TOKEN"):
        return os.environ["RYX_TOKEN"].strip()
    stored = folder / "ryx_token.txt"
    if stored.exists():
        text = stored.read_text(encoding="utf-8").strip()
        if text:
            return text
    token = secrets.token_urlsafe(12)
    stored.write_text(token + "\n", encoding="utf-8")
    return token


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Servidor {APP}: base de datos y API")
    parser.add_argument("--root", default=".", help="Carpeta del servidor (base de datos y archivos)")
    parser.add_argument("--host", default="0.0.0.0", help="Interfaz de red (por defecto todas)")
    parser.add_argument("--port", type=int, default=8787, help="Puerto (por defecto 8787)")
    parser.add_argument("--token", default="", help="Clave que usara el panel RyxHistory.exe")
    parser.add_argument("--node", default=socket.gethostname(), help="Nombre visible de este servidor")
    parser.add_argument("--db", default="", help="Archivo SQLite (por defecto <root>/ryx.db)")
    parser.add_argument("--discord-id", default=os.environ.get("RYX_DISCORD_ID", ""),
                        help="Client ID de la aplicacion de Discord")
    parser.add_argument("--discord-secret", default=os.environ.get("RYX_DISCORD_SECRET", ""),
                        help="Client Secret de la aplicacion de Discord")
    parser.add_argument("--public-url", default=os.environ.get("RYX_PUBLIC_URL", ""),
                        help="URL publica del servidor (por defecto http://<Host>)")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.db).expanduser().resolve() if args.db else root / "ryx.db"

    Handler.root = root
    Handler.token = _load_token(args.token, Path(__file__).resolve().parent)
    Handler.node = args.node
    Handler.store = Store(db_path)
    Handler.store.drop_expired()
    Handler.discord_id = args.discord_id.strip()
    Handler.discord_secret = args.discord_secret.strip()
    Handler.public_url = args.public_url.strip()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    base = Handler.public_url or f"http://{args.host}:{args.port}"
    print(f"=== {APP} · servidor {Handler.node} ===")
    print(f"Carpeta:   {root}")
    print(f"Base de datos: {db_path}")
    print(f"Escuchando en http://{args.host}:{args.port}")
    print(f"Clave del panel: {Handler.token}")
    if Handler.discord_id and Handler.discord_secret:
        print(f"Discord:   activo (client {Handler.discord_id})")
        print(f"Redirect URI que debes registrar: {base.rstrip('/')}/auth/discord/callback")
    else:
        print("Discord:   sin configurar (--discord-id / --discord-secret)")
    print("Deja esta ventana abierta. Ctrl+C para parar.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
