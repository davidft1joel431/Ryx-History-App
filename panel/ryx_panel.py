#!/usr/bin/env python3
"""Panel de control de RyxHistory (solo para el PC del dueno).

Ventana con varias secciones (Inicio, Servidores, Servidor, Registro, APK),
una consola integrada en Inicio, varios servidores y lectura de la base de datos
del servidor host (cuentas, mensajes por seccion e imagenes). Compila el APK
contra el servidor activo con el JDK y el SDK de Android del equipo.

Modos: sin argumentos abre la ventana; --console es el menu de texto;
--check imprime la configuracion y --selftest comprueba que la ventana se crea.
"""
from __future__ import annotations

import ctypes
import base64
import json
import os
import queue
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

APP = "RyxHistory"
DEFAULT_SERVER = "https://CAMBIA-ESTO.example.com"
TIMEOUT = 8

BG = "#14100C"
CARD = "#1E1812"
RAISED = "#2A2118"
LINE = "#3A2E20"
GOLD = "#FFC400"
ORANGE = "#FF8A00"
GREEN = "#1FD34A"
RED = "#FF5A4D"
CREAM = "#FFF6DC"
MUTED = "#B8A98A"
LOG_BG = "#0F0C09"
INK = "#14100C"


# ------------------------------- configuracion -------------------------------

def find_repo() -> Path:
    """Busca la carpeta del proyecto subiendo desde el .exe (o desde el script)."""
    if getattr(sys, "frozen", False):
        here = Path(sys.executable).resolve().parent
    else:
        here = Path(__file__).resolve().parent
    starts = [Path(os.environ["RYX_REPO"])] if os.environ.get("RYX_REPO") else []
    starts += [here, here.parent, Path.cwd()]
    for start in starts:
        for folder in [start, *start.parents]:
            if (folder / "settings.gradle.kts").exists() and (folder / "gradlew.bat").exists():
                return folder
    raise SystemExit("No encuentro el proyecto RyxHistory (settings.gradle.kts + gradlew.bat).")


def config_path(repo: Path) -> Path:
    return repo / "panel" / "panel.json"


def active_server(cfg: dict) -> dict | None:
    for server in cfg.get("servers", []):
        if server.get("name") == cfg.get("active"):
            return server
    servers = cfg.get("servers", [])
    return servers[0] if servers else None


def load_config(repo: Path) -> dict:
    """Config nueva (varios servidores) o migracion de la version de uno solo."""
    cfg: dict = {"active": "", "servers": [], "versionName": "1.0.5", "versionCode": 15}
    path = config_path(repo)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in ("active", "servers", "versionName", "versionCode"):
                if key in data:
                    cfg[key] = data[key]
            if not cfg["servers"] and data.get("server"):
                cfg["servers"] = [{"name": "Servidor principal", "url": data["server"]}]
                cfg["active"] = "Servidor principal"
        except Exception:
            pass
    if not cfg["servers"]:
        cfg["servers"] = [{"name": "Servidor principal", "url": DEFAULT_SERVER}]
        cfg["active"] = "Servidor principal"
    for item in cfg["servers"]:
        item.setdefault("token", "")
    if not active_server(cfg):
        cfg["active"] = cfg["servers"][0]["name"]
    return cfg


def save_config(repo: Path, cfg: dict) -> None:
    path = config_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_server(raw: str) -> str | None:
    text = raw.strip().rstrip("/")
    if not text:
        return None
    if not text.lower().startswith(("http://", "https://")):
        text = "https://" + text
    host = text.split("://", 1)[1].split("/", 1)[0]
    if not host or " " in host:
        return None
    return text


def human_size(size: float) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


# --------------------------- conexion con el servidor ------------------------

class NodeError(Exception):
    pass


class Node:
    """Cliente del agente que corre en cada servidor (server/ryx_server.py)."""

    def __init__(self, url: str, token: str = "", timeout: int = TIMEOUT):
        self.base = (url or "").rstrip("/")
        self.token = (token or "").strip()
        self.timeout = timeout

    def _context(self):
        try:
            return ssl._create_unverified_context()
        except Exception:
            return None

    def _open(self, method: str, path: str, data: bytes | None = None,
              params: dict | None = None, timeout: float | None = None) -> bytes:
        bases = [self.base]
        if "://" in self.base:
            scheme, rest = self.base.split("://", 1)
            bases.append(("http://" if scheme.lower() == "https" else "https://") + rest)
        last: Exception | None = None
        for base in bases:
            url = base + path
            if params:
                url += "?" + urllib.parse.urlencode(params)
            request = urllib.request.Request(url, data=data, method=method)
            if self.token:
                request.add_header("X-Ryx-Token", self.token)
            if data is not None:
                request.add_header("Content-Type", "application/octet-stream")
            try:
                with urllib.request.urlopen(
                    request, timeout=timeout or self.timeout, context=self._context()
                ) as response:
                    self.base = base
                    return response.read()
            except urllib.error.HTTPError as error:
                raw = error.read()
                message = ""
                try:
                    message = json.loads(raw.decode("utf-8", "replace")).get("error", "")
                except Exception:
                    message = raw.decode("utf-8", "replace")[:140]
                if error.code == 401:
                    raise NodeError("La clave del servidor no coincide") from None
                raise NodeError(message or f"HTTP {error.code}") from None
            except Exception as error:
                last = error
        raise NodeError(str(getattr(last, "reason", last) or "Sin respuesta del servidor"))

    def get(self, route: str, **params) -> dict:
        return json.loads(self._open("GET", route, params=params or None).decode("utf-8"))

    def info(self) -> dict:
        return self.get("/api/info")

    def me(self) -> dict:
        return self.get("/api/me")

    # --- registro de usuarios (base de datos del servidor) ---

    def admin_users(self) -> dict:
        return self.get("/api/admin/users")

    def admin_notifications(self, user_id: str, query: str = "", limit: int = 300) -> dict:
        return self.get("/api/admin/notifications", user=user_id, q=query, limit=limit)


def join_remote(base: str, name: str) -> str:
    name = (name or "").strip().replace("\\", "/").strip("/")
    if not base:
        return name
    return f"{base}/{name}" if name else base


def parent_remote(base: str) -> str:
    if not base:
        return ""
    parts = [part for part in base.split("/") if part]
    return "/".join(parts[:-1])


# --------------------------------- acciones ---------------------------------

def _request(url: str) -> tuple[bool, str, int]:
    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            return True, f"HTTP {response.status}", int((time.time() - started) * 1000)
    except urllib.error.HTTPError as error:
        return True, f"HTTP {error.code}", int((time.time() - started) * 1000)
    except Exception as error:
        text = str(getattr(error, "reason", error))
        if "certificate" in text.lower() or "ssl" in text.lower():
            try:
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(url, timeout=TIMEOUT, context=context) as response:
                    return True, f"HTTP {response.status} (certificado propio)", int((time.time() - started) * 1000)
            except Exception as second:
                return False, str(getattr(second, "reason", second)), 0
        return False, text, 0


def probe(server: str, log=print) -> tuple[bool, str]:
    """Comprueba el servidor; si no responde por https prueba por http y viceversa."""
    candidates = [server]
    if server.lower().startswith("https://"):
        candidates.append("http://" + server[8:])
    elif server.lower().startswith("http://"):
        candidates.append("https://" + server[7:])
    log(f"Probando {server} ...")
    for base in candidates:
        for path in ("/api/ping", "/api/health", "/health", "/"):
            ok, detail, ms = _request(base + path)
            if ok:
                extra = "" if base == server else f" (responde por {base.split('://')[0]})"
                message = f"{detail} · {ms} ms{extra}"
                log(f"OK   {base + path} -> {message}")
                return True, message
            log(f"--   {base + path} -> {detail}")
    log("No respondio: revisa IP, puerto, certificado o si el servidor esta encendido.")
    return False, "Sin respuesta"


def build(repo: Path, cfg: dict, log=print) -> Path | None:
    server = active_server(cfg)
    if not server:
        log("No hay ningun servidor configurado.")
        return None
    code = int(cfg["versionCode"])
    name = str(cfg["versionName"])
    log(f"Compilando {APP} {name} (versionCode {code}) para {server['name']} · {server['url']} ...")
    env = os.environ.copy()
    env.update(SERVER_URL=str(server["url"]), APP_VERSION_NAME=name, APP_VERSION_CODE=str(code))
    cmd = [
        os.environ.get("COMSPEC", "cmd.exe"), "/c",
        str(repo / "gradlew.bat"), "assembleRelease", "--no-daemon", "--console=plain",
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        cmd, cwd=str(repo), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=flags,
    )
    if process.stdout is not None:
        for line in process.stdout:
            log(line.rstrip())
    if process.wait() != 0:
        log("La compilacion fallo. Revisa el mensaje de Gradle de arriba.")
        return None
    apks = sorted((repo / "app" / "build" / "outputs" / "apk" / "release").glob("*.apk"))
    if not apks:
        log("No encuentro el APK generado.")
        return None
    out_dir = repo / "panel" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{APP}-{name}.apk"
    shutil.copy2(apks[-1], target)
    cfg["versionCode"] = code + 1
    save_config(repo, cfg)
    log(f"APK listo: {target}")
    log(f"La proxima compilacion usara versionCode {cfg['versionCode']}.")
    return target


def enable_dpi_awareness() -> None:
    """Sin esto Windows estira la ventana y todo se ve borroso en pantallas escaladas."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ------------------------------ piezas graficas ------------------------------

def _blend(first: str, second: str, amount: float) -> str:
    """Mezcla dos colores #rrggbb (amount 0 = primero, 1 = segundo)."""
    amount = max(0.0, min(1.0, amount))
    try:
        a = [int(first[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(second[i:i + 2], 16) for i in (1, 3, 5)]
    except Exception:
        return first
    return "#%02X%02X%02X" % tuple(int(round(a[i] + (b[i] - a[i]) * amount)) for i in range(3))


class ProgressBar(tk.Canvas):
    """Barra fina que barre mientras se compila o se transfiere."""

    def __init__(self, ui, master, height: float = 6):
        bg = master.cget("bg")
        super().__init__(master, bg=bg, height=ui.px(height), highlightthickness=0, bd=0)
        self.ui = ui
        self._pos = 0.0
        self._running = False
        self.bind("<Configure>", lambda _e: self._paint())

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tick()

    def stop(self) -> None:
        self._running = False
        self.delete("all")

    def _tick(self) -> None:
        if not self._running:
            return
        self._pos = (self._pos + 0.05) % 1.0
        self._paint()
        self.after(22, self._tick)

    def _paint(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = max(self.winfo_height(), self.ui.px(6))
        if width < 8:
            return
        self.create_polygon(
            _rounded_points(0, 0, width, height, height / 2), smooth=True, splinesteps=14,
            fill=RAISED, outline=RAISED,
        )
        segment = width * 0.26
        start = self._pos * (width + segment) - segment
        x0, x1 = max(1.0, start), min(width - 1.0, start + segment)
        if x1 - x0 > 3:
            self.create_polygon(
                _rounded_points(x0, 1, x1, height - 1, (height - 2) / 2), smooth=True,
                splinesteps=14, fill=GOLD, outline=GOLD,
            )


def _rounded_points(x0: float, y0: float, x1: float, y1: float, radius: float) -> list:
    r = max(1.0, radius)
    return [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]


class RoundedBox(tk.Frame):
    """Cuadro con las esquinas redondeadas; el contenido va en `inner`."""

    def __init__(self, ui, master, fill: str = CARD, outline: str = LINE,
                 radius: float = 14, padding: float = 16):
        bg = master.cget("bg")
        super().__init__(master, bg=bg)
        self.ui = ui
        self._fill = fill
        self._outline = outline
        self._radius = ui.px(radius)
        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, takefocus=0)
        self._canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.inner = tk.Frame(self, bg=fill)
        self.inner.pack(fill="both", expand=True, padx=ui.px(padding), pady=ui.px(padding))
        self._canvas.bind("<Configure>", self._paint)

    def _paint(self, _event=None) -> None:
        canvas = self._canvas
        canvas.delete("shape")
        width = max(canvas.winfo_width(), 2)
        height = max(canvas.winfo_height(), 2)
        radius = min(self._radius, width // 2, height // 2)
        points = _rounded_points(1, 1, width - 1, height - 1, radius)
        canvas.create_polygon(
            points, smooth=True, splinesteps=28, fill=self._fill,
            outline=self._outline or self._fill, width=1, tags="shape",
        )


class ScrollArea(tk.Frame):
    """Zona con desplazamiento vertical (para listas largas de servidores)."""

    def __init__(self, ui, master):
        bg = master.cget("bg")
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self._resize)
        self.body.bind("<Configure>", self._scrollregion)

    def _resize(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._scrollregion()

    def _scrollregion(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def scroll(self, steps: int) -> None:
        self.canvas.yview_scroll(steps, "units")


class RoundedButton(tk.Canvas):
    """Boton con esquinas redondeadas (texto centrado o alineado a la izquierda)."""

    KINDS = {
        "primary": (GOLD, INK, ORANGE, GOLD),
        "ghost": (RAISED, CREAM, "#33291D", LINE),
        "danger": (RAISED, RED, "#3A1A16", "#4A2A24"),
        "nav": (CARD, MUTED, RAISED, CARD),
        "nav-active": (RAISED, GOLD, RAISED, RAISED),
    }

    def __init__(self, ui, master, text: str, command=None, kind: str = "ghost",
                 size: int = 9, bold: bool | None = None, align: str = "center",
                 radius: float = 10, padx: float = 14, pady: float = 7):
        bg = master.cget("bg")
        self.ui = ui
        self._text = text
        self._command = command
        self._align = align
        self._radius = ui.px(radius)
        self._padx = ui.px(padx)
        self._pady = ui.px(pady)
        self._enabled = True
        self._hovering = False
        bold = (kind != "ghost") if bold is None else bold
        self._font = tkfont.Font(
            family="Segoe UI", size=-ui.px(size), weight="bold" if bold else "normal"
        )
        width = self._font.measure(text) + 2 * self._padx
        height = self._font.metrics("linespace") + 2 * self._pady
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, width=width, height=height,
                         cursor="hand2", takefocus=0)
        self._width = width
        self._height = height
        self._apply_kind(kind)
        self.bind("<Configure>", lambda _e: self._paint())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonRelease-1>", self._on_click)
        self._paint()

    def _apply_kind(self, kind: str) -> None:
        self._fill, self._fg, self._hover, self._outline = self.KINDS.get(kind, self.KINDS["ghost"])

    def _paint(self) -> None:
        width = self.winfo_width()
        height = self.winfo_height()
        width = self._width if width <= 1 else width
        height = self._height if height <= 1 else height
        self.delete("all")
        radius = min(self._radius, width // 2, height // 2)
        fill = self._hover if self._hovering and self._enabled else self._fill
        fg = self._fg if self._enabled else "#6E6355"
        points = _rounded_points(1, 1, width - 1, height - 1, radius)
        self.create_polygon(
            points, smooth=True, splinesteps=28, fill=fill,
            outline=self._outline or fill, width=1,
        )
        if self._align == "w":
            self.create_text(self._padx, height / 2, text=self._text, fill=fg,
                             font=self._font, anchor="w")
        else:
            self.create_text(width / 2, height / 2, text=self._text, fill=fg, font=self._font)

    def _on_enter(self, _event=None) -> None:
        if self._enabled:
            self._hovering = True
            self._paint()

    def _on_leave(self, _event=None) -> None:
        self._hovering = False
        self._paint()

    def _on_click(self, _event=None) -> None:
        if self._enabled and self._command:
            self._command()

    def fade_to(self, kind: str, steps: int = 6) -> None:
        """Cambia de estilo con una transicion corta de color."""
        target = self.KINDS.get(kind, self.KINDS["ghost"])
        start_fill, start_fg = self._fill, self._fg
        start_line = self._outline or self._fill

        def step(index: int = 1) -> None:
            amount = index / steps
            self._fill = _blend(start_fill, target[0], amount)
            self._fg = _blend(start_fg, target[1], amount)
            self._outline = _blend(start_line, target[3] or target[0], amount)
            self._paint()
            if index < steps:
                self.after(22, lambda: step(index + 1))
            else:
                self._apply_kind(kind)
                self._paint()

        step()

    def set(self, text: str | None = None, kind: str | None = None,
            state: str | None = None) -> None:
        if text is not None:
            self._text = text
            width = self._font.measure(text) + 2 * self._padx
            self._width = max(self._width, width) if self._align == "w" else width
            self.configure(width=self._width)
        if kind is not None:
            self._apply_kind(kind)
        if state is not None:
            self._enabled = state != "disabled"
            self.configure(cursor="hand2" if self._enabled else "arrow")
        self._paint()


# ---------------------------------- ventana ----------------------------------

class Panel:
    def __init__(self, repo: Path, selftest: bool = False):
        enable_dpi_awareness()
        self.repo = repo
        self.cfg = load_config(repo)
        self.selftest = selftest
        self.status: dict[str, tuple[bool, str]] = {}
        self.messages: queue.Queue[str] = queue.Queue()
        self.ui_queue: queue.Queue = queue.Queue()
        self.node: Node | None = None
        self.remote_path = ""
        self.remote_entries: list = []
        self.users: list = []
        self.console = None
        self.registry_section = "mensajes"
        self.registry_entries: list = []
        self.registry_view: list = []
        self.registry_index = 0
        self._state_color = MUTED
        self._pulse = 0

        self.root = tk.Tk()
        self.root.title(f"{APP} · Panel de control")
        self.root.configure(bg=BG)
        self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        width = min(self.px(1060), int(self.root.winfo_screenwidth() / self.scale) - self.px(30))
        height = min(self.px(740), int(self.root.winfo_screenheight() / self.scale) - self.px(60))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(self.px(900), self.px(640))
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)

        try:
            self.root.attributes("-alpha", 0.0)
        except Exception:
            pass

        self._build_header()
        self._build_sidebar()
        self._build_content()
        self.show_page("inicio")
        self.root.after(120, self._drain)
        self._fade_in()
        self.root.after(400, self._pulse_step)
        self.log(f"Panel listo · {len(self.cfg['servers'])} servidor(es) configurado(s)")

        if selftest:
            self.root.update()
            folder = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
            (folder / "gui-selftest.txt").write_text(
                f"OK {self.root.winfo_width()}x{self.root.winfo_height()} scale={self.scale:.2f}\n",
                encoding="utf-8",
            )
            self.root.destroy()
            return

        self.root.mainloop()

    # ------------------------------ utilidades ------------------------------

    def px(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def fnt(self, size: int = 10, bold: bool = False, mono: bool = False):
        family = "Consolas" if mono else "Segoe UI"
        return (family, -self.px(size), "bold" if bold else "normal")

    def log(self, message: str) -> None:
        self.messages.put(message)

    def _fade_in(self, step: int = 0, steps: int = 10) -> None:
        """La ventana aparece con un fundido en vez de saltar de golpe."""
        try:
            self.root.attributes("-alpha", min(1.0, step / steps))
        except Exception:
            return
        if step < steps:
            self.root.after(16, lambda: self._fade_in(step + 1, steps))

    def _pulse_step(self) -> None:
        """El punto de estado del servidor respira suave."""
        self._pulse = (self._pulse + 1) % 30
        phase = abs(self._pulse - 15) / 15.0
        try:
            self.header_state.config(fg=_blend(self._state_color, "#4A3F2E", 0.5 * phase))
        except Exception:
            return
        self.root.after(110, self._pulse_step)

    def ui(self, callback) -> None:
        """Se llama desde el hilo principal: nunca se toca Tk desde otro hilo."""
        self.ui_queue.put(callback)

    def run_bg(self, work, failed=None) -> None:
        def runner() -> None:
            try:
                work()
            except Exception as error:
                text = str(error) or type(error).__name__
                if failed is not None:
                    failed(text)
                else:
                    self.log(f"Error: {text}")

        threading.Thread(target=runner, daemon=True).start()

    def label(self, parent, text, size=10, color=CREAM, bold=False, bg=CARD, mono=False):
        return tk.Label(
            parent, text=text, bg=bg, fg=color, anchor="w", justify="left",
            font=self.fnt(size, bold, mono),
        )

    def button(self, parent, text, command, kind="ghost", align="center", size=9,
               bold=None, padx=14, pady=7) -> RoundedButton:
        return RoundedButton(self, parent, text, command, kind=kind, size=size,
                             bold=bold, align=align, padx=padx, pady=pady)

    def card(self, parent, title=None) -> tuple:
        box = RoundedBox(self, parent)
        box.inner.columnconfigure(0, weight=1)
        body = tk.Frame(box.inner, bg=CARD)
        if title:
            self.label(box.inner, title.upper(), size=8, color=GOLD, bold=True).grid(
                row=0, column=0, sticky="w", pady=(0, self.px(8))
            )
            box.inner.rowconfigure(1, weight=1)
            body.grid(row=1, column=0, sticky="nsew")
        else:
            box.inner.rowconfigure(0, weight=1)
            body.grid(row=0, column=0, sticky="nsew")
        return box, body

    def field(self, parent, value="", width=24, mono=True) -> tuple:
        box = RoundedBox(self, parent, fill=RAISED, outline=LINE, radius=10, padding=8)
        entry = tk.Entry(
            box.inner, bg=RAISED, fg=CREAM, insertbackground=CREAM, relief="flat", bd=0,
            font=self.fnt(10, mono=mono), width=width, highlightthickness=0,
        )
        entry.insert(0, value)
        entry.pack(fill="x")
        return box, entry

    def chip(self, parent, text: str, color: str = GOLD) -> RoundedBox:
        box = RoundedBox(self, parent, fill=RAISED, outline=RAISED, radius=9, padding=5)
        self.label(box.inner, text, size=8, color=color, bold=True).pack(anchor="w")
        return box

    # -------------------------------- cabecera -------------------------------

    def _build_header(self):
        header = tk.Frame(self.root, bg=CARD)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(1, weight=1)

        try:
            raw = tk.PhotoImage(
                file=str(self.repo / "app" / "src" / "main" / "res" / "drawable-nodpi" / "logo.png")
            )
            factor = max(1, int(round(raw.width() / self.px(120))))
            logo = raw.subsample(factor, factor)
            image = tk.Label(header, image=logo, bg=CARD)
            image.image = logo
            image.grid(row=0, column=0, rowspan=2, padx=(self.px(18), self.px(12)), pady=self.px(8))
            self.root.iconphoto(True, logo)
        except Exception:
            pass

        tk.Label(header, text=APP, bg=CARD, fg=GOLD, font=self.fnt(18, bold=True)).grid(
            row=0, column=1, sticky="sw", pady=(self.px(8), 0)
        )
        tk.Label(
            header, text="Panel de control · servidores, base de datos y APK", bg=CARD, fg=MUTED,
            font=self.fnt(9),
        ).grid(row=1, column=1, sticky="nw", pady=(0, self.px(8)))

        self.header_server = tk.Label(header, text="", bg=CARD, fg=CREAM, font=self.fnt(10, bold=True))
        self.header_server.grid(row=0, column=2, sticky="se", padx=self.px(18), pady=(self.px(8), 0))
        self.header_state = tk.Label(header, text="●  sin comprobar", bg=CARD, fg=MUTED, font=self.fnt(9))
        self.header_state.grid(row=1, column=2, sticky="ne", padx=self.px(18), pady=(0, self.px(8)))

        tk.Frame(self.root, bg=LINE, height=1).grid(row=0, column=0, columnspan=2, sticky="sew")

    # ------------------------------- lateral ---------------------------------

    def _build_sidebar(self):
        sidebar = RoundedBox(self, self.root, fill=CARD, outline=LINE, radius=18, padding=10)
        sidebar.grid(row=1, column=0, sticky="nsew", padx=(self.px(16), 0), pady=(self.px(14), 0))
        sidebar.configure(width=self.px(196))
        sidebar.grid_propagate(False)

        self.nav_buttons: dict[str, RoundedButton] = {}
        for key, text in (("inicio", "Inicio"), ("servidores", "Servidores"),
                          ("archivos", "Servidor"), ("registro", "Registro"), ("apk", "APK")):
            button = self.button(
                sidebar.inner, text, lambda k=key: self.show_page(k), kind="nav",
                size=10, align="w", padx=14, pady=9,
            )
            button.pack(fill="x", pady=(0, self.px(4)))
            self.nav_buttons[key] = button

        footer = tk.Frame(sidebar.inner, bg=CARD)
        footer.pack(side="bottom", fill="x", pady=(self.px(10), 0))
        self.label(footer, "PROYECTO", size=8, color=MUTED).pack(anchor="w")
        self.label(footer, self.repo.name, size=9, color=CREAM).pack(anchor="w")

    # --------------------------------- páginas -------------------------------

    def _build_content(self):
        self.content = tk.Frame(self.root, bg=BG)
        self.content.grid(row=1, column=1, sticky="nsew", padx=self.px(14),
                          pady=(self.px(14), self.px(14)))
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self.pages: dict[str, tk.Frame] = {}
        for key in ("inicio", "servidores", "servidor", "registro", "apk"):
            page = tk.Frame(self.content, bg=BG)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page

        self._build_home()
        self._build_servers()
        self._build_connection()
        self._build_registry()
        self._build_apk()

    def show_page(self, key: str) -> None:
        for name, button in self.nav_buttons.items():
            button.fade_to("nav-active" if name == key else "nav")
        self.pages[key].tkraise()
        if key == "inicio":
            self.refresh_home()
        elif key == "servidores":
            self.refresh_servers()
        elif key == "servidor":
            self.refresh_connection()
        elif key == "registro":
            self.refresh_registry()
        elif key == "apk":
            self.refresh_apk()

    def page_title(self, page, title: str, subtitle: str):
        box = tk.Frame(page, bg=BG)
        box.grid(row=0, column=0, sticky="w")
        self.label(box, title, size=16, color=CREAM, bold=True, bg=BG).pack(anchor="w")
        self.label(box, subtitle, size=9, color=MUTED, bg=BG).pack(anchor="w", pady=(self.px(2), 0))
        return box

    # --- inicio ---

    def _build_home(self):
        page = self.pages["inicio"]
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)

        top = tk.Frame(page, bg=BG)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        self.page_title(top, "Inicio", "Servidores, base de datos y APK en un solo sitio")

        actions = tk.Frame(top, bg=BG)
        actions.grid(row=0, column=1, rowspan=2, sticky="e", pady=(self.px(6), 0))
        self.button(actions, "Compilar APK", lambda: self.show_page("apk"),
                    kind="primary").pack(side="left")

        quick = tk.Frame(page, bg=BG)
        quick.grid(row=1, column=0, sticky="ew", pady=(self.px(12), 0))
        for texto, accion in (
            ("Probar servidor", self.probe_active),
            ("Conectar host", self.connect_node),
            ("Registro", lambda: self.show_page("registro")),
            ("Abrir APKs", self.open_out),
            ("Copiar clave", self.copy_token),
            ("Limpiar consola", self.clear_console),
        ):
            self.button(quick, texto, accion, size=8, padx=12, pady=6).pack(
                side="left", padx=(0, self.px(6))
            )

        stats = tk.Frame(page, bg=BG)
        stats.grid(row=2, column=0, sticky="ew", pady=(self.px(12), 0))
        for column in range(3):
            stats.columnconfigure(column, weight=1, uniform="stat")
        self.stat_servers = self._stat_card(stats, 0, "SERVIDORES")
        self.stat_active = self._stat_card(stats, 1, "ACTIVO")
        self.stat_apk = self._stat_card(stats, 2, "APK")

        subtitle = self.label(page, "SERVIDORES", size=8, color=GOLD, bold=True, bg=BG)
        subtitle.grid(row=3, column=0, sticky="w", pady=(self.px(14), self.px(6)))

        self.home_area = ScrollArea(self, page)
        self.home_area.grid(row=4, column=0, sticky="nsew")
        self.home_grid = tk.Frame(self.home_area.body, bg=BG)
        self.home_grid.pack(fill="x")
        self.home_grid.columnconfigure(0, weight=1, uniform="srv")
        self.home_grid.columnconfigure(1, weight=1, uniform="srv")
        self.root.bind_all("<MouseWheel>", self._home_wheel, add="+")

        consola_card, consola = self.card(page, "Consola")
        consola_card.grid(row=5, column=0, sticky="ew", pady=(self.px(10), 0))
        caja = RoundedBox(self, consola, fill=LOG_BG, outline=LINE, radius=10, padding=6)
        caja.pack(fill="both", expand=True)
        self.console = tk.Text(
            caja.inner, bg=LOG_BG, fg="#D9CDB4", insertbackground=CREAM, relief="flat", bd=0,
            font=self.fnt(9, mono=True), wrap="word", height=6, highlightthickness=0,
            state="disabled",
        )
        self.console.pack(fill="both", expand=True)
        self.console.bind(
            "<MouseWheel>", lambda event: self.console.yview_scroll(int(-event.delta / 120), "units")
        )

    def probe_active(self) -> None:
        server = active_server(self.cfg)
        if server:
            self.probe_one(server["url"])
        else:
            self.log("No hay servidor configurado.")

    def copy_token(self) -> None:
        server = active_server(self.cfg)
        token = (server or {}).get("token", "")
        if not token:
            self.log("Ese servidor no tiene clave guardada.")
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(token)
            self.log("Clave del panel copiada al portapapeles.")
        except Exception:
            self.log("No se pudo copiar la clave.")

    def _stat_card(self, parent, column: int, title: str):
        frame, body = self.card(parent)
        frame.grid(
            row=0, column=column, sticky="nsew",
            padx=(0 if column == 0 else self.px(6), 0 if column == 2 else self.px(6)),
        )
        self.label(body, title, size=8, color=MUTED).pack(anchor="w")
        value = self.label(body, "—", size=13, color=CREAM, bold=True)
        value.pack(anchor="w", pady=(self.px(2), 0))
        return value

    def _home_wheel(self, event) -> None:
        """La rueda desplaza la lista de servidores de Inicio."""
        try:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return
        while widget is not None:
            if widget is self.home_area.canvas or widget is self.home_area.body:
                self.home_area.scroll(int(-event.delta / 120))
                return
            widget = getattr(widget, "master", None)

    def refresh_home(self) -> None:
        server = active_server(self.cfg)
        self.stat_servers.config(text=str(len(self.cfg["servers"])))
        self.stat_active.config(text=server["name"] if server else "—", fg=GOLD)
        self.stat_apk.config(text=f"{self.cfg['versionName']}  ·  {self.cfg['versionCode']}")

        if server:
            self.header_server.config(text=server["name"])
            ok, message = self.status.get(server["url"], (False, "sin comprobar"))
            color = MUTED if message == "sin comprobar" else (GREEN if ok else RED)
            self._state_color = color
            self.header_state.config(text=f"●  {message}")

        for child in self.home_grid.winfo_children():
            child.destroy()

        for index, item in enumerate(self.cfg["servers"]):
            frame, body = self.card(self.home_grid)
            left = index % 2 == 0
            frame.grid(
                row=index // 2, column=index % 2, sticky="nsew",
                padx=(0 if left else self.px(6), self.px(6) if left else 0),
                pady=(0, self.px(10)),
            )
            is_active = item["name"] == self.cfg["active"]
            head = tk.Frame(body, bg=CARD)
            head.pack(fill="x")
            self.label(head, item["name"], size=11, color=CREAM, bold=True).pack(side="left")
            if is_active:
                self.chip(head, "ACTIVO").pack(side="right")
            self.label(body, item["url"], size=9, color=MUTED, mono=True).pack(
                anchor="w", pady=(self.px(2), self.px(8))
            )

            ok, message = self.status.get(item["url"], (False, "sin comprobar"))
            color = MUTED if message == "sin comprobar" else (GREEN if ok else RED)
            tk.Label(
                body, text=f"●  {message}", bg=CARD, fg=color, font=self.fnt(9), anchor="w"
            ).pack(anchor="w")

            buttons = tk.Frame(body, bg=CARD)
            buttons.pack(fill="x", pady=(self.px(10), 0))
            self.button(buttons, "Probar", lambda u=item["url"]: self.probe_one(u)).pack(side="left")
            if not is_active:
                self.button(
                    buttons, "Usar este", lambda n=item["name"]: self.activate(n), kind="primary"
                ).pack(side="left", padx=(self.px(8), 0))
            else:
                self.button(
                    buttons, "Conexion", lambda: self.show_page("servidor")
                ).pack(side="left", padx=(self.px(8), 0))

    # --- servidores ---

    def _build_servers(self):
        page = self.pages["servidores"]
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.page_title(page, "Servidores", "Varios servidores: elige cual usa el APK y comprueba cada uno.")

        body = tk.Frame(page, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", pady=(self.px(14), 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        list_card, list_body = self.card(body, "Lista")
        list_card.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(6)))
        list_body.rowconfigure(0, weight=1)
        list_body.columnconfigure(0, weight=1)
        list_box = RoundedBox(self, list_body, fill=LOG_BG, outline=LINE, radius=10, padding=6)
        list_box.grid(row=0, column=0, sticky="nsew")
        self.server_list = tk.Listbox(
            list_box.inner, bg=LOG_BG, fg=CREAM, selectbackground=GOLD, selectforeground=INK,
            bd=0, highlightthickness=0, font=self.fnt(10), height=9, activestyle="none",
        )
        self.server_list.pack(fill="both", expand=True)
        self.server_list.bind("<<ListboxSelect>>", self._on_select_server)

        form_card, form_body = self.card(body, "Datos del servidor")
        form_card.grid(row=0, column=1, sticky="nsew", padx=(self.px(6), 0))
        self.label(form_body, "Nombre", size=9, color=MUTED).pack(anchor="w")
        box, self.name_entry = self.field(form_body)
        box.pack(fill="x", pady=(self.px(4), self.px(10)))

        self.label(form_body, "Direccion (IP:puerto o dominio)", size=9, color=MUTED).pack(anchor="w")
        box, self.url_entry = self.field(form_body)
        box.pack(fill="x", pady=(self.px(4), self.px(4)))

        hint = self.label(form_body, "La clave la da el agente del servidor (ryx_token.txt)", size=8, color=MUTED)
        hint.pack(anchor="w")

        self.label(form_body, "Clave del servidor", size=9, color=MUTED).pack(anchor="w", pady=(self.px(8), 0))
        box, self.form_token = self.field(form_body)
        box.pack(fill="x", pady=(self.px(4), self.px(12)))

        row = tk.Frame(form_body, bg=CARD)
        row.pack(fill="x")
        self.button(row, "Guardar cambios", self.save_server, kind="primary").pack(
            side="left", padx=(0, self.px(8))
        )
        self.button(row, "Añadir nuevo", self.add_server).pack(side="left")

        row2 = tk.Frame(form_body, bg=CARD)
        row2.pack(fill="x", pady=(self.px(8), 0))
        self.button(row2, "Usar este", self.activate_selected).pack(side="left", padx=(0, self.px(8)))
        self.button(row2, "Probar", self.probe_selected).pack(side="left", padx=(0, self.px(8)))
        self.button(row2, "Conexion", lambda: self.show_page("servidor")).pack(
            side="left", padx=(0, self.px(8))
        )
        self.button(row2, "Eliminar", self.delete_server, kind="danger").pack(side="left")

    def _selected_index(self) -> int | None:
        selection = self.server_list.curselection()
        return selection[0] if selection else None

    def _on_select_server(self, _event=None) -> None:
        index = self._selected_index()
        if index is None:
            return
        server = self.cfg["servers"][index]
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, server["name"])
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, server["url"])
        self.form_token.delete(0, "end")
        self.form_token.insert(0, server.get("token", ""))

    def refresh_servers(self) -> None:
        self.server_list.delete(0, "end")
        for server in self.cfg["servers"]:
            mark = "  ★" if server["name"] == self.cfg["active"] else ""
            self.server_list.insert("end", f"{server['name']}{mark}")
        index = next(
            (i for i, s in enumerate(self.cfg["servers"]) if s["name"] == self.cfg["active"]), None
        )
        if index is not None:
            self.server_list.selection_clear(0, "end")
            self.server_list.selection_set(index)
            self._on_select_server()

    def save_server(self) -> None:
        index = self._selected_index()
        if index is None:
            self.log("Selecciona un servidor de la lista.")
            return
        name = self.name_entry.get().strip()
        url = normalize_server(self.url_entry.get())
        if not name:
            self.log("El servidor necesita un nombre.")
            return
        if not url:
            self.log("Direccion no valida (ejemplo: https://midominio.com o 192.168.1.10:3000).")
            return
        old = self.cfg["servers"][index]
        if old["name"] != name and any(s["name"] == name for s in self.cfg["servers"]):
            self.log(f"Ya existe un servidor llamado {name}.")
            return
        was_active = self.cfg["active"] == old["name"]
        self.cfg["servers"][index] = {
            "name": name, "url": url, "token": self.form_token.get().strip(),
        }
        if was_active:
            self.cfg["active"] = name
        save_config(self.repo, self.cfg)
        self.refresh_servers()
        self.refresh_home()
        self.log(f"Guardado: {name} · {url}")

    def add_server(self) -> None:
        name = self.name_entry.get().strip() or f"Servidor {len(self.cfg['servers']) + 1}"
        url = normalize_server(self.url_entry.get())
        if not url:
            self.log("Escribe la direccion del servidor nuevo.")
            return
        if any(s["name"] == name for s in self.cfg["servers"]):
            self.log(f"Ya existe un servidor llamado {name}.")
            return
        self.cfg["servers"].append({"name": name, "url": url, "token": self.form_token.get().strip()})
        save_config(self.repo, self.cfg)
        self.refresh_servers()
        self.refresh_home()
        self.log(f"Añadido: {name} · {url}")

    def delete_server(self) -> None:
        index = self._selected_index()
        if index is None:
            self.log("Selecciona el servidor que quieres eliminar.")
            return
        if len(self.cfg["servers"]) == 1:
            self.log("Debe quedar al menos un servidor.")
            return
        removed = self.cfg["servers"].pop(index)
        if self.cfg["active"] == removed["name"]:
            self.cfg["active"] = self.cfg["servers"][0]["name"]
        save_config(self.repo, self.cfg)
        self.refresh_servers()
        self.refresh_home()
        self.log(f"Eliminado: {removed['name']}")

    def activate(self, name: str) -> None:
        self.cfg["active"] = name
        save_config(self.repo, self.cfg)
        self.refresh_servers()
        self.refresh_home()
        self.log(f"Servidor activo: {name}")

    def activate_selected(self) -> None:
        index = self._selected_index()
        if index is None:
            self.log("Selecciona un servidor.")
            return
        self.activate(self.cfg["servers"][index]["name"])

    def probe_selected(self) -> None:
        index = self._selected_index()
        if index is None:
            self.log("Selecciona un servidor para probarlo.")
            return
        self.probe_one(self.cfg["servers"][index]["url"])

    # --- sondeos ---

    def probe_one(self, url: str) -> None:
        self.status[url] = (False, "probando…")
        self.refresh_home()

        def work() -> None:
            ok, message = probe(url, self.log)

            def done() -> None:
                self.status[url] = (ok, message)
                self.refresh_home()

            self.ui(done)

        threading.Thread(target=work, daemon=True).start()

    def probe_all(self) -> None:
        for server in self.cfg["servers"]:
            self.probe_one(server["url"])

    # --- servidor: conexion con la base de datos ---

    def _build_connection(self):
        page = self.pages["servidor"]
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.page_title(page, "Servidor", "Conexion con la base de datos del servidor host.")

        body = tk.Frame(page, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", pady=(self.px(14), 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        datos_card, datos = self.card(body, "Datos del host")
        datos_card.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(6)))
        self.link_server = self.label(datos, "", size=12, color=CREAM, bold=True)
        self.link_server.pack(anchor="w")
        self.link_url = self.label(datos, "", size=9, color=MUTED, mono=True)
        self.link_url.pack(anchor="w", pady=(self.px(2), self.px(14)))

        self.label(datos, "Clave del panel", size=9, color=MUTED).pack(anchor="w")
        caja, self.link_token = self.field(datos, width=16)
        caja.pack(fill="x", pady=(self.px(4), self.px(14)))

        fila = tk.Frame(datos, bg=CARD)
        fila.pack(fill="x")
        self.connect_button = self.button(fila, "Conectar", self.connect_node, kind="primary")
        self.connect_button.pack(side="left", padx=(0, self.px(8)))
        self.button(fila, "Elegir servidor", lambda: self.show_page("servidores")).pack(side="left")

        self.link_status = self.label(datos, "●  sin conexion", size=9, color=MUTED)
        self.link_status.pack(anchor="w", pady=(self.px(18), 0))

        estado_card, estado = self.card(body, "Base de datos")
        estado_card.grid(row=0, column=1, sticky="nsew", padx=(self.px(6), 0))
        self.link_info = self.label(estado, "", size=10, color=MUTED)
        self.link_info.pack(anchor="w", pady=(0, self.px(16)))
        self.button(estado, "Abrir Registro", lambda: self.show_page("registro"),
                    kind="primary").pack(anchor="w")
        self.button(estado, "Actualizar", self.connect_node).pack(anchor="w", pady=(self.px(8), 0))

    def refresh_connection(self) -> None:
        server = active_server(self.cfg)
        if not server:
            self.link_server.config(text="Sin servidor")
            return
        self.link_server.config(text=server["name"])
        self.link_url.config(text=server["url"])
        self.link_token.delete(0, "end")
        self.link_token.insert(0, server.get("token", ""))
        if self.node is None:
            self.link_status.config(text="●  sin conexion", fg=MUTED)
            self.link_info.config(text="Conecta con el host para ver la base de datos.")

    def connect_node(self) -> None:
        server = active_server(self.cfg)
        if not server:
            self.log("No hay servidor configurado.")
            return
        server["token"] = self.link_token.get().strip()
        save_config(self.repo, self.cfg)
        self.link_status.config(text="●  conectando…", fg=GOLD)
        self.connect_button.set(text="Conectando…", state="disabled")
        url, token, name = server["url"], server["token"], server["name"]

        def work() -> None:
            node = Node(url, token)
            info = node.info()

            def done() -> None:
                self.node = node
                self.connect_button.set(text="Conectar", state="normal")
                self.link_status.config(text=f"●  conectado · {node.base}", fg=GREEN)
                database = info.get("database") or {}
                lineas = [
                    f"Nodo: {info.get('node') or name}",
                    f"Sistema: {info.get('system', '')}",
                    f"Disco libre: {human_size(info.get('disk_free', 0))}",
                    f"Cuentas: {database.get('users', 0)}",
                    f"Notificaciones: {database.get('notifications', 0)}",
                    f"Base de datos: {human_size(database.get('size', 0))}",
                    f"Discord: {'activo' if info.get('discord') else 'sin configurar'}",
                ]
                self.link_info.config(text="\n".join(lineas))
                self.log(f"Conectado a {name} · {node.base}")
                self.log(
                    f"  {database.get('users', 0)} cuentas · "
                    f"{database.get('notifications', 0)} notificaciones"
                )
                self.load_users()

            self.ui(done)

        def failed(message: str) -> None:
            def done() -> None:
                self.node = None
                self.connect_button.set(text="Conectar", state="normal")
                self.link_status.config(text=f"●  {message}", fg=RED)
                self.log(f"No se pudo conectar con {name}: {message}")

            self.ui(done)

        self.run_bg(work, failed)

    # --- registro: cuentas e historial de la base de datos ---

    def _build_registry(self):
        page = self.pages["registro"]
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.page_title(
            page, "Registro",
            "Cada cuenta con sus mensajes, sus imagenes y el resumen por aplicacion.",
        )

        body = tk.Frame(page, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", pady=(self.px(14), 0))
        body.columnconfigure(0, weight=0, minsize=self.px(280))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        cuentas_card, cuentas = self.card(body, "Cuentas")
        cuentas_card.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(6)))
        cuentas.columnconfigure(0, weight=1)
        cuentas.rowconfigure(1, weight=1)

        top = tk.Frame(cuentas, bg=CARD)
        top.grid(row=0, column=0, sticky="ew")
        self.registry_count = self.label(top, "sin conexion", size=9, color=MUTED)
        self.registry_count.pack(side="left")
        self.button(top, "Actualizar", self.load_users).pack(side="right")

        lista = RoundedBox(self, cuentas, fill=LOG_BG, outline=LINE, radius=10, padding=6)
        lista.grid(row=1, column=0, sticky="nsew", pady=(self.px(10), 0))
        self.user_list = tk.Listbox(
            lista.inner, bg=LOG_BG, fg=CREAM, selectbackground=GOLD, selectforeground=INK,
            bd=0, highlightthickness=0, font=self.fnt(9), activestyle="none",
            exportselection=False,
        )
        self.user_list.pack(fill="both", expand=True)
        self.user_list.bind("<<ListboxSelect>>", lambda _e: self.load_user_notifications())

        hist_card, hist = self.card(body, "Perfil del usuario")
        hist_card.grid(row=0, column=1, sticky="nsew", padx=(self.px(6), 0))
        hist.columnconfigure(0, weight=1)
        hist.rowconfigure(3, weight=1)

        self.registry_user = self.label(hist, "Selecciona una cuenta", size=12, color=CREAM, bold=True)
        self.registry_user.grid(row=0, column=0, sticky="w")
        self.registry_meta = self.label(hist, "", size=9, color=MUTED)
        self.registry_meta.grid(row=1, column=0, sticky="w", pady=(self.px(2), self.px(10)))

        tabs = tk.Frame(hist, bg=CARD)
        tabs.grid(row=2, column=0, sticky="ew")
        self.registry_tabs = {}
        for clave, texto in (("mensajes", "Mensajes"), ("imagenes", "Con imagen"), ("apps", "Por app")):
            boton = self.button(
                tabs, texto, lambda k=clave: self.set_registry_section(k),
                kind="primary" if clave == self.registry_section else "ghost",
                size=8, padx=12, pady=6,
            )
            boton.pack(side="left", padx=(0, self.px(6)))
            self.registry_tabs[clave] = boton

        busqueda = tk.Frame(hist, bg=CARD)
        busqueda.grid(row=3, column=0, sticky="new", pady=(self.px(10), 0))
        busqueda.columnconfigure(0, weight=1)
        caja, self.registry_query = self.field(busqueda, "", width=14)
        caja.grid(row=0, column=0, sticky="ew")
        self.registry_query.bind("<Return>", lambda _e: self.load_user_notifications())
        self.button(busqueda, "Buscar", self.load_user_notifications).grid(
            row=0, column=1, padx=(self.px(6), 0)
        )

        cuerpo = tk.Frame(hist, bg=CARD)
        cuerpo.grid(row=4, column=0, sticky="nsew", pady=(self.px(10), 0))
        hist.rowconfigure(4, weight=1)
        cuerpo.columnconfigure(0, weight=1)
        cuerpo.rowconfigure(0, weight=1)

        lista2 = RoundedBox(self, cuerpo, fill=LOG_BG, outline=LINE, radius=10, padding=6)
        lista2.grid(row=0, column=0, sticky="nsew")
        self.registry_list = tk.Listbox(
            lista2.inner, bg=LOG_BG, fg=CREAM, selectbackground=RAISED, selectforeground=CREAM,
            bd=0, highlightthickness=0, font=self.fnt(9, mono=True), activestyle="none",
            exportselection=False,
        )
        self.registry_list.pack(fill="both", expand=True)
        self.registry_list.bind("<<ListboxSelect>>", lambda _e: self.show_entry())

        preview = RoundedBox(self, cuerpo, fill=CARD, outline=LINE, radius=10, padding=8)
        preview.grid(row=1, column=0, sticky="ew", pady=(self.px(8), 0))
        self.registry_preview = tk.Text(
            preview.inner, bg=CARD, fg=CREAM, relief="flat", bd=0, wrap="word",
            font=self.fnt(9), height=4, highlightthickness=0, state="disabled",
        )
        self.registry_preview.pack(fill="both", expand=True)

        acciones = tk.Frame(cuerpo, bg=CARD)
        acciones.grid(row=2, column=0, sticky="ew", pady=(self.px(8), 0))
        self.image_button = self.button(acciones, "Ver imagen", self.view_image, kind="primary")
        self.image_button.pack(side="left", padx=(0, self.px(8)))
        self.image_button.set(state="disabled")
        self.button(acciones, "Copiar mensaje", self.copy_entry).pack(side="left")

    def set_registry_section(self, clave: str) -> None:
        self.registry_section = clave
        for nombre, boton in self.registry_tabs.items():
            boton.fade_to("primary" if nombre == clave else "ghost")
        self.load_user_notifications()

    def refresh_registry(self) -> None:
        if self.node is None:
            self.registry_count.config(text="conecta en la pagina Servidor", fg=MUTED)
            self.registry_user.config(text="Sin conexion")
            self.registry_meta.config(text="La base de datos se lee a traves del servidor.")
            self.user_list.delete(0, "end")
            self.registry_list.delete(0, "end")
            self.user_list.insert("end", "   Conecta primero con el servidor")
            return
        self.load_users()

    def load_users(self) -> None:
        node = self.node
        if node is None:
            self.refresh_registry()
            return

        def work() -> None:
            payload = node.admin_users()

            def done() -> None:
                self.users = payload.get("users") or []
                self.registry_index = 0
                self.user_list.delete(0, "end")
                self.registry_count.config(text=f"{len(self.users)} cuenta(s)", fg=MUTED)
                for user in self.users:
                    nombre = user.get("name") or "—"
                    correo = user.get("email") or "sin correo"
                    marca = " · discord" if user.get("discord") else ""
                    self.user_list.insert(
                        "end", f"{nombre} · {correo}{marca}  ({user.get('notifications', 0)})"
                    )
                if not self.users:
                    self.user_list.insert("end", "   Todavia no hay cuentas")
                    self.registry_user.config(text="Sin cuentas")
                    self.registry_meta.config(text="")
                    self.registry_list.delete(0, "end")
                    return
                self.user_list.selection_set(0)
                self.load_user_notifications()

            self.ui(done)

        self.run_bg(work, lambda message: self.log(f"Registro: {message}"))

    def load_user_notifications(self) -> None:
        node = self.node
        if node is None:
            return
        selection = self.user_list.curselection()
        index = selection[0] if selection else self.registry_index
        if index >= len(self.users):
            return
        self.registry_index = index
        user = self.users[index]
        query = self.registry_query.get().strip()

        def work() -> None:
            payload = node.admin_notifications(user["id"], query, 300)

            def done() -> None:
                self.registry_user.config(text=user.get("name") or user.get("email") or "Cuenta")
                creado = user.get("created_at") or 0
                fecha = time.strftime("%d/%m/%Y", time.localtime(creado)) if creado else "—"
                self.registry_meta.config(
                    text=(
                        f"{user.get('email') or 'sin correo'}  ·  "
                        f"discord: {'vinculado' if user.get('discord') else 'no'}  ·  "
                        f"alta {fecha}  ·  {payload.get('count', 0)} notificaciones"
                    )
                )
                self.registry_entries = payload.get("notifications") or []
                self.fill_registry_list()
                if self.registry_list.size():
                    self.registry_list.selection_set(0)
                    self.show_entry()

            self.ui(done)

        self.run_bg(work, lambda message: self.log(f"Historial: {message}"))

    def fill_registry_list(self) -> None:
        self.registry_list.delete(0, "end")
        self.registry_view = []
        kind = self.registry_section

        if kind == "apps":
            counts: dict = {}
            for item in self.registry_entries:
                clave = (item.get("app") or item.get("package") or "?", item.get("package") or "")
                datos = counts.setdefault(clave, {"total": 0, "ultimo": item})
                datos["total"] += 1
                if (item.get("posted_at") or 0) > (datos["ultimo"].get("posted_at") or 0):
                    datos["ultimo"] = item
            for (app, paquete), datos in sorted(counts.items(), key=lambda kv: -kv[1]["total"]):
                self.registry_view.append({"kind": "app", "app": app, "package": paquete, **datos})
                self.registry_list.insert("end", f"{app:<22} {datos['total']:>4} mensajes   ·  {paquete}")
            if not self.registry_view:
                self.registry_list.insert("end", "   Esta cuenta no tiene mensajes")
            return

        for item in self.registry_entries:
            if kind == "imagenes" and not item.get("image"):
                continue
            posted = item.get("posted_at") or 0
            hora = time.strftime("%d/%m %H:%M", time.localtime(posted / 1000)) if posted else "—"
            titulo = item.get("title") or ""
            app = (item.get("app") or item.get("package") or "?")[:16]
            icono = " [img]" if item.get("image") else ""
            self.registry_view.append({"kind": "nota", **item})
            self.registry_list.insert("end", f"{hora}  {app:<16}  {titulo[:60]}{icono}")
        if not self.registry_view:
            vacio = "Esta cuenta no tiene imagenes" if kind == "imagenes" else "Esta cuenta no tiene mensajes"
            self.registry_list.insert("end", f"   {vacio}")

    def _selected_entry(self):
        selection = self.registry_list.curselection()
        index = selection[0] if selection else 0
        if index >= len(self.registry_view):
            return None
        return self.registry_view[index]

    def show_entry(self) -> None:
        entry = self._selected_entry()
        self.registry_preview.configure(state="normal")
        self.registry_preview.delete("1.0", "end")
        if entry is None:
            self.registry_preview.configure(state="disabled")
            self.image_button.set(state="disabled")
            return
        if entry.get("kind") == "app":
            self.registry_preview.insert("end", f"{entry['app']}\n")
            self.registry_preview.insert("end", f"{entry['total']} mensajes guardados\n")
            self.registry_preview.insert(
                "end", f"Ultimo: {entry['ultimo'].get('title') or '(sin titulo)'}\n"
            )
            self.registry_preview.insert("end", f"Paquete: {entry['package']}")
            self.image_button.set(state="disabled")
        else:
            cuerpo = entry.get("big") or entry.get("text") or entry.get("sub") or "(sin texto)"
            self.registry_preview.insert("end", f"{entry.get('title') or ''}\n")
            self.registry_preview.insert("end", f"{cuerpo}\n\n")
            self.registry_preview.insert(
                "end",
                f"{entry.get('app') or ''} · {entry.get('package') or ''} · "
                f"{entry.get('category') or 'sin categoria'}",
            )
            self.image_button.set(state="normal" if entry.get("image") else "disabled")
        self.registry_preview.configure(state="disabled")

    def view_image(self) -> None:
        entry = self._selected_entry()
        if not entry or not entry.get("image"):
            return
        try:
            blob = base64.b64decode(entry["image"])
            folder = Path(tempfile.gettempdir()) / "ryx-imagenes"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{entry.get('uuid') or 'imagen'}.png"
            target.write_bytes(blob)
            os.startfile(str(target))  # type: ignore[attr-defined]
            self.log(f"Imagen abierta: {target.name}")
        except Exception as error:
            self.log(f"No se pudo abrir la imagen: {error}")

    def copy_entry(self) -> None:
        entry = self._selected_entry()
        if not entry or entry.get("kind") == "app":
            return
        texto = "\n".join(
            parte for parte in (
                entry.get("title") or "", entry.get("big") or entry.get("text") or "",
                f"{entry.get('app') or ''} · {time.strftime('%d/%m/%Y %H:%M', time.localtime((entry.get('posted_at') or 0) / 1000))}",
            ) if parte
        )
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(texto)
            self.log("Mensaje copiado al portapapeles.")
        except Exception:
            self.log("No se pudo copiar el mensaje.")

    # --- APK ---

    def _build_apk(self):
        page = self.pages["apk"]
        page.columnconfigure(0, weight=1)
        self.page_title(page, "APK", "Se compila en este PC con la IP del servidor activo dentro.")

        card, body = self.card(page, "Compilacion")
        card.grid(row=1, column=0, sticky="ew", pady=(self.px(14), 0))
        body.columnconfigure(2, weight=1)

        self.apk_server_label = self.label(body, "", size=10, color=GOLD)
        self.apk_server_label.grid(row=0, column=0, columnspan=3, sticky="w")

        self.label(body, "Version visible", size=9, color=MUTED).grid(
            row=1, column=0, sticky="w", pady=(self.px(14), 0)
        )
        self.label(body, "versionCode", size=9, color=MUTED).grid(
            row=1, column=1, sticky="w", padx=(self.px(16), 0), pady=(self.px(14), 0)
        )
        box, self.version_entry = self.field(body, str(self.cfg["versionName"]), width=14)
        box.grid(row=2, column=0, sticky="w", pady=(self.px(4), 0))
        box2, self.code_entry = self.field(body, str(self.cfg["versionCode"]), width=8)
        box2.grid(row=2, column=1, sticky="w", padx=(self.px(16), 0), pady=(self.px(4), 0))

        buttons = tk.Frame(body, bg=CARD)
        buttons.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(self.px(18), 0))
        self.build_button = self.button(buttons, "Compilar APK", self.start_build, kind="primary")
        self.build_button.pack(side="left", padx=(0, self.px(8)))
        self.button(buttons, "Abrir carpeta de APKs", self.open_out).pack(side="left", padx=(0, self.px(8)))
        self.button(buttons, "Cambiar servidor activo", lambda: self.show_page("servidores")).pack(side="left")

        self.build_bar = ProgressBar(self, body, height=6)
        self.build_bar.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(self.px(12), 0))

        self.apk_hint = self.label(page, "", size=8, color=MUTED, bg=BG)
        self.apk_hint.grid(row=2, column=0, sticky="w", pady=(self.px(12), 0))

    def refresh_apk(self) -> None:
        server = active_server(self.cfg)
        if server:
            self.apk_server_label.config(text=f"Servidor activo: {server['name']} · {server['url']}")
        out_dir = self.repo / "panel" / "out"
        apks = sorted(out_dir.glob("*.apk")) if out_dir.exists() else []
        self.apk_hint.config(
            text=f"Salida: {out_dir}" + (f"   ·   ultimo: {apks[-1].name}" if apks else "")
        )
        self.version_entry.delete(0, "end")
        self.version_entry.insert(0, str(self.cfg["versionName"]))
        self.code_entry.delete(0, "end")
        self.code_entry.insert(0, str(self.cfg["versionCode"]))

    def start_build(self) -> None:
        if not active_server(self.cfg):
            self.log("No hay servidor configurado.")
            return
        code_text = self.code_entry.get().strip()
        if not code_text.isdigit():
            self.log("El versionCode debe ser un numero (por ejemplo 15).")
            return
        self.cfg["versionName"] = self.version_entry.get().strip() or "1.0.0"
        self.cfg["versionCode"] = int(code_text)
        save_config(self.repo, self.cfg)
        self.build_button.set(text="Compilando…", state="disabled")
        self.build_bar.start()

        def work() -> None:
            target = build(self.repo, self.cfg, self.log)

            def done() -> None:
                self.build_bar.stop()
                self.build_button.set(text="Compilar APK", state="normal")
                self.refresh_apk()
                self.refresh_home()
                if target:
                    self.log(f"Listo para instalar: {target.name}")

            self.ui(done)

        threading.Thread(target=work, daemon=True).start()

    def open_out(self) -> None:
        folder = self.repo / "panel" / "out"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except Exception:
            self.log(f"Carpeta: {folder}")

    # --------------------------------- consola ------------------------------

    def clear_console(self) -> None:
        if self.console is None:
            return
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def write_console(self, message: str) -> None:
        if self.console is None:
            return
        self.console.configure(state="normal")
        self.console.insert("end", f"{time.strftime('%H:%M:%S')}  {message}\n")
        self.console.configure(state="disabled")
        self.console.see("end")

    def _drain(self) -> None:
        try:
            while True:
                callback = self.ui_queue.get_nowait()
                try:
                    callback()
                except Exception as error:
                    self.messages.put(f"Error interno: {error}")
        except queue.Empty:
            pass
        try:
            while True:
                self.write_console(self.messages.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self._drain)


# ------------------------------- modo consola --------------------------------

def run_console(repo: Path) -> None:
    cfg = load_config(repo)
    while True:
        server = active_server(cfg)
        print()
        print(f"=== Panel {APP} ===")
        print(f"Activo: {server['name']} · {server['url']}" if server else "Sin servidor")
        for index, item in enumerate(cfg["servers"]):
            mark = "*" if server and item["name"] == server["name"] else " "
            print(f"  {mark} {index + 1}) {item['name']}: {item['url']}")
        print(f"Version: {cfg['versionName']} (versionCode {cfg['versionCode']})")
        print("a) Añadir   e) Editar   x) Eliminar   u) Usar   p) Probar")
        print("c) Compilar APK   o) Abrir carpeta   0) Salir")
        option = input("Opcion: ").strip().lower()
        if option in {"a", "e"}:
            index = None
            if option == "e":
                picked = input("Numero de servidor: ").strip()
                index = int(picked) - 1 if picked.isdigit() and 1 <= int(picked) <= len(cfg["servers"]) else None
                if index is None:
                    print("Numero no valido.")
                    continue
            old = cfg["servers"][index] if index is not None else {"name": "", "url": "", "token": ""}
            name = input(f"Nombre [{old['name']}]: ").strip() or old["name"] or f"Servidor {len(cfg['servers']) + 1}"
            url = normalize_server(input(f"Direccion [{old['url']}]: ").strip() or old["url"])
            token = input(f"Clave [{old.get('token', '')}]: ").strip() or old.get("token", "")
            if not url:
                print("Direccion no valida.")
                continue
            if index is None:
                cfg["servers"].append({"name": name, "url": url, "token": token})
            else:
                was_active = cfg["active"] == old["name"]
                cfg["servers"][index] = {"name": name, "url": url, "token": token}
                if was_active:
                    cfg["active"] = name
            save_config(repo, cfg)
            print("Guardado.")
        elif option == "x":
            picked = input("Numero de servidor a eliminar: ").strip()
            if picked.isdigit() and 1 <= int(picked) <= len(cfg["servers"]) and len(cfg["servers"]) > 1:
                removed = cfg["servers"].pop(int(picked) - 1)
                if cfg["active"] == removed["name"]:
                    cfg["active"] = cfg["servers"][0]["name"]
                save_config(repo, cfg)
                print(f"Eliminado: {removed['name']}")
            else:
                print("Numero no valido (debe quedar al menos uno).")
        elif option == "u":
            picked = input("Numero de servidor a usar: ").strip()
            if picked.isdigit() and 1 <= int(picked) <= len(cfg["servers"]):
                cfg["active"] = cfg["servers"][int(picked) - 1]["name"]
                save_config(repo, cfg)
                print(f"Activo: {cfg['active']}")
            else:
                print("Numero no valido.")
        elif option == "p":
            for item in cfg["servers"]:
                probe(item["url"])
        elif option == "c":
            build(repo, cfg)
        elif option == "o":
            folder = repo / "panel" / "out"
            folder.mkdir(parents=True, exist_ok=True)
            try:
                os.startfile(folder)  # type: ignore[attr-defined]
            except Exception:
                print(f"Carpeta: {folder}")
        elif option == "0":
            return
        else:
            print("Opcion no valida.")


def main() -> None:
    repo = find_repo()
    if "--check" in sys.argv:
        cfg = load_config(repo)
        print(f"Proyecto: {repo}")
        for item in cfg["servers"]:
            print(f"Servidor: {item['name']} · {item['url']}")
        print(f"Activo:   {cfg['active']}")
        print(f"Version:  {cfg['versionName']} (versionCode {cfg['versionCode']})")
        return
    if "--console" in sys.argv:
        run_console(repo)
        return
    Panel(repo, selftest="--selftest" in sys.argv)


if __name__ == "__main__":
    main()
