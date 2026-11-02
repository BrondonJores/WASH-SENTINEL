<?php

// Référentiel national des coûts d'équipements WASH : prix sourcés (web,
// appels d'offres ARMP, rapports ONG) affichés au jury au lieu d'un coût
// codé en dur. Seedé par WashEquipmentCostSeeder.
use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('equipment_costs', function (Blueprint $table) {
            $table->id();
            $table->string('equipment_key', 64)->unique();
            $table->string('label', 255);
            // Catégories WASH partagées avec incidents (water_point,
            // toilets_latrines, handwashing, sewage_drainage).
            $table->string('category', 32)->index();
            $table->unsignedInteger('min_xaf');
            $table->unsignedInteger('max_xaf');
            $table->string('source_name', 255);
            $table->string('source_url', 2048)->nullable();
            $table->date('observed_at')->nullable();
            $table->text('notes')->nullable();
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('equipment_costs');
    }
};
