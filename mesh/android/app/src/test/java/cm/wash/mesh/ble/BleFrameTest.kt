package cm.wash.mesh.ble

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Miroir JVM de mesh/demo/test_ble_frames.py (même format 11 octets). */
class BleFrameTest {

    @Test
    fun roundtrip_single_frame() {
        val payload = "petit bundle".toByteArray(Charsets.UTF_8)
        val frames = BleFrame.encode(payload, "bundle-123")
        assertEquals(1, frames.size)
        val out = BleFrame.Reassembler().feed(frames[0])
        assertArrayEquals(payload, out)
    }

    @Test
    fun roundtrip_multi_frame_out_of_order_with_duplicate() {
        val payload = ByteArray(1200) { (it % 251).toByte() }
        val frames = BleFrame.encode(payload, "bundle-xyz", mtu = 128)
        assert(frames.size > 2)
        val re = BleFrame.Reassembler()
        var out: ByteArray? = null
        for (f in frames.reversed()) {
            out = re.feed(f) ?: out
        }
        re.feed(frames[0]) // doublon après complétion : nouveau partiel, sans effet
        assertArrayEquals(payload, out)
    }

    @Test
    fun header_layout_matches_spec() {
        val frames = BleFrame.encode(byteArrayOf(1, 2, 3), "b")
        val f = frames[0]
        assertEquals(BleFrame.HEADER_LEN, 11)
        assertEquals(0x57.toByte(), f[0])
        assertEquals(0x53.toByte(), f[1])
        assertEquals(1.toByte(), f[2])
        // tag = sha256("b")[:4]
        val tag = BleFrame.bundleTag("b")
        assertEquals(4, tag.size)
        assertArrayEquals(tag, f.copyOfRange(3, 7))
        // index=0, total=1 en big-endian.
        assertEquals(0, f[7].toInt() and 0xFF)
        assertEquals(0, f[8].toInt() and 0xFF)
        assertEquals(0, f[9].toInt() and 0xFF)
        assertEquals(1, f[10].toInt() and 0xFF)
    }

    @Test
    fun corrupt_frames_are_rejected() {
        // Première trame d'un bundle en 2 morceaux : toute altération d'en-tête
        // invalide la trame ou orphelinise le partiel — jamais de bundle complet.
        val good = BleFrame.encode(ByteArray(100) { 7.toByte() }, "b", mtu = 64)[0]
        for (i in 0 until BleFrame.HEADER_LEN) {
            val bad = good.copyOf()
            bad[i] = (bad[i] + 1).toByte()
            assertNull("octet $i", BleFrame.Reassembler().feed(bad))
        }
        assertNull(BleFrame.Reassembler().feed(byteArrayOf(0x57, 0x53))) // trop court
    }

    @Test
    fun bundle_tag_is_stable() {
        val h1 = BleFrame.bundleTag("node-A")
        assertEquals(4, h1.size)
        assertArrayEquals(h1, BleFrame.bundleTag("node-A"))
    }
}
