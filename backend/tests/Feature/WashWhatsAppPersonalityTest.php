<?php

namespace Tests\Feature;

use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\School;
use App\Models\SchoolContact;
use App\Services\WashWhatsAppPersonality;
use App\Services\WashWhatsAppService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Notification;
use Tests\Support\FakeWhatsAppService;
use Tests\TestCase;

class WashWhatsAppPersonalityTest extends TestCase
{
    use RefreshDatabase;

    private WashWhatsAppPersonality $personality;

    protected function setUp(): void
    {
        parent::setUp();
        $this->personality = new WashWhatsAppPersonality();
        FakeWhatsAppService::reset();
        $this->app->bind(WhatsAppClient::class, FakeWhatsAppService::class);
        config(['whatsapp.simulator' => true]);
        Notification::fake();
    }

    public static function greetingFrProvider(): array
    {
        return [
            'bonjour simple' => ['Bonjour'],
            'bonjour ponctué' => ['Bonjour !'],
            'salut' => ['Salut'],
            'salut + ça va' => ['Salut, ça va ?'],
            'bonsoir' => ['Bonsoir'],
            'coucou' => ['Coucou'],
        ];
    }

    public static function greetingEnProvider(): array
    {
        return [
            'hello' => ['Hello'],
            'hi' => ['Hi!'],
            'good morning' => ['Good morning'],
        ];
    }

    public static function identityFrProvider(): array
    {
        return [
            'qui es-tu' => ['Qui es-tu ?'],
            'qui êtes-vous' => ['Qui êtes-vous ?'],
            'ton nom' => ["C'est quoi ton nom ?"],
            'sentinel c est quoi' => ["C'est quoi Sentinel ?"],
            'qui est sentinel' => ['Qui est Sentinel ?'],
        ];
    }

    public static function identityEnProvider(): array
    {
        return [
            'who are you' => ['Who are you?'],
            'what is sentinel' => ['What is Sentinel?'],
        ];
    }

    public static function capabilitiesFrProvider(): array
    {
        return [
            'que fais-tu' => ['Que fais-tu ?'],
            'à quoi tu sers' => ['À quoi tu sers ?'],
            'que peux-tu faire' => ['Que peux-tu faire ?'],
            'aide' => ['Aide'],
            'comment ça marche' => ['Comment ça marche ?'],
        ];
    }

    public static function capabilitiesEnProvider(): array
    {
        return [
            'what can you do' => ['What can you do?'],
            'help' => ['Help'],
        ];
    }

    public static function thanksFrProvider(): array
    {
        return [
            'merci' => ['Merci'],
            'merci beaucoup' => ['Merci beaucoup !'],
        ];
    }

    public static function thanksEnProvider(): array
    {
        return [
            'thanks' => ['Thanks!'],
            'thank you' => ['Thank you very much'],
        ];
    }

    /**
     * @dataProvider greetingFrProvider
     * @dataProvider identityFrProvider
     * @dataProvider capabilitiesFrProvider
     * @dataProvider thanksFrProvider
     */
    public function test_french_conversational_intents_return_warm_guided_reply(string $text): void
    {
        $reply = $this->personality->replyFor($text);

        $this->assertNotNull($reply, "Aucune réponse pour : {$text}");
        $this->assertStringContainsString('Sentinel', $reply);
        $this->assertTrue(
            str_contains($reply, 'une phrase') || str_contains($reply, 'note vocale')
                || str_contains($reply, 'où en est mon dossier') || str_contains($reply, 'WASH-'),
            "Pas de guidage dans la réponse pour : {$text}"
        );
        $this->assertLessThanOrEqual(397, mb_strlen($reply), 'Réponse trop longue (style SMS attendu)');
    }

    /**
     * @dataProvider greetingEnProvider
     * @dataProvider identityEnProvider
     * @dataProvider capabilitiesEnProvider
     * @dataProvider thanksEnProvider
     */
    public function test_english_conversational_intents_return_english_reply(string $text): void
    {
        $reply = $this->personality->replyFor($text);

        $this->assertNotNull($reply, "No reply for: {$text}");
        $this->assertStringContainsString('Sentinel', $reply);
        $this->assertStringContainsString('I am Sentinel', $reply, "Réponse pas en anglais pour : {$text}");
        $this->assertTrue(
            str_contains($reply, 'one sentence') || str_contains($reply, 'voice note')
                || str_contains($reply, 'where is my case') || str_contains($reply, 'WASH-'),
            "No guidance in reply for: {$text}"
        );
        $this->assertLessThanOrEqual(397, mb_strlen($reply), 'Reply too long (SMS style expected)');
    }

    public function test_real_report_returns_null(): void
    {
        $this->assertNull($this->personality->replyFor('le robinet du bloc A fuit'));
        $this->assertNull($this->personality->replyFor('Les toilettes du bloc B sont bouchées, école Les Palmiers'));
        $this->assertNull($this->personality->replyFor('Bonjour, le robinet du bloc A fuit depuis hier'));
        $this->assertNull($this->personality->replyFor('Plus de savon dans les toilettes des filles'));
    }

    public function test_empty_and_null_return_null(): void
    {
        $this->assertNull($this->personality->replyFor(null));
        $this->assertNull($this->personality->replyFor(''));
        $this->assertNull($this->personality->replyFor('   '));
    }

    public function test_identity_question_answered_through_webhook(): void
    {
        $this->seedContact();

        $results = app(WashWhatsAppService::class)->handlePayload(
            $this->textPayload('Qui es-tu ?', 'wamid.PERSO_INT_001')
        );

        $this->assertEquals('off_topic', $results[0]['status'] ?? null);
        $this->assertEquals(0, Incident::count());
        $reply = $this->sentTexts()[0]['message'] ?? '';
        $this->assertStringContainsString('Sentinel', $reply);
        $this->assertStringContainsString('note vocale', $reply);
        $this->assertStringContainsString('robinet', $reply);
        $this->assertStringContainsString('suivez', $reply);
    }

    public function test_true_off_topic_keeps_generic_guidance(): void
    {
        $this->seedContact();

        $results = app(WashWhatsAppService::class)->handlePayload(
            $this->textPayload('Quel temps fait-il demain ?', 'wamid.PERSO_INT_002')
        );

        $this->assertEquals('off_topic', $results[0]['status'] ?? null);
        $reply = $this->sentTexts()[0]['message'] ?? '';
        $this->assertStringContainsString('Ici on signale', $reply);
    }

    protected function seedContact(): void
    {
        $school = School::create([
            'name' => 'École de Bonanjo', 'code' => 'DOU-BON-001', 'district' => 'Wouri',
        ]);
        SchoolContact::create([
            'school_id' => $school->id, 'phone' => '237600112233',
            'name' => 'Clarisse Eko', 'role' => 'directrice', 'is_verified' => true,
        ]);
    }

    protected function textPayload(string $body, string $id): array
    {
        $payload = json_decode(
            file_get_contents(base_path('tests/Fixtures/whatsapp/text.json')), true
        );
        $payload['entry'][0]['changes'][0]['value']['messages'][0] = [
            'from' => '237600112233',
            'id' => $id,
            'timestamp' => '1760000000',
            'type' => 'text',
            'text' => ['body' => $body],
        ];

        return $payload;
    }

    protected function sentTexts(): array
    {
        return array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'text'
        ));
    }
}
