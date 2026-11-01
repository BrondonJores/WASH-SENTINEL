<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use Illuminate\Http\Request;

class WashNotificationController extends Controller
{
    public function index(Request $request)
    {
        return response()->json(
            $request->user()->notifications()
                ->when($request->query('unread') === '1', fn ($q) => $q->whereNull('read_at'))
                ->paginate(min(
                    config('wash.pagination.max'),
                    max(config('wash.pagination.min'), (int) $request->query('per_page', config('wash.pagination.default')))
                ))
        );
    }

    public function read(Request $request, string $notification)
    {
        $request->user()->notifications()->findOrFail($notification)->markAsRead();

        return response()->json(['message' => 'Notification lue.']);
    }

    public function readAll(Request $request)
    {
        $request->user()->unreadNotifications->markAsRead();

        return response()->json(['message' => 'Toutes les notifications sont lues.']);
    }
}
