<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/*
 * Ajoute le driver 'meta_transcribe' (Meta Muse Transcribe, cloud
 * OpenAI-compatible) aux profils STT. L'enum Laravel est un varchar +
 * CHECK sur pgsql ET sqlite : on réécrit le CHECK (pgsql) ou on
 * reconstruit la table (sqlite, pas de DROP CONSTRAINT).
 */
return new class extends Migration
{
    private const DRIVERS = ['whisper_cpp', 'omnilingual_onnx', 'cloud_whisper', 'meta_transcribe'];

    private const DRIVERS_BEFORE = ['whisper_cpp', 'omnilingual_onnx', 'cloud_whisper'];

    public function up(): void
    {
        if (DB::getDriverName() === 'pgsql') {
            DB::statement('ALTER TABLE ai_stt_profiles DROP CONSTRAINT IF EXISTS ai_stt_profiles_driver_check');
            DB::statement(sprintf(
                "ALTER TABLE ai_stt_profiles ADD CONSTRAINT ai_stt_profiles_driver_check CHECK (driver IN (%s))",
                $this->quoted(self::DRIVERS)
            ));

            return;
        }

        $this->rebuildWithDrivers(self::DRIVERS);
    }

    public function down(): void
    {
        // Ne passe que si aucun profil 'meta_transcribe' ne subsiste.
        if (DB::getDriverName() === 'pgsql') {
            DB::statement('ALTER TABLE ai_stt_profiles DROP CONSTRAINT IF EXISTS ai_stt_profiles_driver_check');
            DB::statement(sprintf(
                "ALTER TABLE ai_stt_profiles ADD CONSTRAINT ai_stt_profiles_driver_check CHECK (driver IN (%s))",
                $this->quoted(self::DRIVERS_BEFORE)
            ));

            return;
        }

        $this->rebuildWithDrivers(self::DRIVERS_BEFORE);
    }

    private function quoted(array $drivers): string
    {
        return implode(',', array_map(fn ($d) => "'{$d}'", $drivers));
    }

    private function rebuildWithDrivers(array $drivers): void
    {
        Schema::rename('ai_stt_profiles', 'ai_stt_profiles_old');
        Schema::table('ai_stt_profiles_old', function (Blueprint $table) {
            $table->dropIndex('ai_stt_profiles_is_active_index');
        });
        Schema::create('ai_stt_profiles', function (Blueprint $table) use ($drivers) {
            $table->id();
            $table->string('name');
            $table->enum('driver', $drivers)->default('whisper_cpp');
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
        DB::statement('INSERT INTO ai_stt_profiles SELECT * FROM ai_stt_profiles_old');
        Schema::drop('ai_stt_profiles_old');
    }
};
