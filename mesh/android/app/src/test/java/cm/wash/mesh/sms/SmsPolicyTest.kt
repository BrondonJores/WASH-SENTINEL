package cm.wash.mesh.sms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SmsPolicyTest {

    @Test
    fun `sms valide minimal`() {
        val p = SmsPolicy.parse("WASH DOU-BON-001 P")
        assertTrue(p.ok)
        assertEquals("DOU-BON-001", p.code)
        assertEquals('P', p.type)
        assertNull(p.detail)
    }

    @Test
    fun `mot-clé EAU accepté`() {
        val p = SmsPolicy.parse("EAU DOU-LIB-002 L latrines bouchées")
        assertTrue(p.ok)
        assertEquals('L', p.type)
        assertEquals("LATRINES BOUCHEES", p.detail)
    }

    @Test
    fun `casse accents et synonymes tolérés comme backend`() {
        val p = SmsPolicy.parse("wash dou-bon-001 pompe cassée depuis lundi")
        assertTrue(p.ok)
        assertEquals("DOU-BON-001", p.code)
        assertEquals('P', p.type)
        assertEquals("CASSÉE DEPUIS LUNDI".replace("É", "E"), p.detail)
    }

    @Test
    fun `synonymes de types reconnus`() {
        assertEquals('L', SmsPolicy.parse("WASH C1 WC").type)
        assertEquals('E', SmsPolicy.parse("WASH C1 EAU").type)
        assertEquals('H', SmsPolicy.parse("WASH C1 SAVON").type)
        assertEquals('P', SmsPolicy.parse("WASH C1 FORAGE").type)
    }

    @Test
    fun `formats invalides rejetés`() {
        assertFalse(SmsPolicy.parse("WASH DOU-BON-001").ok) // trop court
        assertFalse(SmsPolicy.parse("BONJOUR DOU P").ok) // mot-clé inconnu
        assertFalse(SmsPolicy.parse("WASH DOU X").ok) // type inconnu
        assertFalse(SmsPolicy.parse("WASH @@@ P").ok) // code invalide
        assertFalse(SmsPolicy.parse("").ok)
    }

    @Test
    fun `allowlist exacte, vide égale ouvert`() {
        assertTrue(SmsPolicy.isAllowlisted("+237600000000", ""))
        assertTrue(SmsPolicy.isAllowlisted("+237600000000", "  "))
        assertTrue(SmsPolicy.isAllowlisted("+237600000000", "+237611111111, +237600000000"))
        assertFalse(SmsPolicy.isAllowlisted("+237600000000", "+237611111111"))
        assertFalse(SmsPolicy.isAllowlisted("+2376000000000", "+237600000000")) // pas de préfixe
    }

    @Test
    fun `quota journalier aligné sur 10`() {
        assertEquals(10, SmsPolicy.DEFAULT_QUOTA)
        assertFalse(SmsPolicy.quotaExceeded(9))
        assertTrue(SmsPolicy.quotaExceeded(10))
        assertTrue(SmsPolicy.quotaExceeded(11))
    }
}
