# Ryx History · App Android

Guarda el historial de notificaciones del teléfono y lo sincroniza con tu servidor Ryx History.
Kotlin · Jetpack Compose · Room · WorkManager. Android 8.0+ (API 26).

## Subir al repositorio con GitHub Desktop
1. **File → Clone repository** → `davidft1joel431/Ryx-History-App`.
2. Copia **todo el contenido de esta carpeta** dentro de la carpeta clonada (incluida `.github/`, que puede estar oculta).
3. En GitHub Desktop: escribe un mensaje → **Commit to main** → **Push origin**.

## Configurar los Secrets (una sola vez)
En GitHub: repositorio → **Settings → Secrets and variables → Actions → New repository secret**.

| Secret | Valor |
|---|---|
| `SERVER_URL` | `https://api.tudominio.com` (el mismo de `BASE_URL` del servidor, sin `/` final) |
| `KEYSTORE_BASE64` | tu clave de firma convertida a texto (ver abajo) |
| `KEYSTORE_PASSWORD` | contraseña del keystore |
| `KEY_ALIAS` | `ryx` |
| `KEY_PASSWORD` | contraseña de la clave |

**Crear la clave de firma** (una vez; guarda el `.jks` y las contraseñas en un lugar seguro):
```
keytool -genkeypair -v -keystore ryx-release.jks -alias ryx -keyalg RSA -keysize 2048 -validity 10000
```
Convertirla a texto en Windows (PowerShell):
```
[Convert]::ToBase64String([IO.File]::ReadAllBytes("ryx-release.jks")) | Set-Clipboard
```
Pega lo copiado en `KEYSTORE_BASE64`.

> Sin estos secrets el APK se compila igual (firmado con una clave de prueba y apuntando a una URL de ejemplo), pero **si luego cambias de clave, los usuarios tendrán que desinstalar y reinstalar**. Configúralos antes del primer APK que repartas.

## Compilar
- Cada **push a `main`** compila: ve a **Actions → Compilar APK → (última ejecución) → Artifacts → Ryx-History-APK**.
- Para publicar una versión descargable: crea una etiqueta `v1.0` (en GitHub Desktop: clic derecho sobre el commit → *Create Tag*; luego push). El APK queda en **Releases**.
- Cada compilación sube sola el `versionCode`, así que el APK nuevo se instala **encima** del anterior sin perder datos.

## Primer uso en el teléfono
1. Instala el APK (permite "instalar apps desconocidas" si Android lo pide).
2. Crea tu cuenta o entra con Discord.
3. Toca **Dar acceso a notificaciones** y activa Ryx History.
   En Android 13+ con APK instalado a mano: Ajustes → Apps → Ryx History → menú ⋮ → **Permitir ajustes restringidos**.
4. Quita la optimización de batería para la app (Ajustes → Batería) para que Android no la cierre en segundo plano; en Xiaomi, Oppo, Vivo y similares activa también el "inicio automático".

## Cómo funciona la sincronización
- Cada notificación se guarda primero en el teléfono (Room) con un ID único; si no hay internet, espera.
- Se envía en lotes ~20 s después de llegar, y hay un respaldo cada 15 min. Lo repetido se ignora, no se duplica.
- Solo se marca como enviado lo que el servidor confirmó.
