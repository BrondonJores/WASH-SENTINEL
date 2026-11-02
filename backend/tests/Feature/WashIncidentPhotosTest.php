<?php

namespace Tests\Feature;

use App\Http\Controllers\Api\WashAgentController;
use App\Models\Incident;
use App\Models\Report;
use App\Models\School;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Storage;
use Tests\TestCase;

class WashIncidentPhotosTest extends TestCase
{
    use RefreshDatabase;

    /** @return array{School, Incident, Report[]} */
    private function seedIncidentWithPhotos(int $count, string $district = 'Bonanjo'): array
    {
        Storage::fake('public');
        $school = School::create(['name' => 'EP Bonanjo', 'code' => 'EP-BON', 'district' => $district]);
        $incident = Incident::create([
            'school_id' => $school->id,
            'title' => 'Fuite au forage de Bonanjo',
            'category' => 'water_point',
            'status' => 'reported',
            'urgency' => 'high',
            'priority_score' => 80.0,
            'affected_students' => 300,
        ]);
        $reports = [];
        for ($i = 0; $i < $count; $i++) {
            $path = "reports/photos/bonanjo-{$i}.png";
            Storage::disk('public')->put($path, 'fake-image-bytes');
            $reports[] = Report::create([
                'incident_id' => $incident->id,
                'school_id' => $school->id,
                'channel' => 'photo',
                'raw_content' => "Photo {$i} du forage",
                'photo_path' => $path,
                'is_duplicate' => false,
            ]);
        }

        return [$school, $incident, $reports];
    }

    private function fakeEngine(array $response): void
    {
        Http::fake([
            '*/v1/agent/chat' => Http::response($response, 200),
        ]);
    }

    private function engineOk(array $cards = []): array
    {
        return [
            'answer' => 'Voici la situation.',
            'tools_executed' => [],
            'cards' => $cards,
            'model_used' => 'test-llm',
        ];
    }

    /** @return array<int, array> */
    private function sentIncidents(): array
    {
        $payload = null;
        Http::assertSent(function ($request) use (&$payload) {
            if (str_ends_with($request->url(), '/v1/agent/chat')) {
                $payload = $request->data()['context']['incidents'] ?? null;

                return true;
            }

            return false;
        });
        $this->assertIsArray($payload);

        return $payload;
    }

    public function test_converse_context_includes_absolute_photo_urls(): void
    {
        [, $incident] = $this->seedIncidentWithPhotos(2);
        $this->fakeEngine($this->engineOk());

        $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Montre les incidents de Bonanjo'])
            ->assertOk();

        $incidents = $this->sentIncidents();
        $this->assertCount(1, $incidents);
        $photos = $incidents[0]['photos'] ?? null;
        $this->assertIsArray($photos);
        $this->assertCount(2, $photos);
        foreach ($photos as $photo) {
            $this->assertStringStartsWith('http', $photo['url']);
            $this->assertStringContainsString('/storage/reports/photos/', $photo['url']);
        }
        $this->assertSame($incident->id, $incidents[0]['id']);
    }

    public function test_incident_photos_capped_at_four(): void
    {
        $this->assertSame(4, WashAgentController::INCIDENT_PHOTOS_LIMIT);
        $this->seedIncidentWithPhotos(6);
        $this->fakeEngine($this->engineOk());

        $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Montre les incidents de Bonanjo'])
            ->assertOk();

        $incidents = $this->sentIncidents();
        $this->assertCount(WashAgentController::INCIDENT_PHOTOS_LIMIT, $incidents[0]['photos']);
    }

    public function test_incident_without_photo_gets_empty_list(): void
    {
        Storage::fake('public');
        $school = School::create(['name' => 'EP Bonanjo', 'code' => 'EP-BON', 'district' => 'Bonanjo']);
        Incident::create([
            'school_id' => $school->id,
            'title' => 'Panne sans photo',
            'category' => 'water_point',
            'status' => 'reported',
        ]);
        $this->fakeEngine($this->engineOk());

        $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Montre les incidents de Bonanjo'])
            ->assertOk();

        $incidents = $this->sentIncidents();
        $this->assertSame([], $incidents[0]['photos']);
    }

    public function test_missing_file_excluded_silently(): void
    {
        [, $incident] = $this->seedIncidentWithPhotos(1);
        Report::create([
            'incident_id' => $incident->id,
            'school_id' => $incident->school_id,
            'channel' => 'photo',
            'raw_content' => 'Photo perdue',
            'photo_path' => 'reports/photos/fantome.png',
            'is_duplicate' => false,
        ]);
        $this->fakeEngine($this->engineOk());

        $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Montre les incidents de Bonanjo'])
            ->assertOk();

        $incidents = $this->sentIncidents();
        $photos = $incidents[0]['photos'];
        $this->assertCount(1, $photos);
        $this->assertStringContainsString('bonanjo-0.png', $photos[0]['url']);
    }

    public function test_photo_carries_caption_and_reported_at(): void
    {
        [, $incident, $reports] = $this->seedIncidentWithPhotos(1);
        $this->fakeEngine($this->engineOk());

        $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Montre les incidents de Bonanjo'])
            ->assertOk();

        $incidents = $this->sentIncidents();
        $photo = $incidents[0]['photos'][0];
        $this->assertSame('Fuite au forage de Bonanjo', $photo['caption']);
        $this->assertSame($reports[0]->created_at->toIso8601String(), $photo['reported_at']);
        $this->assertSame($incident->title, $photo['caption']);
    }

    public function test_converse_relays_photos_to_incident_detail_card(): void
    {
        [, $incident] = $this->seedIncidentWithPhotos(2);
        $this->fakeEngine($this->engineOk([[
            'type' => 'incident_detail',
            'title' => "Incident {$incident->reference_code}",
            'data' => ['id' => $incident->id, 'reference_code' => $incident->reference_code],
        ]]));

        $response = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Montre les incidents de Bonanjo'])
            ->assertOk();

        $photos = $response->json('cards.0.data.photos');
        $this->assertIsArray($photos);
        $this->assertCount(2, $photos);
        $this->assertStringStartsWith('http', $photos[0]['url']);
        $this->assertSame('Fuite au forage de Bonanjo', $photos[0]['caption']);
        $this->assertNotEmpty($photos[0]['reported_at']);
    }

    public function test_converse_relays_photos_to_picker_candidates(): void
    {
        [, $incident] = $this->seedIncidentWithPhotos(1);
        $this->fakeEngine($this->engineOk([[
            'type' => 'incident_picker',
            'title' => 'Quel incident ?',
            'data' => ['candidates' => [
                ['id' => $incident->id, 'title' => $incident->title],
                ['id' => 999999, 'title' => 'Incident inconnu'],
            ]],
        ]]));

        $response = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Journalise une intervention'])
            ->assertOk();

        $candidates = $response->json('cards.0.data.candidates');
        $this->assertCount(1, $candidates[0]['photos']);
        $this->assertStringStartsWith('http', $candidates[0]['photos'][0]['url']);
        $this->assertSame([], $candidates[1]['photos']);
    }
}
