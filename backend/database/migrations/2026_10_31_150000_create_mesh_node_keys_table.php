<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('mesh_node_keys', function (Blueprint $table) {
            $table->id();
            // TOFU : première clé Ed25519 vue pour ce nœud = référence.
            $table->string('origin_node_id')->unique();
            $table->string('node_pubkey', 64);
            $table->timestamp('first_seen_at');
            $table->timestamp('last_changed_at')->nullable();
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('mesh_node_keys');
    }
};
