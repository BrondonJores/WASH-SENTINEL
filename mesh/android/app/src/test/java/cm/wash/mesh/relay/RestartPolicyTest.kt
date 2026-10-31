package cm.wash.mesh.relay

import org.junit.Assert.assertEquals
import org.junit.Test

class RestartPolicyTest {

    @Test
    fun `backoff exponentiel depuis 5 s`() {
        assertEquals(5_000L, RestartPolicy.nextDelayMs(0))
        assertEquals(10_000L, RestartPolicy.nextDelayMs(1))
        assertEquals(20_000L, RestartPolicy.nextDelayMs(2))
        assertEquals(40_000L, RestartPolicy.nextDelayMs(3))
    }

    @Test
    fun `plafond à 5 minutes`() {
        assertEquals(300_000L, RestartPolicy.nextDelayMs(10))
        assertEquals(300_000L, RestartPolicy.nextDelayMs(100))
    }

    @Test
    fun `tentative négative donne la base`() {
        assertEquals(5_000L, RestartPolicy.nextDelayMs(-1))
    }
}
