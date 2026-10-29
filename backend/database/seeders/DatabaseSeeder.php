<?php

namespace Database\Seeders;

use App\Models\User;
use Illuminate\Database\Seeder;
use Illuminate\Support\Facades\Hash;

class DatabaseSeeder extends Seeder
{
    /**
     * Seed the application's database.
     */
    public function run(): void
    {
        // User::factory(10)->create();

        $this->call([AiModelProfileSeeder::class, AiSttProfileSeeder::class, WashRoleSeeder::class, WashDemoSeeder::class]);

        User::firstOrCreate(
            ['email' => 'test@example.com'],
            ['name' => 'Test User', 'password' => Hash::make('password')]
        );
    }
}
