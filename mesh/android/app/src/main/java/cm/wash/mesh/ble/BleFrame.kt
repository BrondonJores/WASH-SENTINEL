package cm.wash.mesh.ble

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest

/**
 * Trames BLE — miroir exact de mesh/demo/ble_frames.py (testé en Python,
 * faute de SDK Android ici). Aucune import Android : logique pure.
 *
 * Trame : magic(2)=WS | ver(1)=1 | tag(4)=sha256(bundle_id)[:4] |
 *         index(2 BE) | total(2 BE) | payload (mtu-3-11 max).
 */
object BleFrame {
    const val SERVICE_UUID = "a1b2c3d4-e5f6-4a7b-8c9d-e0f1a2b3c4d5"
    const val TX_CHAR_UUID = "a1b2c3d4-e5f6-4a7b-8c9d-e0f1a2b3c4d6"
    const val RX_CHAR_UUID = "a1b2c3d4-e5f6-4a7b-8c9d-e0f1a2b3c4d7"
    const val CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"

    private val MAGIC_0: Byte = 0x57
    private val MAGIC_1: Byte = 0x53
    private const val VERSION: Byte = 1
    const val HEADER_LEN = 11
    const val PARTIAL_TTL_MS = 60_000L
    const val MAX_CHUNK = 200

    fun bundleTag(bundleId: String): ByteArray =
        MessageDigest.getInstance("SHA-256").digest(bundleId.toByteArray(Charsets.UTF_8)).copyOf(4)

    /** Découpe un bundle en trames pour le MTU négocié (défaut 512, min 23). */
    fun encode(bundle: ByteArray, bundleId: String, mtu: Int = 512): List<ByteArray> {
        require(mtu >= 16) { "MTU trop petit pour l'en-tête BLE" }
        val payloadSize = mtu - 3 - HEADER_LEN
        val tag = bundleTag(bundleId)
        val total = maxOf(1, (bundle.size + payloadSize - 1) / payloadSize)
        require(total <= 0xFFFF) { "Bundle trop gros pour le transport BLE" }
        return (0 until total).map { index ->
            val start = index * payloadSize
            val end = minOf(start + payloadSize, bundle.size)
            val frame = ByteBuffer.allocate(HEADER_LEN + (end - start)).order(ByteOrder.BIG_ENDIAN)
            frame.put(MAGIC_0).put(MAGIC_1).put(VERSION).put(tag)
            frame.putShort(index.toShort()).putShort(total.toShort())
            frame.put(bundle, start, end - start)
            frame.array()
        }
    }

    /** Assemble les trames par tag. Retourne le bundle complet ou null. */
    class Reassembler {
        private data class Partial(val chunks: MutableMap<Int, ByteArray>, val total: Int, var seen: Long)

        private val partials = mutableMapOf<String, Partial>()

        @Synchronized
        fun feed(frame: ByteArray, nowMs: Long = System.currentTimeMillis()): ByteArray? {
            partials.entries.removeIf { nowMs - it.value.seen > PARTIAL_TTL_MS }
            if (frame.size < HEADER_LEN || frame[0] != MAGIC_0 || frame[1] != MAGIC_1 || frame[2] != VERSION) {
                return null
            }
            val tag = frame.copyOfRange(3, 7).joinToString("") { "%02x".format(it) }
            val buf = ByteBuffer.wrap(frame, 7, 4).order(ByteOrder.BIG_ENDIAN)
            val index = buf.short.toInt() and 0xFFFF
            val total = buf.short.toInt() and 0xFFFF
            if (total == 0 || total > 0xFFFF || index >= total) return null
            val part = partials.getOrPut(tag) { Partial(mutableMapOf(), total, nowMs) }
            if (part.total != total) return null
            part.chunks[index] = frame.copyOfRange(HEADER_LEN, frame.size)
            part.seen = nowMs
            if (part.chunks.size != total) return null
            partials.remove(tag)
            return (0 until total).fold(ByteArray(0)) { acc, i -> acc + part.chunks.getValue(i) }
        }
    }
}
