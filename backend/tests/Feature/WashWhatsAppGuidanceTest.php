<?php

namespace Tests\Feature;

use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\Report;
use App\Models\School;
use App\Models\SchoolContact;
use App\Services\MetaWhatsAppService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Notification;
use Tests\Support\FakeWhatsAppService;
use Tests\TestCase;

class WashWhatsAppGuidanceTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        FakeWhatsAppService::reset();
        $this->app->bind(WhatsAppClient::class, FakeWhatsAppService::class);
        config(['whatsapp.simulator' => true]);
        Notification::fake();
    }

    protected function fixture(string $name): array
    {
        return json_decode(file_get_contents(base_path("tests/Fixtures/whatsapp/{$name}.json")), true);
    }

    protected function textPayload(string $body, string $from = '237600112233', string $id = 'wamid.GUIDE001'): array
    {
        $payload = $this->fixture('text');
        $payload['entry'][0]['changes'][0]['value']['messages'][0] = [
            'from' => $from,
            'id' => $id,
            'timestamp' => '1760000000',
            'type' => 'text',
            'text' => ['body' => $body],
        ];

        return $payload;
    }

    protected function triageResponse()
    {
        return Http::response([
            'raw_text' => 'Robinet qui fuit.',
            'extraction' => [
                'data' => [
                    'school_detected' => null,
                    'infrastructure_type' => 'water_point',
                    'issue_type' => 'leak',
                    'urgency_level' => 'medium',
                    'estimated_affected_students' => 0,
                    'health_hazard_risk' => 'low',
                    'short_summary' => 'Fuite sur un robinet.',
                ],
                'model_used' => 'test-llm',
                'confidence_score' => 0.9,
            ],
        ], 200);
    }

    protected function fakeTriage(): void
    {
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);
    }

    protected function fakeDuplicate(int $incidentId): void
    {
        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/wash/check-duplicates' => Http::response([
                'is_duplicate' => true,
                'matched_incident_id' => $incidentId,
                'similarity_score' => 0.95,
            ], 200),
        ]);
    }

    protected function audioPayload(string $id, string $from = '237600112233'): array
    {
        $payload = $this->fixture('audio');
        $payload['entry'][0]['changes'][0]['value']['messages'][0]['id'] = $id;
        $payload['entry'][0]['changes'][0]['value']['messages'][0]['from'] = $from;

        return $payload;
    }

    /** Payload avec des messages bruts arbitraires (cas extrêmes). */
    protected function rawPayload(array $messages): array
    {
        $payload = $this->fixture('text');
        $payload['entry'][0]['changes'][0]['value']['messages'] = $messages;

        return $payload;
    }

    protected function rawMessage(string $type, array $extra = [], string $from = '237600112233', string $id = 'wamid.HARD001'): array
    {
        return array_merge([
            'from' => $from,
            'id' => $id,
            'timestamp' => '1760000000',
            'type' => $type,
        ], $extra);
    }

    /**
     * Enchaîne vocal initial + clic Non, retourne l'incident pending.
     * Les stubs URL Http::fake() s'accumulent (le 1er gagne) : la transcription
     * de la correction vocale éventuelle est fournie via UNE séquence unique.
     */
    protected function seedPendingClarification(?string $correctionTranscript = null): Incident
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        $transcribe = $correctionTranscript === null
            ? Http::response(['transcript' => 'Le robinet du bloc A fuit beaucoup.'], 200)
            : Http::sequence()
                ->push(['transcript' => 'Le robinet du bloc A fuit beaucoup.'])
                ->push(['transcript' => $correctionTranscript]);
        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/voice/transcribe' => $transcribe,
        ]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('audio'))->assertOk();
        $incident = Incident::first();
        $this->assertNotNull($incident);

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('interactive_no'))->assertOk();
        FakeWhatsAppService::$sent = [];

        return $incident;
    }

    /** Stub doublon ajouté APRÈS coup (motif neuf : pas de conflit avec le 1er fake). */
    protected function fakeDuplicateAfterwards(int $incidentId): void
    {
        Http::fake([
            '*/v1/wash/check-duplicates' => Http::response([
                'is_duplicate' => true,
                'matched_incident_id' => $incidentId,
                'similarity_score' => 0.95,
            ], 200),
        ]);
    }

    /** Textes envoyés (hors boutons interactifs / audio). */
    protected function sentTexts(): array
    {
        return array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'text'
        ));
    }

    /** Boutons interactifs envoyés. */
    protected function sentInteractive(): array
    {
        return array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'interactive'
        ));
    }

    protected function seedContact(): School
    {
        $school = School::create([
            'name' => 'École de Bonanjo', 'code' => 'DOU-BON-001', 'district' => 'Wouri',
        ]);
        SchoolContact::create([
            'school_id' => $school->id, 'phone' => '237600112233',
            'name' => 'Clarisse Eko', 'role' => 'directrice', 'is_verified' => true,
        ]);

        return $school;
    }

    public function test_unknown_school_gets_guided_ecole_reply(): void
    {
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('unknown'))->assertOk();

        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('aucune école', $reply);
        $this->assertStringContainsString('ECOLE', $reply);
        $this->assertStringContainsString('De quelle école parlez-vous', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_unknown_school_with_ecole_format_is_acknowledged(): void
    {
        $this->postJson(
            '/api/v1/whatsapp/webhook',
            $this->textPayload('ECOLE Collège Saint-Michel', '237699999999', 'wamid.GUIDE002')
        )->assertOk();

        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('Collège Saint-Michel', $reply);
        $this->assertStringContainsString('aucune école', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_unreadable_audio_gets_guided_reply(): void
    {
        $this->seedContact();
        FakeWhatsAppService::$media['MEDIA_AUDIO_1'] = [
            'bytes' => '', 'mime' => 'audio/ogg', 'filename' => 'wa-empty.ogg',
        ];

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('audio'))->assertOk();

        $this->assertEquals(0, Incident::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString("pas compris", $reply);
        $this->assertStringContainsString('Réenregistrez', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_duplicate_gets_guided_reply(): void
    {
        $this->seedContact();
        $this->fakeTriage();
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('text'))->assertOk();
        $this->assertEquals(1, Incident::count());
        $reference = Incident::first()->reference_code;

        $this->fakeDuplicate(Incident::first()->id);
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Le robinet du bloc A fuit toujours autant.',
            '237600112233',
            'wamid.GUIDE003'
        ))->assertOk();

        $this->assertEquals(1, Incident::count());
        $this->assertCount(2, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[1]['message'];
        $this->assertStringContainsString('Déjà reçu', $reply);
        $this->assertStringContainsString($reference, $reply);
        $this->assertStringContainsString('suivi', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_off_topic_gets_guided_reply_with_examples(): void
    {
        $this->seedContact();

        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Quel est le menu de la cantine demain ?',
            '237600112233',
            'wamid.GUIDE004'
        ))->assertOk();

        $this->assertEquals(0, Incident::count());
        $this->assertEquals(0, Report::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('robinet', $reply);
        $this->assertStringContainsString('toilettes', $reply);
        $this->assertStringContainsString('savon', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_creation_ok_gets_recap_reference_and_next_steps(): void
    {
        $this->seedContact();
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('text'))->assertOk();

        $incident = Incident::first();
        $this->assertNotNull($incident);
        $this->assertStringStartsWith('WASH-', $incident->reference_code);

        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('enregistré', $reply);
        $this->assertStringContainsString($incident->reference_code, $reply);
        $this->assertStringContainsString('Fuite sur un robinet', $reply);
        $this->assertStringContainsString('La suite', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_simulator_path_sends_without_http_call(): void
    {
        config(['whatsapp.simulator' => true]);
        Http::fake();

        $response = (new MetaWhatsAppService())->sendText(
            '237600112233', 'Déjà reçu ! Incident WASH-2026-ABCDEF suivi par nos équipes.'
        );

        $this->assertStringStartsWith('sim-', $response['messages'][0]['id']);
        Http::assertNothingSent();
    }

    public function test_live_path_posts_guided_text_to_graph_api(): void
    {
        config([
            'whatsapp.simulator' => false,
            'whatsapp.token' => 'test-token',
            'whatsapp.phone_number_id' => '999',
        ]);
        Http::fake([
            '*' => Http::response(['messages' => [['id' => 'wamid.LIVE001']]], 200),
        ]);

        (new MetaWhatsAppService())->sendText(
            '237600112233', 'Merci ! Incident WASH-2026-ABCDEF enregistré : fuite.'
        );

        Http::assertSent(fn ($request) => str_contains($request->url(), '999/messages')
            && ($request['text']['body'] ?? '') === 'Merci ! Incident WASH-2026-ABCDEF enregistré : fuite.');
    }

    public function test_oversized_audio_gets_guided_reply_without_incident(): void
    {
        // Le faux média fait 22 o ('fake-voice-note-bytes') : plafond à 10 o.
        config(['whatsapp.max_media_bytes' => 10]);
        $this->seedContact();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('audio'))->assertOk();

        $this->assertEquals(0, Incident::count());
        $this->assertEquals(0, Report::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('trop lourde', $reply);
        $this->assertStringContainsString('renvoie plus court', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_oversized_photo_gets_guided_reply_without_incident(): void
    {
        config(['whatsapp.max_media_bytes' => 10]);
        $this->seedContact();
        FakeWhatsAppService::$media['MEDIA_PHOTO_BIG'] = [
            'bytes' => str_repeat('x', 64), 'mime' => 'image/jpeg', 'filename' => 'wa-big.jpg',
        ];

        $payload = $this->fixture('audio');
        $payload['entry'][0]['changes'][0]['value']['messages'][0] = [
            'from' => '237600112233',
            'id' => 'wamid.PHOTO_BIG_001',
            'timestamp' => '1760000000',
            'type' => 'image',
            'image' => ['id' => 'MEDIA_PHOTO_BIG', 'mime_type' => 'image/jpeg', 'caption' => 'fuite au bloc A'],
        ];

        $this->postJson('/api/v1/whatsapp/webhook', $payload)->assertOk();

        $this->assertEquals(0, Incident::count());
        $this->assertEquals(0, Report::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('trop lourde', $reply);
        $this->assertStringContainsString('plus légère', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_oversized_declared_size_rejected_before_body(): void
    {
        $this->seedContact();
        // Taille déclarée (métadonnées) > plafond par défaut (10 Mo),
        // même avec un petit corps : rejeté sans incident.
        FakeWhatsAppService::$media['MEDIA_AUDIO_BIG'] = [
            'bytes' => 'tiny', 'mime' => 'audio/ogg', 'filename' => 'wa-big.ogg',
            'file_size' => 20 * 1024 * 1024,
        ];

        $payload = $this->fixture('audio');
        $payload['entry'][0]['changes'][0]['value']['messages'][0]['id'] = 'wamid.AUDIO_BIG_001';
        $payload['entry'][0]['changes'][0]['value']['messages'][0]['audio']['id'] = 'MEDIA_AUDIO_BIG';

        $this->postJson('/api/v1/whatsapp/webhook', $payload)->assertOk();

        $this->assertEquals(0, Incident::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $this->assertStringContainsString('trop lourde', FakeWhatsAppService::$sent[0]['message']);
    }

    // --------------------------------------------------------------
    // Clarification après Non : rattachée au pending, jamais perdue.
    // --------------------------------------------------------------

    public function test_no_then_text_correction_without_keyword_updates_pending_incident(): void
    {
        $incident = $this->seedPendingClarification();

        // Correction TEXTE sans mot-clé eau/hygiène (ancien bug : hors-sujet).
        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            "Non, c'est au bloc B, pas au bloc A.",
            '237600112233',
            'wamid.CLARIFY_TEXT_001'
        ));

        $this->assertEquals('clarification_applied', $results[0]['status'] ?? null);
        $this->assertFalse($results[0]['is_duplicate'] ?? true);
        $this->assertEquals($incident->id, $results[0]['incident_id'] ?? null);

        // Incident inchangé (pas de doublon, pas de nouvel incident), Report rattaché.
        $this->assertEquals(1, Incident::count());
        $this->assertEquals(2, Report::count());
        $correction = Report::latest('id')->first();
        $this->assertEquals($incident->id, $correction->incident_id);
        $this->assertFalse((bool) $correction->is_duplicate);
        $this->assertEquals('text', $correction->channel);
        $this->assertEquals('whatsapp', $correction->source);
        $this->assertStringContainsString('bloc B', $correction->raw_content);

        // Résumé incident mis à jour avec la correction.
        $this->assertStringContainsString('bloc B', (string) $incident->fresh()->ai_summary);

        // Réponse FR de correction + re-confirmation, JAMAIS Déjà reçu / hors-sujet.
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $reply = $texts[0]['message'];
        $this->assertStringContainsString("J'ai corrigé", $reply);
        $this->assertStringContainsString("C'est bien ça", $reply);
        $this->assertStringContainsString('bloc B', $reply);
        $this->assertStringNotContainsString('Déjà reçu', $reply);
        $this->assertStringNotContainsString('Ici on signale', $reply);
        $this->assertLessThan(400, mb_strlen($reply));

        $interactive = $this->sentInteractive();
        $this->assertCount(1, $interactive);
        $ids = array_column($interactive[0]['buttons'] ?? [], 'id');
        $this->assertContains('wash_oui', $ids);
        $this->assertContains('wash_non', $ids);

        // Pending conservé : Oui confirme l'incident corrigé.
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('interactive_yes'))->assertOk();
        $this->assertContains('confirme-usager', $incident->fresh()->ai_tags ?? []);
        $last = end(FakeWhatsAppService::$sent);
        $this->assertStringContainsString('confirmé', $last['message']);
    }

    public function test_no_then_voice_correction_is_attached_not_duplicate(): void
    {
        $incident = $this->seedPendingClarification("C'est au bloc B, la deuxième porte.");

        // Le triage verrait un doublon (ancien bug : « Déjà reçu », correction perdue).
        $this->fakeDuplicateAfterwards($incident->id);

        $this->postJson('/api/v1/whatsapp/webhook', $this->audioPayload('wamid.CLARIFY_VOICE_001'))
            ->assertOk();

        // Incident inchangé, Report vocal rattaché, pas de doublon.
        $this->assertEquals(1, Incident::count());
        $this->assertEquals(2, Report::count());
        $correction = Report::latest('id')->first();
        $this->assertEquals($incident->id, $correction->incident_id);
        $this->assertFalse((bool) $correction->is_duplicate);
        $this->assertEquals('voice', $correction->channel);
        $this->assertNotNull($correction->audio_path);
        $this->assertStringContainsString('deuxième porte', (string) $incident->fresh()->ai_summary);

        // Réponse FR de correction + boutons Oui/Non renvoyés.
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $reply = $texts[0]['message'];
        $this->assertStringContainsString("J'ai corrigé", $reply);
        $this->assertStringContainsString("C'est bien ça", $reply);
        $this->assertStringNotContainsString('Déjà reçu', $reply);
        $this->assertStringNotContainsString('Ici on signale', $reply);
        $this->assertLessThan(400, mb_strlen($reply));

        $interactive = $this->sentInteractive();
        $this->assertCount(1, $interactive);
        $ids = array_column($interactive[0]['buttons'] ?? [], 'id');
        $this->assertContains('wash_oui', $ids);
        $this->assertContains('wash_non', $ids);
    }

    public function test_clarification_expired_falls_back_to_normal_triage(): void
    {
        $incident = $this->seedPendingClarification();

        // Silence/expiration : la clé clarify a disparu -> triage normal pur.
        Cache::forget('wash.whatsapp.clarify.237600112233');
        $this->fakeTriage();

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Le robinet du bloc A fuit toujours autant.',
            '237600112233',
            'wamid.CLARIFY_EXPIRED_001'
        ));

        $this->assertEquals('triaged', $results[0]['status'] ?? null);
        $this->assertNotEquals($incident->id, $results[0]['incident_id'] ?? null);

        // Nouvel incident créé, réponse normale sans note de repli.
        $this->assertEquals(2, Incident::count());
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('enregistré', $texts[0]['message']);
        $this->assertStringNotContainsString('pas retrouvé votre signalement', $texts[0]['message']);
    }

    public function test_clarification_deleted_incident_falls_back_to_normal_triage_with_note(): void
    {
        $incident = $this->seedPendingClarification();

        // Incident pending supprimé -> repli : triage normal + note FR.
        $incident->delete();
        $this->fakeTriage();

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Le robinet du bloc A fuit toujours autant.',
            '237600112233',
            'wamid.CLARIFY_STALE_001'
        ));

        $this->assertEquals('triaged', $results[0]['status'] ?? null);

        $this->assertEquals(1, Incident::count());
        $fresh = Incident::first();
        $this->assertEquals($fresh->id, $results[0]['incident_id'] ?? null);

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $reply = $texts[0]['message'];
        $this->assertStringContainsString('pas retrouvé votre signalement', $reply);
        $this->assertStringContainsString('enregistré', $reply);
        $this->assertStringContainsString($fresh->reference_code, $reply);
    }

    // --------------------------------------------------------------
    // Blindage cas extrêmes : types non supportés, webhooks malformés,
    // textes limites, langue, double opt-in, interruptions, pannes.
    // --------------------------------------------------------------

    public function test_unsupported_types_get_guided_reply_never_silent(): void
    {
        $this->seedContact();
        $types = ['sticker', 'reaction', 'location', 'contacts', 'video', 'document', 'poll', 'order'];
        $messages = [];
        foreach ($types as $i => $type) {
            $messages[] = $this->rawMessage($type, [], '237600112233', "wamid.HARD.UNSUP{$i}");
        }

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->rawPayload($messages));

        $this->assertCount(8, $results);
        foreach ($results as $result) {
            $this->assertEquals('unsupported', $result['status'] ?? null);
        }
        $this->assertEquals(0, Incident::count());
        $this->assertEquals(0, Report::count());
        $texts = $this->sentTexts();
        $this->assertCount(8, $texts);
        foreach ($texts as $sent) {
            $this->assertStringContainsString('note vocale', $sent['message']);
            $this->assertStringContainsString('école + panne', $sent['message']);
            $this->assertLessThan(400, mb_strlen($sent['message']));
        }
    }

    public function test_empty_and_status_only_payloads_are_acked_silently(): void
    {
        $this->seedContact();
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', [])->assertOk()->assertJson(['received' => true]);
        $this->postJson('/api/v1/whatsapp/webhook', ['object' => 'whatsapp_business_account', 'entry' => []])->assertOk();

        // Accusé Meta (statuts de livraison) : pas de message usager, pas de réponse.
        $statuses = $this->fixture('text');
        unset($statuses['entry'][0]['changes'][0]['value']['messages']);
        $statuses['entry'][0]['changes'][0]['value']['statuses'] = [
            ['id' => 'wamid.STATUS001', 'status' => 'delivered'],
        ];
        $this->postJson('/api/v1/whatsapp/webhook', $statuses)->assertOk();

        $this->assertEquals(0, Incident::count());
        $this->assertCount(0, FakeWhatsAppService::$sent);
    }

    public function test_malformed_payload_levels_are_ignored_without_crash(): void
    {
        $this->seedContact();
        $this->fakeTriage();

        $service = app(\App\Services\WashWhatsAppService::class);

        // Niveaux malformés : ignorés, zéro résultat, zéro envoi, zéro crash.
        $this->assertSame([], $service->handlePayload(['entry' => 'nope']));
        $this->assertSame([], $service->handlePayload(['entry' => [['changes' => 'nope']]]));
        $this->assertSame([], $service->handlePayload(['entry' => [['changes' => [['value' => ['messages' => 'nope']]]]]]));
        $this->assertSame([], $service->handlePayload(['entry' => [['changes' => [['value' => ['messages' => ['oops', 42]]]]]]]));

        // Message sans expéditeur : ignoré (rien à qui répondre), pas d'envoi.
        $results = $service->handlePayload($this->rawPayload([
            ['id' => 'wamid.HARD.NOFROM', 'timestamp' => '1760000000', 'type' => 'text', 'text' => ['body' => 'robinet cassé']],
        ]));
        $this->assertEquals('ignored', $results[0]['status'] ?? null);

        // Corps non-texte (tableau) : guidage, pas de crash.
        $results = $service->handlePayload($this->rawPayload([
            $this->rawMessage('text', ['text' => ['body' => ['weird' => 'array']]], '237600112233', 'wamid.HARD.BADBODY'),
        ]));
        $this->assertEquals('unsupported', $results[0]['status'] ?? null);

        $this->assertEquals(0, Incident::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
    }

    public function test_empty_text_gets_guided_reply_without_incident(): void
    {
        $this->seedContact();

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->rawPayload([
            $this->rawMessage('text', ['text' => ['body' => '']], '237600112233', 'wamid.HARD.EMPTY001'),
            $this->rawMessage('text', ['text' => ['body' => '   ']], '237600112233', 'wamid.HARD.EMPTY002'),
        ]));

        $this->assertCount(2, $results);
        $this->assertEquals(0, Incident::count());
        $texts = $this->sentTexts();
        $this->assertCount(2, $texts);
        foreach ($texts as $sent) {
            $this->assertStringContainsString('une phrase', $sent['message']);
            $this->assertLessThan(400, mb_strlen($sent['message']));
        }
    }

    public function test_ultra_long_report_is_capped_and_still_triaged(): void
    {
        $this->seedContact();
        $this->fakeTriage();

        $body = 'Le robinet du bloc A fuit beaucoup. ' . str_repeat("Encore de l'eau partout au bloc A. ", 200);
        $this->assertGreaterThan(2000, mb_strlen($body));

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload($body, '237600112233', 'wamid.HARD.LONG001'));

        $this->assertEquals('triaged', $results[0]['status'] ?? null);
        $this->assertEquals(1, Incident::count());
        // Le triage reçoit le texte plafonné, jamais les 6000+ caractères.
        Http::assertSent(function ($request) {
            return str_contains($request->url(), '/v1/wash/triage')
                && mb_strlen((string) ($request['text'] ?? '')) <= 2000;
        });
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertLessThan(400, mb_strlen($texts[0]['message']));
    }

    public function test_unverified_contact_gets_validation_reply_without_incident(): void
    {
        $school = $this->seedContact();
        SchoolContact::where('school_id', $school->id)->update(['is_verified' => false]);
        $this->fakeTriage();

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Le robinet du bloc A fuit beaucoup.',
            '237600112233',
            'wamid.HARD.UNVERIFIED001'
        ));

        $this->assertEquals('unverified_contact', $results[0]['status'] ?? null);
        $this->assertEquals(0, Incident::count());
        $this->assertEquals(0, Report::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('pas encore validé', $reply);
        $this->assertStringContainsString('directeur', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_unknown_school_with_school_format_is_acknowledged_in_english(): void
    {
        $this->postJson(
            '/api/v1/whatsapp/webhook',
            $this->textPayload('SCHOOL Saint-Michel College', '237699999999', 'wamid.HARD.SCHOOL001')
        )->assertOk();

        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('Saint-Michel College', $reply);
        $this->assertStringContainsString('not linked', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_unknown_english_number_gets_english_registration_reply(): void
    {
        $this->postJson(
            '/api/v1/whatsapp/webhook',
            $this->textPayload('Hello, there is no water at our school, please help.', '237699999999', 'wamid.HARD.UNKNOWNEN001')
        )->assertOk();

        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('SCHOOL', $reply);
        $this->assertStringContainsString('not linked', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_mixed_french_english_report_stays_french(): void
    {
        $this->seedContact();
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Hello, sorry : le robinet du bloc A fuit beaucoup, please help !',
            '237600112233',
            'wamid.HARD.MIX001'
        ))->assertOk();

        $this->assertEquals(1, Incident::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('enregistré', $reply);
        $this->assertStringNotContainsString('Priority', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_new_report_interrupts_stale_pending_yes_goes_stale(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/voice/transcribe' => Http::response(['transcript' => 'Le robinet du bloc A fuit beaucoup.'], 200),
        ]);

        // Vocal → incident A + pending Oui/Non.
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('audio'))->assertOk();
        $incidentA = Incident::first();
        $this->assertNotNull($incidentA);

        // Nouveau signalement texte → incident B, pending A oublié.
        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Les toilettes du bloc B sont bouchées, ça déborde.',
            '237600112233',
            'wamid.HARD.INTERRUPT001'
        ));
        $this->assertEquals('triaged', $results[0]['status'] ?? null);
        $this->assertEquals(2, Incident::count());

        // Le vieux « Oui » ne confirme plus : réponse guidée périmée.
        $yes = $this->fixture('interactive_yes');
        $yes['entry'][0]['changes'][0]['value']['messages'][0]['id'] = 'wamid.HARD.INTERRUPT_YES';
        $results = $service->handlePayload($yes);
        $this->assertEquals('confirmed_stale', $results[0]['status'] ?? null);
        $this->assertNotContains('confirme-usager', $incidentA->fresh()->ai_tags ?? []);
    }

    public function test_expired_pending_yes_gets_guided_stale_reply(): void
    {
        $incident = $this->seedPendingClarification();
        // Expiration 24h simulée : clés parties → Oui périmé, pas de confirm.
        Cache::forget('wash.whatsapp.pending.237600112233');
        Cache::forget('wash.whatsapp.clarify.237600112233');

        $yes = $this->fixture('interactive_yes');
        $yes['entry'][0]['changes'][0]['value']['messages'][0]['id'] = 'wamid.HARD.EXPIRED_YES';
        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($yes);

        $this->assertEquals('confirmed_stale', $results[0]['status'] ?? null);
        $this->assertNotContains('confirme-usager', $incident->fresh()->ai_tags ?? []);
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('bien *enregistré*', $texts[0]['message']);
    }

    public function test_graph_send_failure_never_crashes_nor_duplicates(): void
    {
        $this->seedContact();
        $this->fakeTriage();
        FakeWhatsAppService::$failSend = true;

        $service = app(\App\Services\WashWhatsAppService::class);
        $payload = $this->textPayload(
            'Le robinet du bloc A fuit beaucoup.',
            '237600112233',
            'wamid.HARD.SENDFAIL001'
        );
        $results = $service->handlePayload($payload);

        // Incident créé, statut erreur honnête, pas de crash.
        $this->assertEquals('error', $results[0]['status'] ?? null);
        $this->assertEquals(1, Incident::count());
        $this->assertCount(0, FakeWhatsAppService::$sent);

        // Rejeu (retry file) : idempotence wamid, aucun doublon.
        FakeWhatsAppService::$failSend = false;
        $results = $service->handlePayload($payload);
        $this->assertEquals('duplicate_delivery', $results[0]['status'] ?? null);
        $this->assertEquals(1, Incident::count());
        $this->assertEquals(1, Report::count());
        $this->assertCount(0, FakeWhatsAppService::$sent);
    }

    public function test_media_download_failure_gets_guided_unreadable_reply(): void
    {
        $this->seedContact();
        FakeWhatsAppService::$downloadError = new \RuntimeException('404 Not Found (média expiré).');

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->audioPayload('wamid.HARD.DL404_001'));

        $this->assertEquals('unreadable_audio', $results[0]['status'] ?? null);
        $this->assertEquals(0, Incident::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('pas compris', $reply);
        $this->assertStringContainsString('Réenregistrez', $reply);
    }

    public function test_empty_voice_transcript_still_triages_without_crash(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/voice/transcribe' => Http::response(['transcript' => ''], 200),
        ]);

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->audioPayload('wamid.HARD.SILENCE001'));

        // Transcription vide (silence) : le triage prend le relais, guidage texte.
        $this->assertEquals('triaged_pending_confirmation', $results[0]['status'] ?? null);
        $this->assertEquals(1, Incident::count());
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('enregistré', $texts[0]['message']);
        $this->assertCount(1, $this->sentInteractive());
    }

    public function test_expired_suivi_state_restarts_fresh_without_crash(): void
    {
        $this->seedContact();
        $this->fakeTriage();
        $service = app(\App\Services\WashWhatsAppService::class);
        $service->handlePayload($this->textPayload('Le robinet du bloc A fuit.', '237600112233', 'wamid.HARD.SUIVI_EXP0'));

        // « suivi » → demande d'ID (état mémorisé).
        $results = $service->handlePayload($this->textPayload('suivi', '237600112233', 'wamid.HARD.SUIVI_EXP1'));
        $this->assertEquals('suivi', $results[0]['status'] ?? null);

        // Expiration 24h simulée : le slot orphelin redevient un message normal.
        Cache::forget('wash.whatsapp.suivi.237600112233');
        FakeWhatsAppService::$sent = [];
        $results = $service->handlePayload($this->textPayload('NON', '237600112233', 'wamid.HARD.SUIVI_EXP2'));
        $this->assertEquals('off_topic', $results[0]['status'] ?? null);
        $this->assertCount(1, FakeWhatsAppService::$sent);

        // Et le suivi redémarre proprement.
        $results = $service->handlePayload($this->textPayload('suivre mon dossier', '237600112233', 'wamid.HARD.SUIVI_EXP3'));
        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $last = end(FakeWhatsAppService::$sent);
        $this->assertStringContainsString('WASH-2026', $last['message']);
        $this->assertEquals(1, Incident::count());
    }

    public function test_english_conversation_keeps_english_on_voice_failure(): void
    {
        $this->seedContact();
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);

        // Signalement EN : mémorise la conversation en anglais.
        $service = app(\App\Services\WashWhatsAppService::class);
        $service->handlePayload($this->textPayload(
            'Hello, the tap in block A is leaking, please send help.',
            '237600112233',
            'wamid.HARD.ENLANG001'
        ));
        $this->assertEquals(1, Incident::count());

        // Échec vocal ensuite : guidage EN, pas FR.
        FakeWhatsAppService::$media['MEDIA_AUDIO_1'] = [
            'bytes' => '', 'mime' => 'audio/ogg', 'filename' => 'wa-empty.ogg',
        ];
        FakeWhatsAppService::$sent = [];
        $results = $service->handlePayload($this->audioPayload('wamid.HARD.ENLANG002'));

        $this->assertEquals('unreadable_audio', $results[0]['status'] ?? null);
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString("couldn't understand", $reply);
    }

    public function test_unsupported_type_in_english_conversation_replies_english(): void
    {
        $this->seedContact();
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);

        $service = app(\App\Services\WashWhatsAppService::class);
        $service->handlePayload($this->textPayload(
            'Hello, the tap in block A is leaking, please send help.',
            '237600112233',
            'wamid.HARD.ENUNSUP001'
        ));

        FakeWhatsAppService::$sent = [];
        $results = $service->handlePayload($this->rawPayload([
            $this->rawMessage('sticker', ['sticker' => ['id' => 'STICKER1']], '237600112233', 'wamid.HARD.ENUNSUP002'),
        ]));

        $this->assertEquals('unsupported', $results[0]['status'] ?? null);
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $this->assertStringContainsString("can't read", FakeWhatsAppService::$sent[0]['message']);
    }
}
