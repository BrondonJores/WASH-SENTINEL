<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Suivi promis au directeur (« on vous écrit ici dès que ça avance »).
     * Un abonnement = un dossier + un destinataire WhatsApp. STOP le
     * désactive ; un nouveau signalement le réactive.
     */
    public function up(): void
    {
        Schema::create('incident_subscriptions', function (Blueprint $table) {
            $table->id();
            $table->foreignId('incident_id')->constrained()->cascadeOnDelete();
            $table->string('channel', 16)->default('whatsapp');
            $table->string('recipient', 32);
            $table->string('locale', 5)->default('fr');
            $table->boolean('is_active')->default(true);
            $table->timestamp('last_notified_at')->nullable();
            $table->string('last_error', 255)->nullable();
            $table->timestamps();
            $table->unique(['incident_id', 'channel', 'recipient'], 'incident_sub_unique');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('incident_subscriptions');
    }
};
