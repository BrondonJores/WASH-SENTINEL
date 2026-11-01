package cm.wash.mesh.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface MeshDao {
    @Query("SELECT * FROM bundles WHERE status = 'PENDING' ORDER BY updatedAt ASC")
    suspend fun pending(): List<BundleEntity>

    @Query("SELECT * FROM bundles WHERE status = 'PENDING' ORDER BY updatedAt ASC LIMIT :limit")
    suspend fun outbox(limit: Int = 50): List<BundleEntity>

    @Query("SELECT COUNT(*) FROM bundles WHERE status = 'PENDING'")
    suspend fun pendingCount(): Int

    @Query("SELECT COUNT(*) FROM bundles WHERE status = 'DONE'")
    suspend fun doneCount(): Int

    @Query("DELETE FROM bundles WHERE id = :id")
    suspend fun deleteById(id: String)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(e: BundleEntity): Long

    @Query("UPDATE bundles SET json = :json, updatedAt = :now WHERE id = :id")
    suspend fun updateJson(id: String, json: String, now: Long = System.currentTimeMillis())

    @Query("UPDATE bundles SET status = 'DONE' WHERE id IN (:ids)")
    suspend fun markDone(ids: List<String>)
}
