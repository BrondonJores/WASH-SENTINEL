<?php

namespace Tests\Feature;

use App\Models\Incident;
use App\Models\MeshBundle;
use App\Models\Report;
use App\Models\School;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Cache;
use Tests\TestCase;

class WashUssdTest extends TestCase
{
    use RefreshDatabase;

    private const PHONE = '+237600000042';

    private function school(): School
    {
        return School::create(['name' => 'EP Yokadouma', 'code' => 'CE042', 'district' => 'Est']);
    }

    /**
     * Requête passerelle générique style Africa's Talking (form-encoded).
     */
    private function ussd(string $sessionId, string $text, string $phone = self::PHONE)
    {
        return $this->post('/api/v1/mesh/ussd', [
            'sessionId' => $sessionId,
            'serviceCode' => '*123#',
            'phoneNumber' => $phone,
            'text' => $text,
        ]);
    }

    public function test_home_menu_returns_con(): void
    {
        $response = $this->ussd('sess-home-1', '');

        $response->assertOk();
        $body = (string) $response->getContent();
        $this->assertStringStartsWith('CON ', $body);
        $this->assertStringContainsString('WASH-SENTINEL', $body);
        $this->assertStringContainsString('1. Signaler', $body);
    }

    public function test_full_flow_creates_incident_with_ticket(): void
    {
        $this->school();
        $sid = 'sess-full-1';

        // La passerelle rejoue chaque écran : text cumulatif, une requête par étape.
        $this->ussd($sid, '')->assertOk();
        $this->ussd($sid, '1')->assertOk();
        $this->ussd($sid, '1*CE042')->assertOk();
        $this->ussd($sid, '1*CE042*1')->assertOk();
        $this->ussd($sid, '1*CE042*1*2')->assertOk();

        $confirm = $this->ussd($sid, '1*CE042*1*2*POMPE CASSEE');
        $body = (string) $confirm->getContent();
        $this->assertStringStartsWith('CON ', $body);
        $this->assertStringContainsString('CE042', $body);
        $this->assertStringContainsString('Confirmer', $body);

        $final = $this->ussd($sid, '1*CE042*1*2*POMPE CASSEE*1');
        $final->assertOk();
        $end = (string) $final->getContent();
        $this->assertStringStartsWith('END ', $end);
        $this->assertStringContainsString('Ticket:', $end);

        $this->assertDatabaseHas('reports', ['source' => 'ussd']);
        $this->assertDatabaseHas('mesh_bundles', ['status' => 'delivered']);
        $bundle = MeshBundle::first();
        $this->assertStringStartsWith('[USSD]', (string) $bundle->message);
        $this->assertStringContainsString('(URGENT)', (string) $bundle->message);
        $this->assertEquals(1, Incident::count());
    }

    public function test_no_pii_is_persisted(): void
    {
        $this->school();
        $sid = 'sess-pii-1';

        foreach (['', '1', '1*CE042', '1*CE042*2', '1*CE042*2*1', '1*CE042*2*1*9'] as $text) {
            $this->ussd($sid, $text)->assertOk();
        }
        $this->ussd($sid, '1*CE042*2*1*9*1')->assertOk();

        $expectedOrigin = 'ussd:'.substr(hash('sha256', self::PHONE), 0, 16);
        $this->assertDatabaseHas('mesh_bundles', ['origin_node_id' => $expectedOrigin]);

        $bundle = MeshBundle::first();
        $payload = json_encode($bundle->payload);
        $this->assertStringNotContainsString(self::PHONE, (string) $bundle->origin_node_id);
        $this->assertStringNotContainsString(self::PHONE, (string) $payload);
        $this->assertStringNotContainsString(self::PHONE, (string) $bundle->message);

        $report = Report::first();
        $this->assertStringNotContainsString(self::PHONE, (string) $report->message);

        // Session oubliée après END ; le marqueur d'idempotence ne garde que le ticket.
        $this->assertNull(Cache::get('ussd:session:sess-pii-1'));
        $done = Cache::get('ussd:done:sess-pii-1');
        $this->assertNotNull($done);
        $this->assertStringNotContainsString(self::PHONE, (string) json_encode($done));
    }

    public function test_invalid_school_code_retries_then_ends(): void
    {
        $this->school();
        $sid = 'sess-badcode-1';

        $this->ussd($sid, '')->assertOk();
        $this->ussd($sid, '1')->assertOk();

        $retry = $this->ussd($sid, '1*XXX');
        $retryBody = (string) $retry->getContent();
        $this->assertStringStartsWith('CON ', $retryBody);
        $this->assertStringContainsString('inconnu', $retryBody);

        $this->ussd($sid, '1*XXX*YYY');

        $final = $this->ussd($sid, '1*XXX*YYY*ZZZ');
        $finalBody = (string) $final->getContent();
        $this->assertStringStartsWith('END ', $finalBody);
        $this->assertStringContainsString('introuvable', $finalBody);

        $this->assertEquals(0, Report::where('source', 'ussd')->count());
    }

    public function test_invalid_type_choice_reshows_menu(): void
    {
        $this->school();
        $sid = 'sess-badtype-1';

        $this->ussd($sid, '');
        $this->ussd($sid, '1');
        $this->ussd($sid, '1*CE042');

        $response = $this->ussd($sid, '1*CE042*9');
        $body = (string) $response->getContent();
        $this->assertStringStartsWith('CON ', $body);
        $this->assertStringContainsString('Choix invalide', $body);

        // La session continue : un choix valide passe à l'urgence.
        $next = $this->ussd($sid, '1*CE042*9*2');
        $this->assertStringContainsString('Urgence', (string) $next->getContent());
    }

    public function test_cancel_with_zero_ends_session_without_incident(): void
    {
        $this->school();
        $sid = 'sess-cancel-1';

        $this->ussd($sid, '');
        $this->ussd($sid, '1');
        $this->ussd($sid, '1*CE042');

        $response = $this->ussd($sid, '1*CE042*0');
        $body = (string) $response->getContent();
        $this->assertStringStartsWith('END ', $body);

        $this->assertEquals(0, Report::where('source', 'ussd')->count());
        $this->assertEquals(0, MeshBundle::count());
    }

    public function test_gateway_retry_after_confirm_returns_same_ticket(): void
    {
        $this->school();
        $sid = 'sess-retry-1';

        foreach (['', '1', '1*CE042', '1*CE042*1', '1*CE042*1*1', '1*CE042*1*1*9'] as $text) {
            $this->ussd($sid, $text)->assertOk();
        }
        $first = (string) $this->ussd($sid, '1*CE042*1*1*9*1')->getContent();
        $this->assertStringStartsWith('END ', $first);

        // Rejeu passerelle : même sessionId + même text → même ticket, 1 seul incident.
        $replay = (string) $this->ussd($sid, '1*CE042*1*1*9*1')->getContent();
        $this->assertStringStartsWith('END ', $replay);
        $this->assertStringContainsString('deja enregistre', $replay);

        preg_match('/Ticket:\s*(\S+)/', $first, $m1);
        preg_match('/Ticket:\s*(\S+)/', $replay, $m2);
        $this->assertNotEmpty($m1[1] ?? null);
        $this->assertEquals($m1[1], $m2[1] ?? null);
        $this->assertEquals(1, Report::where('source', 'ussd')->count());
    }

    public function test_duplicate_report_from_same_caller_is_detected(): void
    {
        $this->school();

        $flow = function (string $sid): string {
            $texts = ['', '1', '1*CE042', '1*CE042*3', '1*CE042*3*1', '1*CE042*3*1*EAU TROUBLE', '1*CE042*3*1*EAU TROUBLE*1'];
            $last = '';
            foreach ($texts as $text) {
                $last = (string) $this->ussd($sid, $text)->getContent();
            }

            return $last;
        };

        $first = $flow('sess-dedup-1');
        $this->assertStringStartsWith('END ', $first);
        $this->assertStringContainsString('enregistre', $first);

        $second = $flow('sess-dedup-2');
        $this->assertStringStartsWith('END ', $second);
        $this->assertStringContainsString('deja recu', $second);

        $this->assertEquals(1, Report::where('source', 'ussd')->count());
    }

    public function test_quota_is_enforced(): void
    {
        config(['services.mesh.sms_quota_per_sender' => 0]);
        $this->school();
        $sid = 'sess-quota-1';

        foreach (['', '1', '1*CE042', '1*CE042*1', '1*CE042*1*1', '1*CE042*1*1*9'] as $text) {
            $this->ussd($sid, $text)->assertOk();
        }
        $final = (string) $this->ussd($sid, '1*CE042*1*1*9*1')->getContent();
        $this->assertStringStartsWith('END ', $final);
        $this->assertStringContainsString('Quota', $final);
        $this->assertEquals(0, Report::where('source', 'ussd')->count());
    }

    public function test_get_probe_mirrors_post_flow(): void
    {
        $this->school();

        $response = $this->get('/api/v1/mesh/ussd?'.http_build_query([
            'sessionId' => 'sess-probe-1',
            'serviceCode' => '*123#',
            'phoneNumber' => self::PHONE,
            'text' => '',
        ]));
        $response->assertOk();
        $this->assertStringStartsWith('CON ', (string) $response->getContent());

        $this->get('/api/v1/mesh/ussd?'.http_build_query([
            'sessionId' => 'sess-probe-1',
            'serviceCode' => '*123#',
            'phoneNumber' => self::PHONE,
            'text' => '1',
        ]))->assertOk();

        $next = $this->get('/api/v1/mesh/ussd?'.http_build_query([
            'sessionId' => 'sess-probe-1',
            'serviceCode' => '*123#',
            'phoneNumber' => self::PHONE,
            'text' => '1*CE042',
        ]));
        $this->assertStringContainsString('Type de panne', (string) $next->getContent());
    }

    public function test_missing_session_id_is_rejected(): void
    {
        $this->post('/api/v1/mesh/ussd', [
            'phoneNumber' => self::PHONE,
            'text' => '',
        ])->assertStatus(422);
    }

    public function test_lenient_restart_when_first_empty_text_is_skipped(): void
    {
        $this->school();

        // Certaines passerelles envoient directement le premier choix.
        $response = $this->ussd('sess-lenient-1', '1');
        $body = (string) $response->getContent();
        $this->assertStringStartsWith('CON ', $body);
        $this->assertStringContainsString('code ecole', $body);
    }
}
