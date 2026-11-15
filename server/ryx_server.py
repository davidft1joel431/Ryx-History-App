#!/usr/bin/env python3
"""Agente RyxHistory para los servidores.

Los servidores solo guardan la base de datos, asi que este agente expone una
API minima para que el panel RyxHistory.exe consulte el estado del servidor y
transfiera archivos (subir, descargar, carpetas, borrar).

    python ryx_server.py --root C:\\ryx --port 8787 --token MI_CLAVE

La clave se puede pasar con --token, con la variable RYX_TOKEN o se genera sola
y queda guardada en ryx_token.txt (junto a este archivo).
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import platform
import secrets
import shutil
import socket
import sys
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = "RyxHistory"
VERSION = "1.0.0"
STARTED = time.time()
DB_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".db3", ".realm", ".mdb", ".accdb", ".sql", ".dump")
MAX_UPLOAD = 512 * 1024 * 1024


def _json_bytes(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


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


class Handler(BaseHTTPRequestHandler):
    server_version = f"{APP}-node/{VERSION}"
    root: Path = Path(".").resolve()
    token: str = ""
    node: str = socket.gethostname()

    # ------------------------------ utilidades ------------------------------

    def log_message(self, fmt, *args):
        stamp = datetime.now().strftime("%H:%M:%S")
        sys.stdout.write(f"[{stamp}] {self.client_address[0]}  {fmt % args}\n")
        sys.stdout.flush()

    def _send(self, status: int, body: bytes, content_type: str = "application/json", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status: int = 200):
        self._send(status, _json_bytes(payload))

    def _error(self, status: int, message: str):
        self._json({"ok": False, "error": message}, status)

    def _token_ok(self) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        given = self.headers.get("X-Ryx-Token") or (query.get("token") or [""])[0]
        return bool(self.token) and hmac.compare_digest(given, self.token)

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

    def _query(self, name: str, default: str = "") -> str:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return (query.get(name) or [default])[0]

    # ------------------------------- peticiones -----------------------------

    def do_GET(self):  # noqa: N802
        route = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if route in ("/api/ping", "/ping", "/"):
            self._json({"ok": True, "app": APP, "node": self.node, "version": VERSION})
            return
        if not self._token_ok():
            self._error(401, "Clave del servidor incorrecta o ausente")
            return
        try:
            if route == "/api/info":
                total, free = _disk()
                self._json(
                    {
                        "ok": True,
                        "app": APP,
                        "node": self.node,
                        "version": VERSION,
                        "system": f"{platform.system()} {platform.release()}",
                        "python": platform.python_version(),
                        "uptime": int(time.time() - STARTED),
                        "root": str(self.root),
                        "disk_total": total,
                        "disk_free": free,
                        "databases": _databases(self.root),
                    }
                )
                return
            if route == "/api/list":
                target = self._target(self._query("path"))
                if not target.exists():
                    self._error(404, "Esa carpeta no existe")
                    return
                if not target.is_dir():
                    self._error(400, "No es una carpeta")
                    return
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
                return
            if route == "/api/download":
                target = self._target(self._query("path"))
                if not target.is_file():
                    self._error(404, "Ese archivo no existe")
                    return
                data = target.read_bytes()
                self._send(
                    200,
                    data,
                    "application/octet-stream",
                    {"Content-Disposition": f'attachment; filename="{target.name}"'},
                )
                return
            self._error(404, "Ruta desconocida")
        except PermissionError as error:
            self._error(403, str(error))
        except Exception as error:  # pragma: no cover - red o disco
            self._error(500, f"{type(error).__name__}: {error}")

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_POST(self):  # noqa: N802
        route = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if route == "/api/ping":
            self._json({"ok": True, "app": APP, "node": self.node, "version": VERSION})
            return
        if not self._token_ok():
            self._error(401, "Clave del servidor incorrecta o ausente")
            return
        try:
            if route == "/api/upload":
                target = self._target(self._query("path"))
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    self._error(400, "El archivo llego vacio")
                    return
                if length > MAX_UPLOAD:
                    self._error(413, "El archivo es demasiado grande")
                    return
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
                return
            if route == "/api/mkdir":
                target = self._target(self._query("path"))
                target.mkdir(parents=True, exist_ok=True)
                self._json({"ok": True, "path": self._relative(target)})
                return
            if route == "/api/delete":
                target = self._target(self._query("path"))
                if target == self.root:
                    self._error(400, "No se puede borrar la carpeta del servidor")
                    return
                if not target.exists():
                    self._error(404, "Ese archivo no existe")
                    return
                if target.is_dir():
                    if self._query("recursive") == "1":
                        shutil.rmtree(target)
                    else:
                        target.rmdir()
                else:
                    target.unlink()
                self._json({"ok": True})
                return
            if route == "/api/rename":
                source = self._target(self._query("path"))
                destination = self._target(self._query("to"))
                if not source.exists():
                    self._error(404, "Ese archivo no existe")
                    return
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.replace(destination)
                self._json({"ok": True, "path": self._relative(destination)})
                return
            self._error(404, "Ruta desconocida")
        except PermissionError as error:
            self._error(403, str(error))
        except OSError as error:
            self._error(409, f"{type(error).__name__}: {error}")
        except Exception as error:  # pragma: no cover
            self._error(500, f"{type(error).__name__}: {error}")


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
    parser = argparse.ArgumentParser(description=f"Agente {APP} para los servidores")
    parser.add_argument("--root", default=".", help="Carpeta que el panel puede ver (por defecto la actual)")
    parser.add_argument("--host", default="0.0.0.0", help="Interfaz de red (por defecto todas)")
    parser.add_argument("--port", type=int, default=8787, help="Puerto (por defecto 8787)")
    parser.add_argument("--token", default="", help="Clave que usara el panel")
    parser.add_argument("--node", default=socket.gethostname(), help="Nombre visible de este servidor")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    Handler.root = root
    Handler.token = _load_token(args.token, Path(__file__).resolve().parent)
    Handler.node = args.node

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"=== {APP} · servidor {Handler.node} ===")
    print(f"Carpeta: {root}")
    print(f"Escuchando en http://{args.host}:{args.port}")
    print(f"Clave:   {Handler.token}")
    print("Deja esta ventana abierta. Ctrl+C para parar.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
