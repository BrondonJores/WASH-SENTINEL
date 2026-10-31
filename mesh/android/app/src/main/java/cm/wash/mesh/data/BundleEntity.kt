package cm.wash.mesh.data

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "bundles")
data class BundleEntity(
    @PrimaryKey val id: String,
    val originNode: String,
    val schoolId: Int,
    val json: String,
    val status: String = "PENDING",
    val updatedAt: Long = System.currentTimeMillis(),
)
