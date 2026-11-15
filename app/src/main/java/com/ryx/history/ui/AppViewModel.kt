package com.ryx.history.ui

import android.app.Activity
import android.app.Application
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Base64
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.ryx.history.RyxApp
import com.ryx.history.data.AppCount
import com.ryx.history.data.NotificationEntity
import com.ryx.history.net.Api
import com.ryx.history.sync.SyncScheduler
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.IOException
import java.security.SecureRandom
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private const val PAGE = 200
private const val EXPORT_LIMIT = 5000

@OptIn(ExperimentalCoroutinesApi::class)
class AppViewModel(application: Application) : AndroidViewModel(application) {
    private val ryx = application as RyxApp
    private val dao = ryx.db.dao()

    val loggedIn: StateFlow<Boolean> = ryx.prefs.loggedIn
    val userName: String get() = ryx.prefs.userName

    val query = MutableStateFlow("")
    val limit = MutableStateFlow(PAGE)
    val busy = MutableStateFlow(false)
    val message = MutableStateFlow<String?>(null)

    val list: StateFlow<List<NotificationEntity>> =
        combine(query, limit) { q, l -> q.trim() to l }
            .flatMapLatest { (q, l) -> dao.observe(q, l) }
            .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())
    val total: StateFlow<Int> = dao.count().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)
    val pending: StateFlow<Int> = dao.pendingCount().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)
    val sent: StateFlow<Int> = dao.sentCount().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)
    val apps: StateFlow<List<AppCount>> =
        dao.apps().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    /** Datos de la cuenta tal como los ve el servidor. */
    data class AccountProfile(
        val name: String = "",
        val email: String = "",
        val discord: Boolean = false,
        val notifications: Int = 0
    )

    val profile = MutableStateFlow<AccountProfile?>(null)

    fun byApp(pkg: String, from: Long = 0L): StateFlow<List<NotificationEntity>> =
        (if (from <= 0L) dao.byApp(pkg, PAGE) else dao.byAppSince(pkg, from, PAGE))
            .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    /** Mensajes desde una fecha (para el filtro por rango del perfil). */
    fun since(from: Long): StateFlow<List<NotificationEntity>> =
        dao.since(from, PAGE).stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    /**
     * Guarda en el archivo elegido (texto o CSV) los mensajes del rango y la app
     * seleccionados en el perfil. No usa `busy` de la red para no bloquear el sync.
     */
    fun export(from: Long, pkg: String?, csv: Boolean, uri: Uri) {
        viewModelScope.launch {
            busy.value = true
            try {
                val rows = withContext(Dispatchers.IO) { dao.export(from, pkg ?: "", EXPORT_LIMIT) }
                if (rows.isEmpty()) {
                    message.value = "No hay mensajes que exportar en ese rango"
                    return@launch
                }
                val texto = withContext(Dispatchers.Default) {
                    if (csv) exportCsv(rows) else exportText(rows)
                }
                withContext(Dispatchers.IO) {
                    val salida = getApplication<Application>().contentResolver.openOutputStream(uri)
                        ?: throw IOException("el archivo no se pudo abrir")
                    salida.use { it.write(texto.toByteArray(Charsets.UTF_8)) }
                }
                message.value = "Exportados ${rows.size} mensaje(s)"
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                message.value = "No se pudo escribir el archivo"
            } finally {
                busy.value = false
            }
        }
    }

    private fun runNetwork(after: (() -> Unit)? = null, block: suspend () -> Unit) {
        viewModelScope.launch {
            busy.value = true
            try {
                withContext(Dispatchers.IO) { block() }
                after?.invoke()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Api.ApiException) {
                message.value = e.message ?: "El servidor devolvió un error"
            } catch (e: IOException) {
                message.value = "No hay conexión con el servidor"
            } catch (e: Exception) {
                // Respuesta inesperada del servidor: se avisa, nunca se cierra la app.
                message.value = "El servidor devolvió una respuesta inesperada. Inténtalo de nuevo."
            } finally {
                busy.value = false
            }
        }
    }

    /** Evita mandar al usuario a un servidor que no existe (APK compilado sin SERVER_URL). */
    private fun ensureConfigured(): Boolean {
        if (ryx.api.isConfigured) return true
        message.value = "Esta versión no tiene configurada la URL del servidor (SERVER_URL). Avisa a quien la compiló."
        return false
    }

    fun login(email: String, password: String) {
        if (!ensureConfigured()) return
        runNetwork({ SyncScheduler.now(ryx) }) { ryx.api.login(email.trim(), password) }
    }

    fun register(email: String, password: String, name: String) {
        if (!ensureConfigured()) return
        runNetwork({ SyncScheduler.now(ryx) }) { ryx.api.register(email.trim(), password, name.trim()) }
    }

    fun startDiscord(context: Context) {
        if (!ensureConfigured()) return
        val bytes = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val state = Base64.encodeToString(bytes, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
        ryx.prefs.pendingState = state
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(ryx.api.discordStartUrl(state)))
        if (context !is Activity) intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            context.startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            ryx.prefs.pendingState = null
            message.value = "No hay un navegador instalado para abrir Discord."
            return
        }
        message.value = "Termina el inicio de sesión en el navegador y vuelve a Ryx History."
    }

    /** Pide al servidor los datos de la cuenta (nombre, correo y si tiene Discord). */
    fun loadProfile() {
        if (ryx.prefs.accessToken == null) return
        runNetwork {
            val user = ryx.api.me()
            profile.value = AccountProfile(
                name = user.optString("name"),
                email = user.optString("email"),
                discord = user.optBoolean("discord"),
                notifications = user.optInt("notifications")
            )
        }
    }

    /** Abre Discord para vincular la cuenta que entró con correo y contraseña. */
    fun linkDiscord(context: Context) {
        if (!ensureConfigured()) return
        viewModelScope.launch {
            busy.value = true
            try {
                val url = withContext(Dispatchers.IO) { ryx.api.discordLinkUrl() }
                if (url.isBlank()) {
                    message.value = "El servidor no tiene Discord configurado."
                    return@launch
                }
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                if (context !is Activity) intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(intent)
                message.value = "Termina de vincular en el navegador y vuelve a Ryx History."
            } catch (e: Api.ApiException) {
                message.value = e.message ?: "El servidor devolvió un error"
            } catch (e: IOException) {
                message.value = "No hay conexión con el servidor"
            } catch (e: ActivityNotFoundException) {
                message.value = "No hay un navegador instalado para abrir Discord."
            } catch (e: Exception) {
                message.value = "No se pudo abrir Discord. Inténtalo de nuevo."
            } finally {
                busy.value = false
            }
        }
    }

    fun handleDeepLink(uri: Uri) {        // Vuelta del navegador tras vincular Discord a una cuenta con correo.
        if (uri.getQueryParameter("linked") == "1") {
            message.value = "Cuenta de Discord vinculada"
            loadProfile()
            return
        }
        val error = firstParam(uri, "error")
        val code = firstParam(uri, "code", "auth_code", "authorization_code")
        val access = firstParam(uri, "accessToken", "access_token", "token")
        val refresh = firstParam(uri, "refreshToken", "refresh_token")
        if (error == null && code == null && access == null) return   // enlace ajeno al inicio de sesión

        if (!error.isNullOrBlank()) {
            ryx.prefs.pendingState = null
            message.value = if (error == "access_denied") "Cancelaste el inicio de sesión con Discord."
            else "Discord devolvió un error ($error). Inténtalo de nuevo."
            return
        }

        // Protección anti-CSRF: si el servidor devuelve el estado, debe ser el que generamos.
        val state = firstParam(uri, "state", "app_state")
        if (!state.isNullOrBlank()) {
            if (state != ryx.prefs.pendingState) {
                message.value = "El enlace de Discord no es válido o ya se usó. Inténtalo de nuevo."
                return
            }
        } else if (!ryx.prefs.pendingDiscordLogin()) {
            message.value = "El enlace de Discord caducó. Vuelve a tocar “Continuar con Discord”."
            return
        }

        ryx.prefs.pendingState = null

        // Algunos servidores devuelven la sesión ya creada en lugar de un código.
        if (access != null && refresh != null) {
            ryx.prefs.saveSession(
                access, refresh,
                firstParam(uri, "name").orEmpty(),
                firstParam(uri, "email").orEmpty()
            )
            SyncScheduler.now(ryx)
            message.value = "Sesión iniciada con Discord"
            return
        }

        if (code == null) {
            message.value = "No se pudo completar el inicio de sesión con Discord. Inténtalo de nuevo."
            return
        }
        runNetwork({
            SyncScheduler.now(ryx)
            message.value = "Sesión iniciada con Discord"
        }) { ryx.api.discordExchange(code) }
    }

    private fun firstParam(uri: Uri, vararg names: String): String? =
        names.firstNotNullOfOrNull { name ->
            uri.getQueryParameter(name)?.takeIf { it.isNotBlank() }
        }

    fun syncNow() {
        SyncScheduler.now(ryx)
        message.value = "Sincronizando…"
    }

    fun loadMore() { limit.value = limit.value + PAGE }

    fun logout() {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                ryx.api.logout()
                dao.clear()       // el historial local pertenece a esta cuenta
            }
            ryx.prefs.clearSession()
        }
    }

    fun wipeEverything() {
        runNetwork({ message.value = "Historial borrado del servidor y del teléfono" }) {
            ryx.api.deleteCloudHistory()
            dao.clear()
        }
    }
}

private fun fecha(patron: String) = SimpleDateFormat(patron, Locale("es", "PE"))

private fun cuerpoDe(n: NotificationEntity): String =
    n.bigText?.takeIf { it.isNotBlank() } ?: n.text ?: ""

/** Archivo de texto legible con el texto completo de cada mensaje. */
private fun exportText(rows: List<NotificationEntity>): String {
    val salida = StringBuilder()
    salida.append("RyxHistory · mensajes exportados\r\n")
    salida.append("Generado: ").append(fecha("dd/MM/yyyy HH:mm").format(Date())).append("\r\n")
    salida.append("Mensajes: ").append(rows.size).append("\r\n\r\n")
    rows.forEach { n ->
        salida.append('[').append(fecha("dd/MM/yyyy HH:mm").format(Date(n.postedAt))).append("] ")
            .append(n.appName).append(" (").append(n.packageName).append(")\r\n")
        if (!n.title.isNullOrBlank()) salida.append("Título: ").append(n.title).append("\r\n")
        salida.append(cuerpoDe(n)).append("\r\n")
        if (!n.category.isNullOrBlank()) salida.append("Categoría: ").append(n.category).append("\r\n")
        if (!n.image.isNullOrBlank()) salida.append("[imagen adjunta]\r\n")
        salida.append("---\r\n")
    }
    return salida.toString()
}

private fun csvCampo(valor: String?): String = "\"" + (valor ?: "").replace("\"", "\"\"") + "\""

/** Hoja de cálculo: una fila por mensaje, con BOM para que Excel lea los acentos. */
private fun exportCsv(rows: List<NotificationEntity>): String {
    val salida = StringBuilder("\uFEFF")
    salida.append("fecha,hora,app,paquete,titulo,texto,texto_completo,categoria,imagen\r\n")
    rows.forEach { n ->
        val campos = listOf(
            fecha("yyyy-MM-dd").format(Date(n.postedAt)),
            fecha("HH:mm").format(Date(n.postedAt)),
            n.appName,
            n.packageName,
            n.title,
            n.text,
            n.bigText,
            n.category,
            if (n.image.isNullOrBlank()) "no" else "si"
        )
        salida.append(campos.joinToString(",") { csvCampo(it) }).append("\r\n")
    }
    return salida.toString()
}
