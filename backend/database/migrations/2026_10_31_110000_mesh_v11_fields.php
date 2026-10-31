<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('mesh_bundles', function (Blueprint $table) {
            // Alignement BPv7 (RFC 9171) — tous optionnels, v1.1 additive.
            $table->string('destination_eid', 128)->nullable()->after('school_code');
            $table->string('report_to_eid', 128)->nullable()->after('destination_eid');
            $table->unsignedInteger('lifetime_seconds')->nullable()->after('expires_at');
            $table->string('previous_node_id', 64)->nullable()->after('received_via_node_id');
            // Binary Spray-and-Wait : budget de copies restant (défaut L=8).
            $table->unsignedSmallInteger('copies_remaining')->default(8)->after('max_hops');
            // Fragmentation (futurs photos/vocal).
            $table->unsignedInteger('fragment_offset')->nullable()->after('copies_remaining');
            $table->unsignedInteger('fragment_total')->nullable()->after('fragment_offset');
            // Custody légère applicative (flag, pas BIBE complet).
            $table->boolean('custody_requested')->default(false)->after('fragment_total');
            // Priorité applicative : normal | high | alert (alert = flooding).
            $table->string('priority', 16)->default('normal')->after('custody_requested');
            // Réservé Phase 3 : signature Ed25519 du manifest (modèle Rhizome).
            $table->string('signature', 128)->nullable()->after('priority');

            $table->index('priority');
        });
    }

    public function down(): void
    {
        Schema::table('mesh_bundles', function (Blueprint $table) {
            $table->dropIndex(['priority']);
            $table->dropColumn([
                'destination_eid', 'report_to_eid', 'lifetime_seconds', 'previous_node_id',
                'copies_remaining', 'fragment_offset', 'fragment_total',
                'custody_requested', 'priority', 'signature',
            ]);
        });
    }
};
