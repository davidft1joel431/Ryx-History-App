#!/usr/bin/env python3
"""Panel de control de RyxHistory (solo para el PC del dueno).

Interfaz grafica para cambiar la direccion del servidor, comprobarla y compilar
el APK con esa direccion. Usa el JDK y el SDK de Android del equipo: no necesita
internet ni tokens.

Modos: sin argumentos abre la ventana; --console es el menu de texto;
--check imprime la configuracion y --selftest comprueba que la ventana se crea.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

APP = "RyxHistory"
DEFAULT_SERVER = "https://CAMBIA-ESTO.example.com"
TIMEOUT = 8

BG = "#14100C"
CARD = "#1E1812"
RAISED = "#2A2118"
GOLD = "#FFC400"
ORANGE = "#FF8A00"
GREEN = "#1FD34A"
RED = "#FF5A4D"
CREAM = "#FFF6DC"
MUTED = "#B8A98A"


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


def load_config(repo: Path) -> dict:
    data = {"server": DEFAULT_SERVER, "versionName": "1.0.5", "versionCode": 15}
    path = config_path(repo)
    if path.exists():
        try:
            data.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return data


def save_config(repo: Path, data: dict) -> None:
    path = config_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


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


# --------------------------------- acciones ---------------------------------

def probe(server: str, log=print) -> bool:
    log(f"Probando {server} ...")
    for path in ("/api/health", "/health", "/"):
        url = server + path
        started = time.time()
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
                log(f"OK   {url} -> HTTP {response.status} ({int((time.time() - started) * 1000)} ms)")
                return True
        except urllib.error.HTTPError as error:
            log(f"OK   {url} -> HTTP {error.code} ({int((time.time() - started) * 1000)} ms): responde")
            return True
        except Exception as error:
            log(f"--   {url} -> {error}")
    log("No respondio: revisa la IP, el puerto o si el servidor esta encendido.")
    return False


def build(repo: Path, cfg: dict, log=print) -> Path | None:
    code = int(cfg["versionCode"])
    name = str(cfg["versionName"])
    log(f"Compilando {APP} {name} (versionCode {code}) para {cfg['server']} ...")
    env = os.environ.copy()
    env.update(SERVER_URL=str(cfg["server"]), APP_VERSION_NAME=name, APP_VERSION_CODE=str(code))
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


# ---------------------------------- ventana ----------------------------------

def run_gui(repo: Path, selftest: bool = False) -> None:
    import tkinter as tk
    from tkinter import messagebox

    cfg = load_config(repo)
    messages: queue.Queue[str] = queue.Queue()

    def log(message: str) -> None:
        messages.put(message)

    root = tk.Tk()
    root.title(f"{APP} · Panel de control")
    root.configure(bg=BG)
    root.geometry("920x680")
    root.minsize(820, 600)

    def label(parent, text, size=10, color=CREAM, bold=False, bg=CARD):
        return tk.Label(
            parent, text=text, bg=bg, fg=color, anchor="w", justify="left",
            font=("Segoe UI", size, "bold" if bold else "normal"),
        )

    def entry(parent, value, width=30):
        widget = tk.Entry(
            parent, bg=RAISED, fg=CREAM, insertbackground=CREAM, relief="flat", bd=0,
            font=("Consolas", 10), width=width,
            highlightthickness=1, highlightbackground=RAISED, highlightcolor=GOLD,
        )
        widget.insert(0, value)
        return widget

    def button(parent, text, command, primary=False, width=None):
        widget = tk.Button(
            parent, text=text, command=command, relief="flat", bd=0, cursor="hand2",
            bg=GOLD if primary else RAISED, fg="#14100C" if primary else CREAM,
            activebackground=ORANGE if primary else RAISED, activeforeground="#14100C",
            padx=16, pady=9, font=("Segoe UI", 10, "bold" if primary else "normal"),
            highlightthickness=0,
        )
        if width:
            widget.config(width=width)
        return widget

    def card(parent, title):
        frame = tk.Frame(parent, bg=CARD, highlightbackground=RAISED, highlightthickness=1)
        label(frame, title.upper(), size=9, color=GOLD, bold=True).pack(anchor="w", padx=18, pady=(14, 8))
        body = tk.Frame(frame, bg=CARD)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        return frame, body

    # --- cabecera con el logo ---
    header = tk.Frame(root, bg=BG)
    header.pack(fill="x", padx=24, pady=(18, 12))
    try:
        raw = tk.PhotoImage(file=str(repo / "app" / "src" / "main" / "res" / "drawable-nodpi" / "logo.png"))
        logo = raw.subsample(4, 4)
        logo_widget = tk.Label(header, image=logo, bg=BG)
        logo_widget.image = logo
        logo_widget.pack(side="left", padx=(0, 16))
        root.iconphoto(True, logo)
    except Exception:
        pass

    titles = tk.Frame(header, bg=BG)
    titles.pack(side="left")
    tk.Label(titles, text=APP, bg=BG, fg=GOLD, font=("Segoe UI", 22, "bold")).pack(anchor="w")
    tk.Label(
        titles, text="Panel de control · servidor y APK", bg=BG, fg=MUTED, font=("Segoe UI", 9)
    ).pack(anchor="w")

    server_shown = tk.Label(header, text=cfg["server"], bg=BG, fg=MUTED, font=("Consolas", 9))
    server_shown.pack(side="right", anchor="e")

    # --- tarjetas ---
    top = tk.Frame(root, bg=BG)
    top.pack(fill="x", padx=24)
    top.columnconfigure(0, weight=1)
    top.columnconfigure(1, weight=1)

    # servidor
    server_card, server_body = card(top, "Servidor")
    server_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    label(server_body, "Direccion del servidor", size=9, color=MUTED).pack(anchor="w")
    server_entry = entry(server_body, cfg["server"])
    server_entry.pack(fill="x", pady=(6, 12), ipady=3)

    status = tk.Label(server_body, text="●  Sin probar", bg=CARD, fg=MUTED, font=("Segoe UI", 9))
    status.pack(anchor="w", pady=(0, 8))

    def set_status(text: str, color: str) -> None:
        status.config(text=f"●  {text}", fg=color)

    def save_server() -> None:
        url = normalize_server(server_entry.get())
        if not url:
            messagebox.showerror(APP, "Direccion no valida.\nEjemplo: https://midominio.com o 192.168.1.10:3000")
            return
        cfg["server"] = url
        save_config(repo, cfg)
        server_entry.delete(0, "end")
        server_entry.insert(0, url)
        server_shown.config(text=url)
        set_status("Guardado, sin probar", MUTED)
        log(f"Servidor guardado: {url}")

    def test_server() -> None:
        url = normalize_server(server_entry.get())
        if not url:
            messagebox.showerror(APP, "Direccion no valida.")
            return
        set_status("Probando…", GOLD)
        test_button.config(state="disabled")

        def work() -> None:
            ok = probe(url, log)

            def done() -> None:
                set_status("En linea" if ok else "Sin respuesta", GREEN if ok else RED)
                test_button.config(state="normal")

            root.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    server_buttons = tk.Frame(server_body, bg=CARD)
    server_buttons.pack(fill="x")
    test_button = button(server_buttons, "Probar servidor", test_server)
    test_button.pack(side="left", padx=(0, 8))
    button(server_buttons, "Guardar", save_server).pack(side="left")
    label(
        server_body, "La app tambien permite cambiarla desde el menu ⋮.", size=8, color=MUTED
    ).pack(anchor="w", pady=(10, 0))

    # APK
    apk_card, apk_body = card(top, "APK")
    apk_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
    fields = tk.Frame(apk_body, bg=CARD)
    fields.pack(fill="x")
    fields.columnconfigure(0, weight=2)
    fields.columnconfigure(1, weight=1)
    label(fields, "Version visible", size=9, color=MUTED).grid(row=0, column=0, sticky="w")
    label(fields, "versionCode", size=9, color=MUTED).grid(row=0, column=1, sticky="w", padx=(10, 0))
    version_entry = entry(fields, cfg["versionName"], width=12)
    version_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0), ipady=3)
    code_entry = entry(fields, str(cfg["versionCode"]), width=8)
    code_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(4, 0), ipady=3)

    def open_out() -> None:
        folder = repo / "panel" / "out"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except Exception:
            log(f"Carpeta: {folder}")

    def start_build() -> None:
        url = normalize_server(server_entry.get())
        if not url:
            messagebox.showerror(APP, "Revisa la direccion del servidor.")
            return
        code_text = code_entry.get().strip()
        if not code_text.isdigit():
            messagebox.showerror(APP, "El versionCode debe ser un numero (por ejemplo 15).")
            return
        cfg["server"] = url
        cfg["versionName"] = version_entry.get().strip() or "1.0.0"
        cfg["versionCode"] = int(code_text)
        save_config(repo, cfg)
        set_status("Compilando…", GOLD)
        build_button.config(state="disabled", text="Compilando…")

        def work() -> None:
            target = build(repo, cfg, log)

            def done() -> None:
                build_button.config(state="normal", text="Compilar APK")
                if target:
                    set_status("APK listo", GREEN)
                    code_entry.delete(0, "end")
                    code_entry.insert(0, str(cfg["versionCode"]))
                    messagebox.showinfo(APP, f"APK generado:\n{target}")
                else:
                    set_status("Error al compilar", RED)

            root.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    apk_buttons = tk.Frame(apk_body, bg=CARD)
    apk_buttons.pack(fill="x", pady=(14, 0))
    build_button = button(apk_buttons, "Compilar APK", start_build, primary=True)
    build_button.pack(fill="x", pady=(0, 8))
    button(apk_buttons, "Abrir carpeta de APKs", open_out).pack(fill="x")

    # --- registro ---
    log_card, log_body = card(root, "Registro")
    log_card.pack(fill="both", expand=True, padx=24, pady=(16, 22))
    log_text = tk.Text(
        log_body, bg="#0F0C09", fg="#D9CDB4", insertbackground=CREAM, relief="flat", bd=0,
        font=("Consolas", 9), wrap="word", height=10, highlightthickness=0,
    )
    scrollbar = tk.Scrollbar(
        log_body, command=log_text.yview, bg=RAISED, activebackground=GOLD, troughcolor="#0F0C09",
        bd=0, relief="flat", highlightthickness=0, width=10,
    )
    log_text.configure(yscrollcommand=scrollbar.set, state="disabled")
    scrollbar.pack(side="right", fill="y")
    log_text.pack(side="left", fill="both", expand=True)

    footer = tk.Frame(root, bg=BG)
    footer.pack(fill="x", padx=24, pady=(0, 12))
    label(footer, f"Proyecto: {repo}", size=8, color=MUTED, bg=BG).pack(side="left")

    def drain() -> None:
        wrote = False
        try:
            while True:
                text = messages.get_nowait()
                log_text.configure(state="normal")
                log_text.insert("end", text + "\n")
                wrote = True
        except queue.Empty:
            pass
        if wrote:
            log_text.see("end")
            log_text.configure(state="disabled")
        root.after(120, drain)

    log(f"Panel listo. Servidor: {cfg['server']}")
    log(f"Proyecto: {repo}")
    root.after(120, drain)

    if selftest:
        root.update()
        folder = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
        (folder / "gui-selftest.txt").write_text(
            f"OK {root.winfo_width()}x{root.winfo_height()}\n", encoding="utf-8"
        )
        root.destroy()
        return

    root.mainloop()


# ------------------------------- modo consola --------------------------------

def run_console(repo: Path) -> None:
    cfg = load_config(repo)
    while True:
        print()
        print(f"=== Panel {APP} ===")
        print(f"Proyecto: {repo}")
        print(f"Servidor: {cfg['server']}")
        print(f"Version:  {cfg['versionName']} (versionCode {cfg['versionCode']})")
        print("1) Cambiar servidor   2) Probar servidor   3) Cambiar version")
        print("4) Compilar APK       5) Abrir carpeta      0) Salir")
        option = input("Opcion: ").strip()
        if option == "1":
            server = normalize_server(input("Nueva direccion: "))
            if not server:
                print("Direccion no valida.")
                continue
            cfg["server"] = server
            save_config(repo, cfg)
            print(f"Guardado: {server}")
        elif option == "2":
            probe(str(cfg["server"]))
        elif option == "3":
            name = input(f"Version visible [{cfg['versionName']}]: ").strip()
            code = input(f"versionCode [{cfg['versionCode']}]: ").strip()
            if name:
                cfg["versionName"] = name
            if code.isdigit():
                cfg["versionCode"] = int(code)
            save_config(repo, cfg)
        elif option == "4":
            build(repo, cfg)
        elif option == "5":
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
        print(f"Servidor: {cfg['server']}")
        print(f"Version:  {cfg['versionName']} (versionCode {cfg['versionCode']})")
        return
    if "--console" in sys.argv:
        run_console(repo)
        return
    run_gui(repo, selftest="--selftest" in sys.argv)


if __name__ == "__main__":
    main()
