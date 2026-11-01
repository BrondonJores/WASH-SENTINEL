<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('mesh_bundles', function (Blueprint $table) {
            // V2 signatures : clé publique Ed25519 auto-annoncée (TOFU),
            // conservée pour audit même quand le relai a reformaté le bundle.
            $table->string('node_pubkey', 64)->nullable()->after('signature');
            $table->index(['origin_node_id', 'node_pubkey']);
        });
    }

    public function down(): void
    {
        Schema::table('mesh_bundles', function (Blueprint $table) {
            $table->dropIndex(['origin_node_id', 'node_pubkey']);
            $table->dropColumn('node_pubkey');
        });
    }
};
