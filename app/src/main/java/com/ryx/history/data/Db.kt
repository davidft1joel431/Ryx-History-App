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
    val synced: Boolean = false
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
}

@Database(entities = [NotificationEntity::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun dao(): NotificationDao
}
