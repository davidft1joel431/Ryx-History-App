# Servidor RyxHistory

Cada servidor solo guarda la base de datos, así que aquí está el agente que el
panel **RyxHistory.exe** usa para conectarse, ver el estado y transferir
archivos (subir, descargar, crear carpetas, borrar).

## Arrancar en el servidor

```
python ryx_server.py --root C:\ryx --port 8787
```

La primera vez genera una clave y la guarda en `ryx_token.txt` (también la
muestra en pantalla). Esa clave es la que se escribe en el panel, en la página
**Servidor**.

Opciones: `--root` carpeta visible, `--port` puerto, `--host` interfaz,
`--token` clave fija, `--node` nombre del servidor.

Si el servidor tiene delante un proxy o firewall, deja abierto el puerto 8787
(o el que elijas) y publica el dominio con ese puerto.

## Rutas

| Método | Ruta | Uso |
| --- | --- | --- |
| GET | `/api/ping` | Comprobar que el agente responde (sin clave) |
| GET | `/api/info` | Nodo, sistema, disco, bases de datos |
| GET | `/api/list?path=` | Listar una carpeta |
| GET | `/api/download?path=` | Descargar un archivo |
| POST | `/api/upload?path=` | Subir un archivo (cuerpo = bytes) |
| POST | `/api/mkdir?path=` | Crear carpeta |
| POST | `/api/delete?path=` | Borrar archivo o carpeta (`&recursive=1`) |
| POST | `/api/rename?path=&to=` | Renombrar o mover |

Todas salvo `/api/ping` piden la cabecera `X-Ryx-Token`.
