<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\DB;

return new class extends Migration
{
    /**
     * Coût sourcé : le défaut 1 500 000 silencieux est banni (0.0 = non
     * communiqué). Bases déjà migrées (Pg) : SET DEFAULT. SQLite (tests) :
     * schéma recréé à zéro à chaque run, le défaut 0.0 vient déjà de la
     * migration de création — rien à faire (pas de dbal).
     */
    public function up(): void
    {
        if (DB::getDriverName() === 'pgsql') {
            DB::statement('ALTER TABLE schools ALTER COLUMN estimated_replacement_cost SET DEFAULT 0.0');
        }
    }

    public function down(): void
    {
        if (DB::getDriverName() === 'pgsql') {
            DB::statement('ALTER TABLE schools ALTER COLUMN estimated_replacement_cost SET DEFAULT 1500000.0');
        }
    }
};
