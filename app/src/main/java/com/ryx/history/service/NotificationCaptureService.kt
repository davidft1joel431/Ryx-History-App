package com.ryx.history.service

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.ryx.history.RyxApp
import com.ryx.history.data.NotificationEntity
import com.ryx.history.sync.SyncScheduler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.util.UUID

/** Captura cada notificación que llega al teléfono y la guarda en la base local. */
class NotificationCaptureService : NotificationListenerService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null || sbn.packageName == packageName) return
        val n = sbn.notification ?: return
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        val extras = n.extras
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.take(2000)
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.take(8000)
        val sub = extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString()?.take(2000)
        val big = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()?.take(20000)
        if (title.isNullOrBlank() && text.isNullOrBlank() && big.isNullOrBlank()) return

        val appName = try {
            val info = packageManager.getApplicationInfo(sbn.packageName, 0)
            packageManager.getApplicationLabel(info).toString()
        } catch (e: Exception) {
            sbn.packageName
        }

        // UUID determinista: la misma notificación nunca se guarda dos veces
        val id = UUID.nameUUIDFromBytes("${sbn.key}|${sbn.postTime}|$title|$text|$big".toByteArray()).toString()
        val entity = NotificationEntity(
            uuid = id,
            packageName = sbn.packageName.take(256),
            appName = appName.take(256),
            title = title, text = text, subText = sub, bigText = big,
            category = n.category?.take(64),
            channelId = n.channelId?.take(256),
            postedAt = sbn.postTime
        )
        val app = applicationContext as RyxApp
        scope.launch {
            if (app.db.dao().insert(entity) != -1L) SyncScheduler.soon(applicationContext)
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}
