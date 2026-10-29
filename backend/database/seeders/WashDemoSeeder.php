<?php

namespace Database\Seeders;

use App\Models\Incident;
use App\Models\MaintenanceLog;
use App\Models\Report;
use App\Models\School;
use App\Models\SchoolContact;
use App\Models\User;
use Illuminate\Database\Seeder;
use Illuminate\Support\Facades\Hash;

class WashDemoSeeder extends Seeder
{
    public function run(): void
    {
        $admin = User::updateOrCreate(
            ['email' => 'admin@wash.cm'],
            ['name' => 'Amina Ngo Bell', 'password' => Hash::make('password')]
        );
        $tech = User::updateOrCreate(
            ['email' => 'tech@wash.cm'],
            ['name' => 'Jean Fotso', 'password' => Hash::make('password')]
        );
        $director = User::updateOrCreate(
            ['email' => 'directeur@ecole.cm'],
            ['name' => 'Clarisse Eko', 'password' => Hash::make('password')]
        );
        $admin->syncRoles(['wash_admin']);
        $tech->syncRoles(['maintenance_agent']);
        $director->syncRoles(['school_reporter']);

        $schools = [];
        foreach ($this->schools() as $data) {
            $schools[$data['code']] = School::updateOrCreate(['code' => $data['code']], $data);
        }

        SchoolContact::updateOrCreate(
            ['phone' => '237600112233'],
            ['school_id' => $schools['DOU-BON-001']->id, 'name' => 'Clarisse Eko', 'role' => 'directrice', 'is_verified' => true]
        );
        SchoolContact::updateOrCreate(
            ['phone' => '237600778899'],
            ['school_id' => $schools['RUR-NGOK-004']->id, 'name' => 'Paul Mbarga', 'role' => 'directeur', 'is_verified' => true]
        );

        $bonanjo = Incident::firstOrCreate(
            ['title' => 'Pompe principale hors service', 'school_id' => $schools['DOU-BON-001']->id],
            [
                'category' => 'water_point', 'issue_type' => 'total_breakdown',
                'status' => 'triaged', 'urgency' => 'critical', 'health_hazard' => 'severe',
                'priority_score' => 94.5, 'affected_students' => 450,
                'ai_summary' => 'Pompe principale du puits cassée depuis ce matin, 450 élèves sans eau potable.',
                'ai_tags' => ['water_point', 'total_breakdown', 'critical'],
            ]
        );

        Report::firstOrCreate(
            ['raw_content' => 'Urgent ici école de Bonanjo. La pompe principale du puits est cassée depuis ce matin, 450 élèves sans eau !'],
            [
                'incident_id' => $bonanjo->id, 'school_id' => $schools['DOU-BON-001']->id,
                'reporter_id' => $director->id, 'channel' => 'voice',
                'is_duplicate' => false,
            ]
        );
        Report::firstOrCreate(
            ['raw_content' => 'Plus aucune goutte au robinet nord de Bonanjo, les enfants rentrent avec des bidons vides.'],
            [
                'incident_id' => $bonanjo->id, 'school_id' => $schools['DOU-BON-001']->id,
                'channel' => 'text', 'is_duplicate' => true,
                'duplicate_of_incident_id' => $bonanjo->id, 'duplicate_similarity_score' => 0.88,
            ]
        );

        Incident::firstOrCreate(
            ['title' => 'Forage à sec depuis trois semaines', 'school_id' => $schools['RUR-NGOK-004']->id],
            [
                'category' => 'water_point', 'issue_type' => 'dry_well',
                'status' => 'reported', 'urgency' => 'high', 'health_hazard' => 'high',
                'priority_score' => 88.5, 'affected_students' => 195,
                'ai_summary' => 'Forage rural à sec depuis 22 jours, 195 jeunes filles menacées de décrochage.',
                'ai_tags' => ['water_point', 'dry_well', 'high'],
                'created_at' => now()->subDays(22), 'updated_at' => now()->subDays(22),
            ]
        );

        Incident::firstOrCreate(
            ['title' => 'Fuite sur le robinet du préau', 'school_id' => $schools['RUR-NKOL-005']->id],
            [
                'category' => 'water_point', 'issue_type' => 'leak',
                'status' => 'reported', 'urgency' => 'medium', 'health_hazard' => 'low',
                'priority_score' => 42.0, 'affected_students' => 0,
                'ai_summary' => 'Petite fuite sur le robinet du préau depuis 12 jours.',
                'ai_tags' => ['water_point', 'leak', 'medium'],
                'created_at' => now()->subDays(12), 'updated_at' => now()->subDays(12),
            ]
        );

        $resolved = Incident::firstOrCreate(
            ['title' => 'Latrines VIP débordées', 'school_id' => $schools['DOU-LIB-002']->id],
            [
                'category' => 'toilets_latrines', 'issue_type' => 'blockage',
                'status' => 'resolved', 'urgency' => 'high', 'health_hazard' => 'high',
                'priority_score' => 76.0, 'affected_students' => 300,
                'ai_summary' => 'Fosse des latrines VIP pleine, vidange effectuée.',
                'ai_tags' => ['toilets_latrines', 'blockage', 'high'],
                'assigned_to_user_id' => $tech->id,
                'resolved_at' => now()->subDays(5),
            ]
        );

        MaintenanceLog::firstOrCreate(
            ['incident_id' => $resolved->id, 'notes' => 'Vidange fosse + remplacement joint clapet.'],
            [
                'school_id' => $schools['DOU-LIB-002']->id, 'performed_by' => $tech->id,
                'cost_amount' => 250000, 'currency' => 'XAF',
                'repaired_at' => now()->subDays(5), 'days_without_service' => 4,
            ]
        );
        MaintenanceLog::firstOrCreate(
            ['incident_id' => $resolved->id, 'notes' => 'Curage canalisation secondaire.'],
            [
                'school_id' => $schools['DOU-LIB-002']->id, 'performed_by' => $tech->id,
                'cost_amount' => 180000, 'currency' => 'XAF',
                'repaired_at' => now()->subDays(40), 'days_without_service' => 2,
            ]
        );
    }

    protected function schools(): array
    {
        return [
            [
                'name' => 'École Publique de Bonanjo', 'code' => 'DOU-BON-001', 'district' => 'Wouri',
                'latitude' => 4.02520000, 'longitude' => 9.68450000,
                'student_count' => 650, 'female_students' => 330, 'teacher_count' => 18,
                'broken_toilets' => 0, 'distance_from_center_km' => 5.0,
                'equipment_type' => 'pompe_manuelle', 'installation_year' => 2019,
                'estimated_replacement_cost' => 1500000.0, 'contact_phone' => '+237 6 00 11 22',
            ],
            [
                'name' => 'Collège Libermann', 'code' => 'DOU-LIB-002', 'district' => 'Wouri',
                'latitude' => 4.05110000, 'longitude' => 9.73230000,
                'student_count' => 1200, 'female_students' => 610, 'teacher_count' => 45,
                'broken_toilets' => 2, 'distance_from_center_km' => 8.0,
                'equipment_type' => 'forage_mecanise', 'installation_year' => 2015,
                'estimated_replacement_cost' => 4500000.0, 'contact_phone' => '+237 6 00 33 44',
            ],
            [
                'name' => 'École Publique de Bali', 'code' => 'DOU-BAL-003', 'district' => 'Wouri',
                'latitude' => 4.03470000, 'longitude' => 9.69680000,
                'student_count' => 480, 'female_students' => 245, 'teacher_count' => 12,
                'broken_toilets' => 1, 'distance_from_center_km' => 6.5,
                'equipment_type' => 'pompe_manuelle', 'installation_year' => 2021,
                'estimated_replacement_cost' => 1500000.0, 'contact_phone' => '+237 6 00 55 66',
            ],
            [
                'name' => 'École Rurale de Ngok', 'code' => 'RUR-NGOK-004', 'district' => 'Mvila', 'default_language' => 'dua_Latn',
                'latitude' => 2.91670000, 'longitude' => 11.15000000,
                'student_count' => 210, 'female_students' => 195, 'teacher_count' => 6,
                'broken_toilets' => 3, 'distance_from_center_km' => 72.0,
                'equipment_type' => 'forage_solaire', 'installation_year' => 2017,
                'estimated_replacement_cost' => 3200000.0, 'contact_phone' => '+237 6 00 77 88',
            ],
            [
                'name' => 'École de Nkol', 'code' => 'RUR-NKOL-005', 'district' => 'Mvila', 'default_language' => 'dua_Latn',
                'latitude' => 2.95000000, 'longitude' => 11.10000000,
                'student_count' => 160, 'female_students' => 80, 'teacher_count' => 5,
                'broken_toilets' => 0, 'distance_from_center_km' => 65.0,
                'equipment_type' => 'pompe_manuelle', 'installation_year' => 2020,
                'estimated_replacement_cost' => 1500000.0, 'contact_phone' => '+237 6 00 99 00',
            ],
        ];
    }
}
