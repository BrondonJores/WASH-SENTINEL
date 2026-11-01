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
    public const LIBRARY_LIMIT = 60;

    public const TITLE_MAX = 120;

    public const MESSAGES_MAX = 200;

    public const MESSAGE_ROLES = ['user', 'assistant'];

    public const MESSAGE_CONTENT_MAX = 20000;

    public const MESSAGE_TOOLS_MAX = 20;

    public const TOOL_MAX = 64;

    public const CARDS_MAX = 20;

    public const CARD_TYPE_MAX = 64;

    public const CARD_TITLE_MAX = 180;

    public const MODEL_MAX = 120;

    public const SAID_AT_MIN = 0;

    public const SAID_AT_MAX = 9999999999999;

    public const FOLLOW_UPS_MAX = 10;

    public const FOLLOW_UP_MAX = 200;

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
                ->limit(self::LIBRARY_LIMIT)
                ->get(),
        ]);
    }

    public function store(Request $request)
    {
        $validated = $request->validate(array_merge(
            [
                'title' => ['required', 'string', 'max:' . self::TITLE_MAX],
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
            'title' => ['sometimes', 'string', 'max:' . self::TITLE_MAX],
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
            'messages' => ['required', 'array', 'max:' . self::MESSAGES_MAX],
            'messages.*.role' => ['required', 'in:' . implode(',', self::MESSAGE_ROLES)],
            'messages.*.content' => ['required', 'string', 'max:' . self::MESSAGE_CONTENT_MAX],
            'messages.*.tools' => ['nullable', 'array', 'max:' . self::MESSAGE_TOOLS_MAX],
            'messages.*.tools.*' => ['string', 'max:' . self::TOOL_MAX],
            'messages.*.cards' => ['nullable', 'array', 'max:' . self::CARDS_MAX],
            'messages.*.cards.*.type' => ['nullable', 'string', 'max:' . self::CARD_TYPE_MAX],
            'messages.*.cards.*.title' => ['nullable', 'string', 'max:' . self::CARD_TITLE_MAX],
            'messages.*.cards.*.data' => ['nullable', 'array'],
            'messages.*.model' => ['nullable', 'string', 'max:' . self::MODEL_MAX],
            'messages.*.said_at' => ['nullable', 'integer', 'min:' . self::SAID_AT_MIN, 'max:' . self::SAID_AT_MAX],
            'messages.*.follow_ups' => ['nullable', 'array', 'max:' . self::FOLLOW_UPS_MAX],
            'messages.*.follow_ups.*' => ['string', 'max:' . self::FOLLOW_UP_MAX],
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
                'said_at' => $message['said_at'] ?? null,
                'follow_ups' => $message['follow_ups'] ?? [],
            ]);
        }
    }
}
