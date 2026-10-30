<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Project;
use Illuminate\Http\Request;

class WashProjectController extends Controller
{
    public function index(Request $request)
    {
        return response()->json(
            Project::where('user_id', $request->user()->id)
                ->withCount('conversations')
                ->orderBy('name')
                ->get()
        );
    }

    public function store(Request $request)
    {
        $validated = $request->validate(['name' => ['required', 'string', 'max:60']]);

        $project = Project::create([...$validated, 'user_id' => $request->user()->id]);

        return response()->json($project, 201);
    }

    public function update(Request $request, int $project)
    {
        $row = Project::where('user_id', $request->user()->id)->findOrFail($project);
        $validated = $request->validate(['name' => ['required', 'string', 'max:60']]);
        $row->update($validated);

        return response()->json($row->fresh());
    }

    public function destroy(Request $request, int $project)
    {
        $row = Project::where('user_id', $request->user()->id)->findOrFail($project);
        $row->delete();

        return response()->json(['message' => 'Dossier supprimé.']);
    }
}
