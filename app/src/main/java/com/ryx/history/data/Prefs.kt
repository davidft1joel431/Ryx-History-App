package com.ryx.history.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.UUID

/** Guarda sesión y datos pequeños cifrados con el Keystore de Android. */
class Prefs(context: Context) {
    private val appContext = context.applicationContext
    private val sp: SharedPreferences = securePreferences() ?: plainPreferences()

    private val _loggedIn = MutableStateFlow(!sp.getString(K_REFRESH, null).isNullOrBlank())
    val loggedIn: StateFlow<Boolean> = _loggedIn

    val accessToken: String? get() = sp.getString(K_ACCESS, null)
    val refreshToken: String? get() = sp.getString(K_REFRESH, null)
    /** Dirección del servidor que fijó el usuario en Ajustes; null = la de fábrica. */
    var serverUrl: String?
        get() = sp.getString(K_SERVER, null)
        set(value) {
            val editor = sp.edit()
            if (value.isNullOrBlank()) editor.remove(K_SERVER) else editor.putString(K_SERVER, value.trim())
            editor.apply()
        }

    val userName: String get() = sp.getString(K_NAME, null) ?: ""
    val userEmail: String get() = sp.getString(K_EMAIL, null) ?: ""

    /**
     * Estado anti-CSRF del inicio de sesión con Discord.
     * Se escribe con commit(): el proceso suele morir mientras el navegador está abierto.
     */
    var pendingState: String?
        get() = sp.getString(K_STATE, null)
        set(value) {
            val editor = sp.edit()
            if (value.isNullOrBlank()) editor.remove(K_STATE).remove(K_STATE_AT)
            else editor.putString(K_STATE, value).putLong(K_STATE_AT, System.currentTimeMillis())
            editor.commit()
        }

    /** Hay un inicio de sesión con Discord en curso y todavía no caducó. */
    fun pendingDiscordLogin(): Boolean {
        val state = sp.getString(K_STATE, null)
        if (state.isNullOrBlank()) return false
        val issuedAt = sp.getLong(K_STATE_AT, 0L)
        val age = System.currentTimeMillis() - issuedAt
        return age in 0..DISCORD_WINDOW_MS
    }

    val deviceId: String
        get() = sp.getString(K_DEVICE, null) ?: UUID.randomUUID().toString().also {
            sp.edit().putString(K_DEVICE, it).apply()
        }

    fun saveSession(access: String, refresh: String, name: String, email: String) {
        sp.edit().putString(K_ACCESS, access).putString(K_REFRESH, refresh)
            .putString(K_NAME, name).putString(K_EMAIL, email).apply()
        _loggedIn.value = true
    }

    fun clearSession() {
        sp.edit().remove(K_ACCESS).remove(K_REFRESH).remove(K_NAME).remove(K_EMAIL)
            .remove(K_STATE).remove(K_STATE_AT).apply()
        _loggedIn.value = false
    }

    /**
     * Si el Keystore quedó inservible (restauración de copia, "ajustes restringidos",
     * cambio de clave de firma) EncryptedSharedPreferences lanza una excepción y la app
     * moriría al arrancar. Se descarta el archivo y se crea de nuevo.
     */
    private fun securePreferences(): SharedPreferences? {
        return try {
            createSecure()
        } catch (e: Exception) {
            runCatching { appContext.deleteSharedPreferences(FILE_SECURE) }
            runCatching { createSecure() }.getOrNull()
        }
    }

    private fun createSecure(): SharedPreferences = EncryptedSharedPreferences.create(
        appContext,
        FILE_SECURE,
        MasterKey.Builder(appContext).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )

    private fun plainPreferences(): SharedPreferences =
        appContext.getSharedPreferences(FILE_PLAIN, Context.MODE_PRIVATE)

    private companion object {
        const val FILE_SECURE = "ryx_secure"
        const val FILE_PLAIN = "ryx_fallback"
        const val DISCORD_WINDOW_MS = 15 * 60 * 1000L
        const val K_ACCESS = "access"
        const val K_REFRESH = "refresh"
        const val K_NAME = "name"
        const val K_EMAIL = "email"
        const val K_STATE = "pending_state"
        const val K_STATE_AT = "pending_state_at"
        const val K_DEVICE = "device_id"
        const val K_SERVER = "server_url"
    }
}
