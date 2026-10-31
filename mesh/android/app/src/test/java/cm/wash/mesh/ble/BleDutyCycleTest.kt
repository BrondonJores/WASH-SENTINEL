package cm.wash.mesh.ble

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BleDutyCycleTest {

    @Test
    fun `cycle attendu 8 s actif puis 22 s repos`() {
        assertEquals(8_000L, BleDutyCycle.ACTIVE_MS)
        assertEquals(22_000L, BleDutyCycle.IDLE_MS)
        assertEquals(30_000L, BleDutyCycle.CYCLE_MS)
    }

    @Test
    fun `fenêtre active en début de cycle`() {
        assertTrue(BleDutyCycle.isActiveWindow(0))
        assertTrue(BleDutyCycle.isActiveWindow(7_999))
        assertFalse(BleDutyCycle.isActiveWindow(8_000))
        assertFalse(BleDutyCycle.isActiveWindow(29_999))
        assertTrue(BleDutyCycle.isActiveWindow(30_000))
        assertTrue(BleDutyCycle.isActiveWindow(60_001))
    }

    @Test
    fun `temps restant avant changement de phase`() {
        assertEquals(8_000L, BleDutyCycle.msUntilNextPhase(0))
        assertEquals(1L, BleDutyCycle.msUntilNextPhase(7_999))
        assertEquals(22_000L, BleDutyCycle.msUntilNextPhase(8_000))
        assertEquals(1L, BleDutyCycle.msUntilNextPhase(29_999))
        assertEquals(8_000L, BleDutyCycle.msUntilNextPhase(30_000))
    }
}
