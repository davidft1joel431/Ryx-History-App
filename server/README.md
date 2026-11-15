# Servidor RyxHistory

Un solo proceso en el servidor host hace dos cosas:

- **Base de datos de la app** (SQLite en `<root>/ryx.db`): cuentas, sesiones,
  dispositivos y notificaciones sincronizadas (con texto completo e imagen).
- **API que usa el APK**: registro, entrada, refresco de sesión, `/api/sync`,
  perfil (`/api/me`), vínculo con Discord y borrado del historial.

El panel `RyxPanel.exe` ya **no** administra archivos del disco: solo se conecta
como base de datos para leer las cuentas, sus mensajes por sección y las
imágenes guardadas.

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

Con Discord configurado la app puede entrar con Discord o vincular Discord a una
cuenta creada con correo y contraseña (perfil → **Vincular mi Discord**).

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
el login de Discord usan ese mismo servidor. La app no permite cambiarla después.

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
| POST | `/api/auth/discord/link` | Vincula Discord a la cuenta de la sesión (devuelve la URL) |
| GET | `/api/me` | Perfil: nombre, correo, Discord vinculado, contadores |
| POST | `/api/sync` | `{device, notifications[]}` → `{accepted:[uuid]}` |
| DELETE | `/api/me/history` | Borra el historial de la cuenta |
| GET | `/api/info` | Nodo, disco, base de datos, Discord (clave del panel) |
| GET | `/api/admin/users` | Cuentas con sus contadores (clave del panel) |
| GET | `/api/admin/notifications?user=&q=&limit=` | Historial de una cuenta (clave del panel) |

Las rutas de la app usan `Authorization: Bearer <accessToken>`; las del panel,
la cabecera `X-Ryx-Token`.

## Seguridad

- La API nunca devuelve rutas del disco: `/api/info` solo da nombres y tamaños.
- La clave del panel viaja solo en la cabecera `X-Ryx-Token` (nunca en la URL) y
  se compara en tiempo constante.
- Límites por IP: 300 peticiones por minuto en general, 8 intentos de entrada por
  cada 5 minutos y 5 registros por cada 15 minutos; al pasarse, la IP queda
  bloqueada un rato y la respuesta es 429.
- Contraseñas con PBKDF2-SHA256 (120 000 vueltas y sal por cuenta); las sesiones
  se guardan como hash y caducan (30 días el acceso, 180 el refresco).
- Los mensajes de error no incluyen trazas ni rutas, y las páginas HTML se sirven
  con CSP, `X-Frame-Options: DENY` y `nosniff`.

## Copia de la base de datos

La base de datos es un archivo: con el servidor parado copia `<root>/ryx.db`.
Las copias `-wal` y `-shm` solo hacen falta si el servidor está en marcha.
