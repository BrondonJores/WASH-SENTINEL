<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('ai_stt_profiles', function (Blueprint $table) {
            $table->id();
            $table->string('name');
            $table->enum('driver', ['whisper_cpp', 'omnilingual_onnx', 'cloud_whisper'])->default('whisper_cpp');
            $table->string('base_url')->nullable();
            $table->string('model')->nullable();
            $table->string('tokens_path')->nullable();
            $table->text('api_key')->nullable();
            $table->string('default_language', 16)->default('fr');
            $table->unsignedInteger('threads')->default(2);
            $table->unsignedInteger('timeout')->default(120);
            $table->boolean('is_active')->default(false);
            $table->boolean('is_default')->default(false);
            $table->timestamp('last_tested_at')->nullable();
            $table->string('last_test_status')->nullable();
            $table->unsignedInteger('last_test_latency_ms')->nullable();
            $table->timestamps();

            $table->index('is_active');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('ai_stt_profiles');
    }
};
