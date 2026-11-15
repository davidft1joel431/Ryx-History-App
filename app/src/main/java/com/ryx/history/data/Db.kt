package com.ryx.history.data

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.flow.Flow

@Entity(
    tableName = "notifications",
    indices = [Index("postedAt"), Index("synced"), Index("packageName")]
)
data class NotificationEntity(
    @PrimaryKey val uuid: String,
    val packageName: String,
    val appName: String,
    val title: String?,
    val text: String?,
    val subText: String?,
    val bigText: String?,
    val category: String?,
    val channelId: String?,
    val postedAt: Long,
    val synced: Boolean = false,
    /** Icono o foto de la notificación (PNG en base64) para verla en el perfil. */
    val image: String? = null
)

/** Resumen por aplicación para la sección «Por app» del perfil. */
data class AppCount(
    val packageName: String,
    val appName: String,
    val total: Int
)

@Dao
interface NotificationDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(n: NotificationEntity): Long

    @Query(
        """SELECT * FROM notifications
           WHERE (:q = '' OR title LIKE '%' || :q || '%' OR text LIKE '%' || :q || '%'
                  OR bigText LIKE '%' || :q || '%' OR appName LIKE '%' || :q || '%')
           ORDER BY postedAt DESC LIMIT :limit"""
    )
    fun observe(q: String, limit: Int): Flow<List<NotificationEntity>>

    @Query("SELECT * FROM notifications WHERE synced = 0 ORDER BY postedAt ASC LIMIT :limit")
    suspend fun unsynced(limit: Int): List<NotificationEntity>

    @Query("UPDATE notifications SET synced = 1 WHERE uuid IN (:uuids)")
    suspend fun markSynced(uuids: List<String>)

    @Query("SELECT COUNT(*) FROM notifications")
    fun count(): Flow<Int>

    @Query("SELECT COUNT(*) FROM notifications WHERE synced = 0")
    fun pendingCount(): Flow<Int>

    @Query("DELETE FROM notifications")
    suspend fun clear()

    @Query("SELECT * FROM notifications WHERE packageName = :pkg ORDER BY postedAt DESC LIMIT :limit")
    fun byApp(pkg: String, limit: Int): Flow<List<NotificationEntity>>

    @Query("SELECT * FROM notifications WHERE postedAt >= :from ORDER BY postedAt DESC LIMIT :limit")
    fun since(from: Long, limit: Int): Flow<List<NotificationEntity>>

    @Query(
        """SELECT * FROM notifications WHERE packageName = :pkg AND postedAt >= :from
           ORDER BY postedAt DESC LIMIT :limit"""
    )
    fun byAppSince(pkg: String, from: Long, limit: Int): Flow<List<NotificationEntity>>

    @Query(
        """SELECT packageName, appName, COUNT(*) AS total FROM notifications
           GROUP BY packageName, appName ORDER BY total DESC"""
    )
    fun apps(): Flow<List<AppCount>>

    @Query("SELECT COUNT(*) FROM notifications WHERE synced = 1")
    fun sentCount(): Flow<Int>
}

val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE notifications ADD COLUMN image TEXT")
    }
}

@Database(entities = [NotificationEntity::class], version = 2, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun dao(): NotificationDao
}
