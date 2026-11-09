package com.ryx.history.ui

import android.app.Application
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
            } catch (e: Api.ApiException) {
                message.value = e.message
            } catch (e: IOException) {
                message.value = "No hay conexión con el servidor"
            } finally {
                busy.value = false
            }
        }
    }

    fun login(email: String, password: String) =
        runNetwork({ SyncScheduler.now(ryx) }) { ryx.api.login(email.trim(), password) }

    fun register(email: String, password: String, name: String) =
        runNetwork({ SyncScheduler.now(ryx) }) { ryx.api.register(email.trim(), password, name.trim()) }

    fun startDiscord(context: Context) {
        val bytes = ByteArray(24).also { SecureRandom().nextBytes(it) }
        val state = Base64.encodeToString(bytes, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
        ryx.prefs.pendingState = state
        context.startActivity(
            Intent(Intent.ACTION_VIEW, Uri.parse(ryx.api.discordStartUrl(state))).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
    }

    fun handleDeepLink(uri: Uri) {
        val code = uri.getQueryParameter("code")
        val state = uri.getQueryParameter("state")
        val expected = ryx.prefs.pendingState
        if (code.isNullOrBlank() || state.isNullOrBlank() || state != expected) {
            message.value = "No se pudo completar el inicio de sesión con Discord. Inténtalo de nuevo."
            return
        }
        ryx.prefs.pendingState = null
        runNetwork({ SyncScheduler.now(ryx) }) { ryx.api.discordExchange(code) }
    }

    fun syncNow() {
        SyncScheduler.now(ryx)
        message.value = "Sincronizando…"
    }

    fun loadMore() { limit.value = limit.value + PAGE }

    fun logout() {
        viewModelScope.launch(Dispatchers.IO) {
            ryx.api.logout()
            ryx.prefs.clearSession()
            dao.clear()           // el historial local pertenece a esta cuenta
        }
    }

    fun wipeEverything() {
        runNetwork({ message.value = "Historial borrado del servidor y del teléfono" }) {
            ryx.api.deleteCloudHistory()
            dao.clear()
        }
    }
}
