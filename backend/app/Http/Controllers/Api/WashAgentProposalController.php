<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\AgentProposal;
use App\Services\AgentProposalService;
use Illuminate\Http\Request;

class WashAgentProposalController extends Controller
{
    public function confirm(Request $request, AgentProposal $proposal, AgentProposalService $service)
    {
        $result = $service->confirm($request->user(), $proposal);

        return response()->json(['message' => 'Proposition exécutée.', 'result' => $result]);
    }

    public function cancel(Request $request, AgentProposal $proposal, AgentProposalService $service)
    {
        $result = $service->cancel($request->user(), $proposal);

        return response()->json(['message' => 'Proposition annulée.', 'result' => $result]);
    }
}
