<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('mesh_bundles', function (Blueprint $table) {
            $table->id();
            $table->uuid('bundle_id')->unique();
            $table->string('origin_node_id', 64)->index();
            $table->foreignId('school_id')->nullable()->constrained()->nullOnDelete();
            $table->string('school_code', 32)->nullable();
            $table->string('channel', 16)->default('text');
            $table->text('message')->nullable();
            $table->json('payload');
            $table->json('hops')->nullable();
            $table->unsignedSmallInteger('hop_count')->default(0);
            $table->unsignedSmallInteger('max_hops')->default(10);
            $table->string('received_via_node_id', 64)->nullable();
            $table->string('status', 16)->default('pending')->index();
            $table->foreignId('report_id')->nullable()->constrained()->nullOnDelete();
            $table->timestamp('expires_at')->nullable();
            $table->timestamp('delivered_at')->nullable();
            $table->timestamps();

            $table->index(['status', 'created_at']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('mesh_bundles');
    }
};
