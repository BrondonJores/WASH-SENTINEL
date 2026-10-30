<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Conversation;
use App\Models\Project;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\Rule;

class WashConversationController extends Controller
{
    public function library(Request $request)
    {
        $uid = $request->user()->id;

        return response()->json([
            'projects' => Project::where('user_id', $uid)
                ->withCount('conversations')
                ->orderBy('name')
                ->get(),
            'conversations' => Conversation::where('user_id', $uid)
                ->with('messages')
                ->latest('updated_at')
                ->limit(60)
                ->get(),
        ]);
    }

    public function store(Request $request)
    {
        $validated = $request->validate(array_merge(
            [
                'title' => ['required', 'string', 'max:120'],
                'project_id' => ['nullable', 'integer', Rule::exists('projects', 'id')->where('user_id', $request->user()->id)],
            ],
            $this->messageRules()
        ));

        $conversation = DB::transaction(function () use ($validated, $request) {
            $conversation = Conversation::create([
                'user_id' => $request->user()->id,
                'project_id' => $validated['project_id'] ?? null,
                'title' => $validated['title'],
            ]);
            $this->storeMessages($conversation, $validated['messages']);

            return $conversation;
        });

        return response()->json($conversation->load('messages'), 201);
    }

    public function update(Request $request, int $conversation)
    {
        $row = Conversation::where('user_id', $request->user()->id)->findOrFail($conversation);
        $validated = $request->validate([
            'title' => ['sometimes', 'string', 'max:120'],
            'project_id' => ['sometimes', 'nullable', 'integer', Rule::exists('projects', 'id')->where('user_id', $request->user()->id)],
        ]);
        $row->update($validated);

        return response()->json($row->fresh());
    }

    public function replaceMessages(Request $request, int $conversation)
    {
        $row = Conversation::where('user_id', $request->user()->id)->findOrFail($conversation);
        $validated = $request->validate($this->messageRules());

        DB::transaction(function () use ($row, $validated) {
            $row->messages()->delete();
            $this->storeMessages($row, $validated['messages']);
            $row->touch();
        });

        return response()->json($row->fresh()->load('messages'));
    }

    public function destroy(Request $request, int $conversation)
    {
        $row = Conversation::where('user_id', $request->user()->id)->findOrFail($conversation);
        $row->delete();

        return response()->json(['message' => 'Discussion supprimée.']);
    }

    private function messageRules(): array
    {
        return [
            'messages' => ['required', 'array', 'max:200'],
            'messages.*.role' => ['required', 'in:user,assistant'],
            'messages.*.content' => ['required', 'string', 'max:20000'],
            'messages.*.tools' => ['nullable', 'array', 'max:20'],
            'messages.*.tools.*' => ['string', 'max:64'],
            'messages.*.cards' => ['nullable', 'array', 'max:20'],
            'messages.*.cards.*.type' => ['nullable', 'string', 'max:64'],
            'messages.*.cards.*.title' => ['nullable', 'string', 'max:180'],
            'messages.*.cards.*.data' => ['nullable', 'array'],
            'messages.*.model' => ['nullable', 'string', 'max:120'],
        ];
    }

    private function storeMessages(Conversation $conversation, array $messages): void
    {
        foreach ($messages as $message) {
            $conversation->messages()->create([
                'role' => $message['role'],
                'content' => $message['content'],
                'tools' => $message['tools'] ?? [],
                'cards' => $message['cards'] ?? [],
                'model' => $message['model'] ?? null,
            ]);
        }
    }
}
