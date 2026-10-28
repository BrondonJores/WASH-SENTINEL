<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('reports', function (Blueprint $table) {
            $table->id();
            $table->foreignId('incident_id')->nullable()->constrained()->nullOnDelete();
            $table->foreignId('school_id')->constrained()->cascadeOnDelete();
            $table->foreignId('reporter_id')->nullable()->constrained('users')->nullOnDelete();
            $table->enum('channel', ['voice', 'text', 'photo', 'webrtc_call'])->default('text');
            $table->text('raw_content');
            $table->string('audio_path')->nullable();
            $table->string('photo_path')->nullable();
            $table->boolean('is_duplicate')->default(false);
            $table->foreignId('duplicate_of_incident_id')->nullable()->constrained('incidents')->nullOnDelete();
            $table->float('duplicate_similarity_score')->nullable();
            $table->json('raw_ai_extraction')->nullable();
            $table->timestamps();

            $table->index(['school_id', 'created_at']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('reports');
    }
};
