<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('ai_analyses', function (Blueprint $table) {
            $table->id();
            $table->foreignId('incident_id')->nullable()->constrained()->cascadeOnDelete();
            $table->foreignId('report_id')->nullable()->constrained()->cascadeOnDelete();
            $table->string('analysis_type');
            $table->json('input_payload')->nullable();
            $table->json('output_payload')->nullable();
            $table->string('model_used')->nullable();
            $table->float('confidence')->nullable();
            $table->unsignedInteger('processing_ms')->nullable();
            $table->timestamps();

            $table->index(['incident_id', 'analysis_type']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('ai_analyses');
    }
};
