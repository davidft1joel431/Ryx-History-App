package com.ryx.history

import android.app.Application
import androidx.room.Room
import com.ryx.history.data.AppDatabase
import com.ryx.history.data.Prefs
import com.ryx.history.net.Api
import com.ryx.history.sync.SyncScheduler

class RyxApp : Application() {
    lateinit var db: AppDatabase
        private set
    lateinit var prefs: Prefs
        private set
    lateinit var api: Api
        private set

    override fun onCreate() {
        super.onCreate()
        db = Room.databaseBuilder(this, AppDatabase::class.java, "ryx_history.db").build()
        prefs = Prefs(this)
        api = Api(prefs)
        SyncScheduler.schedulePeriodic(this)
    }
}
