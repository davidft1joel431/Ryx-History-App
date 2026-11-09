package com.ryx.history.net

import android.os.Build
import com.ryx.history.BuildConfig
import com.ryx.history.data.NotificationEntity
import com.ryx.history.data.Prefs
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Cliente HTTP del servidor. Todas las funciones son bloqueantes: llamarlas desde Dispatchers.IO. */
class Api(private val prefs: Prefs) {

    class ApiException(val code: Int, message: String) : Exception(message)

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()
    private val base = BuildConfig.SERVER_URL.trimEnd('/')
    private val jsonType = "application/json; charset=utf-8".toMediaType()

    private fun call(method: String, path: String, body: JSONObject?, token: String?): JSONObject {
        val builder = Request.Builder().url(base + path)
        if (token != null) builder.header("Authorization", "Bearer $token")
        val payload = if (method == "GET") null else (body ?: JSONObject()).toString().toRequestBody(jsonType)
        builder.method(method, payload)
        client.newCall(builder.build()).execute().use { r ->
            val text = r.body?.string().orEmpty()
            val json = try { JSONObject(text) } catch (e: Exception) { JSONObject() }
            if (!r.isSuccessful) throw ApiException(r.code, json.optString("error", "Error ${r.code}"))
            return json
        }
    }

    private fun authed(method: String, path: String, body: JSONObject? = null): JSONObject {
        return try {
            call(method, path, body, prefs.accessToken)
        } catch (e: ApiException) {
            if (e.code == 401 && refresh()) call(method, path, body, prefs.accessToken) else throw e
        }
    }

    @Synchronized
    private fun refresh(): Boolean {
        val rt = prefs.refreshToken ?: return false
        return try {
            saveSession(call("POST", "/api/auth/refresh", JSONObject().put("refreshToken", rt), null))
            true
        } catch (e: ApiException) {
            if (e.code == 401 || e.code == 403) prefs.clearSession()   // sesión vencida: volver al login
            false
        } catch (e: IOException) {
            false
        }
    }

    private fun saveSession(j: JSONObject) {
        val u = j.getJSONObject("user")
        prefs.saveSession(
            j.getString("accessToken"), j.getString("refreshToken"),
            u.optString("name"), u.optString("email")
        )
    }

    fun login(email: String, password: String) =
        saveSession(call("POST", "/api/auth/login", JSONObject().put("email", email).put("password", password), null))

    fun register(email: String, password: String, name: String) =
        saveSession(
            call("POST", "/api/auth/register",
                JSONObject().put("email", email).put("password", password).put("name", name), null)
        )

    fun discordExchange(code: String) =
        saveSession(call("POST", "/api/auth/discord/exchange", JSONObject().put("code", code), null))

    fun discordStartUrl(state: String) = "$base/auth/discord/start?app_state=$state"

    fun logout() {
        try {
            call("POST", "/api/auth/logout", JSONObject().put("refreshToken", prefs.refreshToken ?: ""), null)
        } catch (_: Exception) { /* sin conexión: igual se cierra la sesión local */ }
    }

    fun deleteCloudHistory(): Int = authed("DELETE", "/api/me/history").optInt("deleted")

    /** Envía un lote y devuelve los uuid que el servidor confirmó. */
    fun sync(batch: List<NotificationEntity>): List<String> {
        val arr = JSONArray()
        for (n in batch) {
            arr.put(
                JSONObject()
                    .put("uuid", n.uuid).put("packageName", n.packageName).put("appName", n.appName)
                    .putOpt("title", n.title).putOpt("text", n.text).putOpt("subText", n.subText)
                    .putOpt("bigText", n.bigText).putOpt("category", n.category).putOpt("channelId", n.channelId)
                    .put("postedAt", n.postedAt)
            )
        }
        val device = JSONObject()
            .put("id", prefs.deviceId).put("model", Build.MODEL ?: "").put("android", Build.VERSION.RELEASE ?: "")
        val res = authed("POST", "/api/sync", JSONObject().put("device", device).put("notifications", arr))
        val accepted = res.optJSONArray("accepted") ?: JSONArray()
        return List(accepted.length()) { accepted.getString(it) }
    }
}
