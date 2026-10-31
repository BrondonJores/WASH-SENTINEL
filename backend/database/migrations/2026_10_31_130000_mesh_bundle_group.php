<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('mesh_bundles', function (Blueprint $table) {
            // V2b médias différés : relie les fragments à leur manifeste
            // (bundle_group = bundle_id du manifeste).
            $table->string('bundle_group', 64)->nullable()->after('bundle_id');
            $table->index('bundle_group');
        });
    }

    public function down(): void
    {
        Schema::table('mesh_bundles', function (Blueprint $table) {
            $table->dropIndex(['bundle_group']);
            $table->dropColumn('bundle_group');
        });
    }
};
