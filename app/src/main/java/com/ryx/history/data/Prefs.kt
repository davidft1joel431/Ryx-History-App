package com.ryx.history.data

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.UUID

/** Guarda sesión y datos pequeños cifrados con el Keystore de Android. */
class Prefs(context: Context) {
    private val sp = EncryptedSharedPreferences.create(
        context,
        "ryx_secure",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )

    private val _loggedIn = MutableStateFlow(sp.getString(K_REFRESH, null) != null)
    val loggedIn: StateFlow<Boolean> = _loggedIn

    val accessToken: String? get() = sp.getString(K_ACCESS, null)
    val refreshToken: String? get() = sp.getString(K_REFRESH, null)
    val userName: String get() = sp.getString(K_NAME, null) ?: ""
    val userEmail: String get() = sp.getString(K_EMAIL, null) ?: ""

    var pendingState: String?
        get() = sp.getString(K_STATE, null)
        set(value) { sp.edit().putString(K_STATE, value).apply() }

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
        sp.edit().remove(K_ACCESS).remove(K_REFRESH).remove(K_NAME).remove(K_EMAIL).remove(K_STATE).apply()
        _loggedIn.value = false
    }

    private companion object {
        const val K_ACCESS = "access"
        const val K_REFRESH = "refresh"
        const val K_NAME = "name"
        const val K_EMAIL = "email"
        const val K_STATE = "pending_state"
        const val K_DEVICE = "device_id"
    }
}
