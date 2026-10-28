<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('incidents', function (Blueprint $table) {
            $table->id();
            $table->foreignId('school_id')->constrained()->cascadeOnDelete();
            $table->string('reference_code')->unique();
            $table->string('title');
            $table->enum('category', ['water_point', 'toilets_latrines', 'handwashing', 'sewage_drainage', 'other'])->default('other');
            $table->enum('issue_type', ['leak', 'total_breakdown', 'contamination', 'blockage', 'dry_well', 'vandalism', 'other'])->default('other');
            $table->enum('status', ['reported', 'triaged', 'assigned', 'in_progress', 'resolved', 'closed'])->default('reported');
            $table->enum('urgency', ['low', 'medium', 'high', 'critical'])->default('medium');
            $table->enum('health_hazard', ['low', 'medium', 'high', 'severe'])->default('low');
            $table->float('priority_score')->default(0.0);
            $table->unsignedInteger('affected_students')->default(0);
            $table->text('ai_summary')->nullable();
            $table->json('ai_tags')->nullable();
            $table->foreignId('assigned_to_user_id')->nullable()->constrained('users')->nullOnDelete();
            $table->timestamp('resolved_at')->nullable();
            $table->timestamps();

            $table->index(['school_id', 'status']);
            $table->index('urgency');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('incidents');
    }
};
