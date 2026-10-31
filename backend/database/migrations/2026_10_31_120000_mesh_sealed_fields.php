<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('mesh_bundles', function (Blueprint $table) {
            // V2 E2E : enveloppe scellée (libsodium sealed box, base64) + algo.
            // Seul le serveur (destinataire) déchiffre ; les relais voient
            // les métadonnées de routage mais jamais le contenu.
            $table->text('sealed_payload')->nullable()->after('message');
            $table->string('sealed_alg', 32)->nullable()->after('sealed_payload');
        });
    }

    public function down(): void
    {
        Schema::table('mesh_bundles', function (Blueprint $table) {
            $table->dropColumn(['sealed_payload', 'sealed_alg']);
        });
    }
};
