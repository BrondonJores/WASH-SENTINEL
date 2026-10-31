package cm.wash.mesh.mesh

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TransportSelectorTest {

    @Test
    fun `nearby gagne quand disponible`() {
        val sel = TransportSelector.select(nearbyReady = true, bleReady = true, payloadBytes = 500)
        assertEquals(Transport.NEARBY, sel.primary)
        assertEquals(listOf(Transport.BLE, Transport.QR), sel.fallbacks)
    }

    @Test
    fun `ble est le secours quand nearby tombe`() {
        val sel = TransportSelector.select(nearbyReady = false, bleReady = true, payloadBytes = 500)
        assertEquals(Transport.BLE, sel.primary)
        assertEquals(listOf(Transport.QR), sel.fallbacks)
        assertTrue(sel.reason.contains("BLE"))
    }

    @Test
    fun `qr est le dernier recours sans radio`() {
        val sel = TransportSelector.select(nearbyReady = false, bleReady = false, payloadBytes = 500)
        assertEquals(Transport.QR, sel.primary)
        assertTrue(sel.fallbacks.isEmpty())
        assertTrue(sel.reason.contains("QR"))
    }

    @Test
    fun `qr volumineux prévient dans le motif`() {
        val sel = TransportSelector.select(
            nearbyReady = false,
            bleReady = false,
            payloadBytes = TransportSelector.QR_MAX_BYTES + 1,
        )
        assertEquals(Transport.QR, sel.primary)
        assertTrue(sel.reason.contains("volumineux"))
    }

    @Test
    fun `qr petit ne prévient pas`() {
        val sel = TransportSelector.select(
            nearbyReady = false,
            bleReady = false,
            payloadBytes = TransportSelector.QR_MAX_BYTES,
        )
        assertTrue(!sel.reason.contains("volumineux"))
    }
}
