package com.ryx.history.sync

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.ryx.history.RyxApp
import com.ryx.history.net.Api
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.IOException
import java.util.concurrent.TimeUnit

class SyncWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val app = applicationContext as RyxApp
        if (app.prefs.refreshToken == null) return@withContext Result.success()
        try {
            while (true) {
                val batch = app.db.dao().unsynced(100)
                if (batch.isEmpty()) break
                val confirmed = app.api.sync(batch)
                app.db.dao().markSynced(confirmed)
                // Si el servidor no confirmó todo, se reintenta luego (el servidor ignora repetidos)
                if (confirmed.size < batch.size) return@withContext Result.retry()
            }
            Result.success()
        } catch (e: Api.ApiException) {
            if (e.code == 401 || e.code == 403 || e.code == 400 || e.code == 413) Result.failure() else Result.retry()
        } catch (e: IOException) {
            Result.retry()
        }
    }
}

object SyncScheduler {
    private val needsNetwork = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    /** Respaldo cada 15 minutos (el mínimo de Android). */
    fun schedulePeriodic(ctx: Context) {
        val req = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES).setConstraints(needsNetwork).build()
        WorkManager.getInstance(ctx).enqueueUniquePeriodicWork("ryx-periodic", ExistingPeriodicWorkPolicy.KEEP, req)
    }

    /** Tras capturar una notificación: envía en ~20 s (agrupa varias en un solo envío). */
    fun soon(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(needsNetwork).setInitialDelay(20, TimeUnit.SECONDS).build()
        WorkManager.getInstance(ctx).enqueueUniqueWork("ryx-soon", ExistingWorkPolicy.KEEP, req)
    }

    /** Botón "Sincronizar ahora". */
    fun now(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<SyncWorker>().setConstraints(needsNetwork).build()
        WorkManager.getInstance(ctx).enqueueUniqueWork("ryx-now", ExistingWorkPolicy.REPLACE, req)
    }
}
