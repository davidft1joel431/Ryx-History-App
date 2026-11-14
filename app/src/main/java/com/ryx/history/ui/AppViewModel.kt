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

private const val PAGE = 200

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

    /** Dirección efectiva del servidor; cambia al editarla en Ajustes. */
    val serverBase = MutableStateFlow(ryx.api.base)

    val list: StateFlow<List<NotificationEntity>> =
        combine(query, limit) { q, l -> q.trim() to l }
            .flatMapLatest { (q, l) -> dao.observe(q, l) }
            .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())
    val total: StateFlow<Int> = dao.count().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)
    val pending: StateFlow<Int> = dao.pendingCount().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)

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

    fun handleDeepLink(uri: Uri) {
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

    fun setServer(raw: String) {
        val url = normalizeServerUrl(raw)
        if (url == null) {
            message.value = "Dirección no válida. Ejemplo: https://192.168.1.10:3000"
            return
        }
        ryx.prefs.serverUrl = url
        serverBase.value = ryx.api.base
        message.value = "Servidor guardado: $url"
    }

    fun resetServer() {
        ryx.prefs.serverUrl = null
        serverBase.value = ryx.api.base
        message.value = "Servidor de fábrica: ${ryx.api.base}"
    }

    private fun normalizeServerUrl(raw: String): String? {
        var text = raw.trim()
        if (text.isEmpty()) return null
        if (!text.startsWith("http://", true) && !text.startsWith("https://", true)) text = "https://$text"
        return try {
            val uri = java.net.URI(text)
            if (uri.host.isNullOrBlank()) null else text.trimEnd('/')
        } catch (e: Exception) {
            null
        }
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
