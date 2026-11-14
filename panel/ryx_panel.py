#!/usr/bin/env python3
"""Panel de consola de RyxHistory (solo para el PC del dueno).

Sirve para cambiar la direccion del servidor, comprobar que responde y compilar
el APK con esa direccion dentro. No necesita internet ni tokens: usa el JDK y el
SDK de Android que ya estan instalados en el equipo.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

APP = "RyxHistory"
DEFAULT_SERVER = "https://CAMBIA-ESTO.example.com"
TIMEOUT = 8


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


def probe(server: str) -> None:
    print(f"Probando {server} ...")
    for path in ("/api/health", "/health", "/"):
        url = server + path
        started = time.time()
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
                ms = int((time.time() - started) * 1000)
                print(f"  OK  {url} -> HTTP {response.status} ({ms} ms)")
                return
        except urllib.error.HTTPError as error:
            ms = int((time.time() - started) * 1000)
            print(f"  OK  {url} -> HTTP {error.code} ({ms} ms): el servidor responde")
            return
        except Exception as error:
            print(f"  --  {url} -> {error}")
    print("  El servidor no respondio: revisa la IP, el puerto o si esta encendido.")


def build(repo: Path, cfg: dict) -> None:
    code = int(cfg["versionCode"])
    name = str(cfg["versionName"])
    print(f"Compilando {APP} {name} (versionCode {code}) para {cfg['server']} ...")
    env = os.environ.copy()
    env.update(
        SERVER_URL=str(cfg["server"]),
        APP_VERSION_NAME=name,
        APP_VERSION_CODE=str(code),
    )
    cmd = [
        os.environ.get("COMSPEC", "cmd.exe"), "/c",
        str(repo / "gradlew.bat"), "assembleRelease", "--no-daemon", "--console=plain",
    ]
    if subprocess.run(cmd, cwd=str(repo), env=env).returncode != 0:
        print("La compilacion fallo. Revisa el mensaje de Gradle de arriba.")
        return
    apks = sorted((repo / "app" / "build" / "outputs" / "apk" / "release").glob("*.apk"))
    if not apks:
        print("No encuentro el APK generado.")
        return
    out_dir = repo / "panel" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{APP}-{name}.apk"
    shutil.copy2(apks[-1], target)
    cfg["versionCode"] = code + 1
    save_config(repo, cfg)
    print(f"APK listo: {target}")
    print(f"La proxima compilacion usara versionCode {cfg['versionCode']}.")


def show(cfg: dict, repo: Path) -> None:
    print(f"Proyecto: {repo}")
    print(f"Servidor: {cfg['server']}")
    print(f"Version:  {cfg['versionName']} (versionCode {cfg['versionCode']})")


def main() -> None:
    repo = find_repo()
    cfg = load_config(repo)
    if "--check" in sys.argv:
        show(cfg, repo)
        return
    while True:
        print()
        print(f"=== Panel {APP} ===")
        show(cfg, repo)
        print("1) Cambiar servidor (IP/URL)")
        print("2) Probar servidor")
        print("3) Cambiar version del APK")
        print("4) Compilar APK")
        print("5) Abrir carpeta de APKs")
        print("0) Salir")
        option = input("Opcion: ").strip()
        if option == "1":
            server = normalize_server(input("Nueva direccion (ej. https://midominio.com o 192.168.1.10:3000): "))
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


if __name__ == "__main__":
    main()
