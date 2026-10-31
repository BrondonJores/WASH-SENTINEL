<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('messages', function (Blueprint $table) {
            // Horodatage client (ms epoch) : survit au replace-all qui
            // réécrit created_at en bloc à chaque synchronisation.
            $table->unsignedBigInteger('said_at')->nullable()->after('model');
            $table->json('follow_ups')->nullable()->after('said_at');
        });
    }

    public function down(): void
    {
        Schema::table('messages', function (Blueprint $table) {
            $table->dropColumn(['said_at', 'follow_ups']);
        });
    }
};
