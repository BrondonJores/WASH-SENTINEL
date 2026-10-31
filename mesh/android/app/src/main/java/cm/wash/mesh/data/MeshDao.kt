package cm.wash.mesh.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface MeshDao {
    @Query("SELECT * FROM bundles WHERE status = 'PENDING' ORDER BY updatedAt ASC")
    suspend fun pending(): List<BundleEntity>

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(e: BundleEntity): Long

    @Query("UPDATE bundles SET json = :json, updatedAt = :now WHERE id = :id")
    suspend fun updateJson(id: String, json: String, now: Long = System.currentTimeMillis())

    @Query("UPDATE bundles SET status = 'DONE' WHERE id IN (:ids)")
    suspend fun markDone(ids: List<String>)
}
