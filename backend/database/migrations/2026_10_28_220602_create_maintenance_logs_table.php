<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('maintenance_logs', function (Blueprint $table) {
            $table->id();
            $table->foreignId('incident_id')->constrained()->cascadeOnDelete();
            $table->foreignId('school_id')->constrained()->cascadeOnDelete();
            $table->foreignId('performed_by')->nullable()->constrained('users')->nullOnDelete();
            $table->float('cost_amount')->default(0.0);
            $table->string('currency', 8)->default('XAF');
            $table->timestamp('repaired_at')->nullable();
            $table->unsignedInteger('days_without_service')->default(0);
            $table->text('notes')->nullable();
            $table->timestamps();

            $table->index(['school_id', 'repaired_at']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('maintenance_logs');
    }
};
