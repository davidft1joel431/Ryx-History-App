# Servidor RyxHistory

Un solo proceso en el servidor host hace las tres cosas:

- **Base de datos de la app** (SQLite en `<root>/ryx.db`): cuentas, sesiones,
  dispositivos y notificaciones sincronizadas.
- **API que usa el APK**: registro, entrada, refresco de sesión, `/api/sync` y
  borrado del historial.
- **Inicio de sesión con Discord** (OAuth2), usando la dirección de este
  servidor como `redirect_uri`.
- **Agente del panel** `RyxHistory.exe`: estado, listado y transferencia de
  archivos con clave.

## Arrancar

```
python ryx_server.py --root C:\ryx --port 8787
```

La primera vez genera la clave del panel y la guarda en `ryx_token.txt` (también
la muestra en pantalla). Esa clave se escribe en el panel, página **Servidor**.

Opciones: `--root` carpeta del servidor, `--port` puerto, `--host` interfaz,
`--token` clave fija, `--node` nombre, `--db` archivo SQLite,
`--public-url` dirección pública (si hay proxy delante).

Deja abierto el puerto 8787 (o el que elijas) en el firewall del servidor.

## Discord

1. En <https://discord.com/developers/applications> crea una aplicación →
   **OAuth2** → copia **Client ID** y **Client Secret**.
2. En **Redirects** añade exactamente:

   ```
   http://TU-IP-O-DOMINIO:8787/auth/discord/callback
   ```

   El servidor imprime la línea que debes registrar al arrancar.
3. Arranca con las credenciales:

   ```
   python ryx_server.py --root C:\ryx --port 8787 ^
     --discord-id 1234567890 --discord-secret xxxxx
   ```

   También valen las variables `RYX_DISCORD_ID` y `RYX_DISCORD_SECRET`.

**Si Discord rechaza la URL** (`Invalid OAuth2 redirect_uri`): Discord exige
HTTPS en los redirects, salvo `localhost`/`127.0.0.1`. Con una IP suelta y
`http://` puede no dejarte guardarla. En ese caso pon un proxy con HTTPS
(Caddy, Nginx) delante del 8787, registra `https://tudominio.com/auth/discord/callback`
y arranca con `--public-url https://tudominio.com`. El resto de la app puede
seguir hablando por `http://IP:8787` sin problema (el APK permite tráfico sin TLS).

## La app apunta a la IP del servidor

En el panel, página **Servidores**, la dirección del servidor activo se escribe
como `http://192.168.1.10:8787` (o `https://dominio.com`). Al compilar el APK,
esa dirección queda dentro de la app (`SERVER_URL`), así que la base de datos y
el login de Discord usan ese mismo servidor. También se puede cambiar luego en
la app: Ajustes → servidor.

## Rutas

| Método | Ruta | Uso |
| --- | --- | --- |
| GET | `/api/ping` | Comprobar que responde (sin clave) |
| GET | `/auth/discord/start?app_state=` | Abre Discord y vuelve al callback |
| GET | `/auth/discord/callback` | Discord vuelve aquí y redirige a `ryxhistory://` |
| POST | `/api/auth/register` | `{email, password, name}` → sesión |
| POST | `/api/auth/login` | `{email, password}` → sesión |
| POST | `/api/auth/refresh` | `{refreshToken}` → sesión nueva |
| POST | `/api/auth/logout` | `{refreshToken}` |
| POST | `/api/auth/discord/exchange` | `{code}` → sesión |
| POST | `/api/sync` | `{device, notifications[]}` → `{accepted:[uuid]}` |
| DELETE | `/api/me/history` | Borra el historial de la cuenta |
| GET | `/api/info` | Nodo, disco, base de datos, Discord (clave del panel) |
| GET | `/api/list?path=` | Listar una carpeta (clave del panel) |
| GET | `/api/download?path=` | Descargar un archivo (clave del panel) |
| POST | `/api/upload?path=` | Subir un archivo (clave del panel) |
| POST | `/api/mkdir?path=` | Crear carpeta (clave del panel) |
| POST | `/api/delete?path=` | Borrar archivo o carpeta (clave del panel) |
| POST | `/api/rename?path=&to=` | Renombrar o mover (clave del panel) |

Las rutas de sesión usan `Authorization: Bearer <accessToken>`; las de archivos,
la cabecera `X-Ryx-Token`.

## Copia de la base de datos

La base de datos es un archivo: cópiala con el servidor parado, o desde el panel
(página **Servidor** → carpeta `ryx.db` → **Descargar**). Las copias `-wal` y
`-shm` solo hacen falta si el servidor está en marcha.
