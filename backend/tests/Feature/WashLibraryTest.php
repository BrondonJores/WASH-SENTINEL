<?php

namespace Tests\Feature;

use App\Models\Conversation;
use App\Models\Project;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class WashLibraryTest extends TestCase
{
    use RefreshDatabase;

    private function login(string $email = 'a@wash.cm'): User
    {
        $user = User::create(['name' => 'A', 'email' => $email, 'password' => 'secret']);
        Sanctum::actingAs($user);

        return $user;
    }

    private function payload(): array
    {
        return [
            ['role' => 'user', 'content' => 'Bonjour', 'tools' => [], 'cards' => [], 'model' => ''],
            ['role' => 'assistant', 'content' => 'Salut', 'tools' => ['summarize_district'],
             'cards' => [['type' => 'district_summary', 'title' => 'Synthèse', 'data' => ['open_incidents' => 3]]],
             'model' => 'qwen'],
        ];
    }

    public function test_guest_cannot_access_library(): void
    {
        $this->getJson('/api/v1/wash/library')->assertUnauthorized();
        $this->postJson('/api/v1/wash/projects', ['name' => 'X'])->assertUnauthorized();
    }

    public function test_project_crud(): void
    {
        $this->login();

        $created = $this->postJson('/api/v1/wash/projects', ['name' => 'Urgences'])
            ->assertCreated()
            ->assertJsonPath('name', 'Urgences');
        $id = $created->json('id');

        $this->patchJson("/api/v1/wash/projects/{$id}", ['name' => 'Priorités'])
            ->assertOk()
            ->assertJsonPath('name', 'Priorités');

        $this->getJson('/api/v1/wash/projects')->assertOk()->assertJsonCount(1);

        $this->deleteJson("/api/v1/wash/projects/{$id}")->assertOk();
        $this->assertDatabaseMissing('projects', ['id' => $id]);
    }

    public function test_project_delete_detaches_conversations(): void
    {
        $this->login();
        $projectId = $this->postJson('/api/v1/wash/projects', ['name' => 'P'])->json('id');
        $convId = $this->postJson('/api/v1/wash/conversations', [
            'title' => 'T', 'project_id' => $projectId, 'messages' => $this->payload(),
        ])->json('id');

        $this->deleteJson("/api/v1/wash/projects/{$projectId}")->assertOk();

        $this->assertDatabaseHas('conversations', ['id' => $convId, 'project_id' => null]);
    }

    public function test_conversation_create_and_library(): void
    {
        $this->login();

        $this->postJson('/api/v1/wash/conversations', [
            'title' => 'Point du matin', 'messages' => $this->payload(),
        ])->assertCreated()->assertJsonPath('messages.1.tools.0', 'summarize_district');

        $this->getJson('/api/v1/wash/library')
            ->assertOk()
            ->assertJsonPath('conversations.0.title', 'Point du matin')
            ->assertJsonPath('conversations.0.messages.0.role', 'user')
            ->assertJsonPath('conversations.0.messages.1.cards.0.data.open_incidents', 3);
    }

    public function test_replace_messages(): void
    {
        $this->login();
        $id = $this->postJson('/api/v1/wash/conversations', [
            'title' => 'T', 'messages' => $this->payload(),
        ])->json('id');

        $this->putJson("/api/v1/wash/conversations/{$id}/messages", [
            'messages' => [['role' => 'user', 'content' => 'Nouveau']],
        ])->assertOk();

        $this->assertDatabaseCount('messages', 1);
        $this->assertDatabaseHas('messages', ['conversation_id' => $id, 'content' => 'Nouveau']);
    }

    public function test_move_conversation_between_projects(): void
    {
        $this->login();
        $a = $this->postJson('/api/v1/wash/projects', ['name' => 'A'])->json('id');
        $b = $this->postJson('/api/v1/wash/projects', ['name' => 'B'])->json('id');
        $id = $this->postJson('/api/v1/wash/conversations', [
            'title' => 'T', 'project_id' => $a, 'messages' => $this->payload(),
        ])->json('id');

        $this->patchJson("/api/v1/wash/conversations/{$id}", ['project_id' => $b])
            ->assertOk()->assertJsonPath('project_id', $b);
        $this->patchJson("/api/v1/wash/conversations/{$id}", ['project_id' => null])
            ->assertOk()->assertJsonPath('project_id', null);
    }

    public function test_users_are_isolated(): void
    {
        $this->login('a@wash.cm');
        $projectId = $this->postJson('/api/v1/wash/projects', ['name' => 'P'])->json('id');
        $convId = $this->postJson('/api/v1/wash/conversations', [
            'title' => 'T', 'project_id' => $projectId, 'messages' => $this->payload(),
        ])->json('id');

        $this->login('b@wash.cm');
        $this->getJson('/api/v1/wash/library')
            ->assertOk()
            ->assertJsonCount(0, 'projects')
            ->assertJsonCount(0, 'conversations');
        $this->patchJson("/api/v1/wash/conversations/{$convId}", ['title' => 'Hack'])
            ->assertNotFound();
        $this->putJson("/api/v1/wash/conversations/{$convId}/messages", ['messages' => []])
            ->assertNotFound();
        $this->deleteJson("/api/v1/wash/conversations/{$convId}")->assertNotFound();
        $this->postJson('/api/v1/wash/conversations', [
            'title' => 'T', 'project_id' => $projectId, 'messages' => $this->payload(),
        ])->assertUnprocessable();

        $this->assertDatabaseHas('conversations', ['id' => $convId, 'title' => 'T']);
    }

    public function test_validation_rejects_bad_payload(): void
    {
        $this->login();
        $this->postJson('/api/v1/wash/conversations', [
            'title' => 'T',
            'messages' => [['role' => 'robot', 'content' => 'x']],
        ])->assertUnprocessable();
        $this->postJson('/api/v1/wash/projects', ['name' => ''])->assertUnprocessable();
    }
}
