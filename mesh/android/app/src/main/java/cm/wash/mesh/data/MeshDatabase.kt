package cm.wash.mesh.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(entities = [BundleEntity::class], version = 1, exportSchema = false)
abstract class MeshDatabase : RoomDatabase() {
    abstract fun dao(): MeshDao

    companion object {
        @Volatile private var instance: MeshDatabase? = null

        fun get(context: Context): MeshDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    MeshDatabase::class.java,
                    "wash-mesh.db",
                ).build().also { instance = it }
            }
    }
}
