<?php

namespace Database\Seeders;

use App\Models\Team;
use Illuminate\Database\Seeder;

// Équipes de maintenance WASH : une à deux par district du WashDemoSeeder
// (Wouri, Mvila, Sanaga-Maritime), avec spécialités réalistes.
class WashTeamSeeder extends Seeder
{
    public function run(): void
    {
        foreach ($this->teams() as $data) {
            Team::updateOrCreate(['name' => $data['name']], $data);
        }
    }

    protected function teams(): array
    {
        return [
            [
                'name' => 'Équipe Wouri Nord',
                'district' => 'Wouri',
                'phone' => '+237 6 90 11 22',
                'specialties' => ['forage', 'pompes manuelles'],
                'is_active' => true,
            ],
            [
                'name' => 'Équipe Wouri Sud',
                'district' => 'Wouri',
                'phone' => '+237 6 90 33 44',
                'specialties' => ['latrines', 'assainissement'],
                'is_active' => true,
            ],
            [
                'name' => 'Équipe Mvila Rurale',
                'district' => 'Mvila',
                'phone' => '+237 6 91 55 66',
                'specialties' => ['forage solaire', 'pompes manuelles'],
                'is_active' => true,
            ],
            [
                'name' => 'Équipe Mvila Mobile',
                'district' => 'Mvila',
                'phone' => null,
                'specialties' => ['dépannage urgent'],
                'is_active' => true,
            ],
            [
                'name' => 'Équipe Sanaga-Maritime Est',
                'district' => 'Sanaga-Maritime',
                'phone' => '+237 6 92 77 88',
                'specialties' => ['forage mécanisé', 'réseau eau'],
                'is_active' => true,
            ],
            [
                'name' => 'Équipe Sanaga-Maritime Ouest',
                'district' => 'Sanaga-Maritime',
                'phone' => '+237 6 92 99 00',
                'specialties' => ['latrines VIP', 'drainage'],
                'is_active' => false,
            ],
        ];
    }
}
