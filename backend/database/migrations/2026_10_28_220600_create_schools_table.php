<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('schools', function (Blueprint $table) {
            $table->id();
            $table->string('name');
            $table->string('code')->unique();
            $table->string('district');
            $table->decimal('latitude', 10, 8)->nullable();
            $table->decimal('longitude', 11, 8)->nullable();
            $table->unsignedInteger('student_count')->default(0);
            $table->unsignedInteger('female_students')->default(0);
            $table->unsignedInteger('teacher_count')->default(0);
            $table->unsignedInteger('broken_toilets')->default(0);
            $table->float('distance_from_center_km')->default(10.0);
            $table->string('equipment_type')->default('pompe_manuelle');
            $table->unsignedSmallInteger('installation_year')->nullable();
            $table->float('estimated_replacement_cost')->default(1500000.0);
            $table->string('contact_phone')->nullable();
            $table->timestamps();

            $table->index('district');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('schools');
    }
};
