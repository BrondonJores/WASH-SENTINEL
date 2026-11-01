<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\User;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Hash;

class AuthController extends Controller
{
    public const EMAIL_MAX = 255;

    public const PASSWORD_MAX = 255;

    public function token(Request $request)
    {
        $validated = $request->validate([
            'email' => ['required', 'email', 'max:' . self::EMAIL_MAX],
            'password' => ['required', 'string', 'max:' . self::PASSWORD_MAX],
        ]);

        $user = User::where('email', $validated['email'])->first();
        if (!$user || !Hash::check($validated['password'], $user->password)) {
            return response()->json(['message' => 'Identifiants invalides.'], 401);
        }

        return response()->json([
            'token' => $user->createToken('admin')->plainTextToken,
            'user' => [
                'id' => $user->id,
                'name' => $user->name,
                'email' => $user->email,
                'roles' => $user->getRoleNames(),
            ],
        ]);
    }

    public function destroy(Request $request)
    {
        $request->user()->currentAccessToken()->delete();

        return response()->json(['message' => 'Déconnecté.']);
    }
}
