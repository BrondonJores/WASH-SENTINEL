<?php

namespace Tests\Feature;

use App\Models\Incident;
use App\Models\School;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class WashOverviewTest extends TestCase
{
    use RefreshDatabase;

    public function test_overview_aggregates_live_territory_numbers(): void
    {
        $a = School::create(['name' => 'E1', 'code' => 'E1', 'district' => 'Wouri']);
        $b = School::create(['name' => 'E2', 'code' => 'E2', 'district' => 'Mvila']);
        Incident::create([
            'school_id' => $a->id, 'reference_code' => 'W-1', 'title' => 'Pompe',
            'category' => 'water_point', 'status' => 'reported',
            'urgency' => 'critical', 'affected_students' => 400,
        ]);
        Incident::create([
            'school_id' => $a->id, 'reference_code' => 'W-2', 'title' => 'Fuite',
            'category' => 'water_point', 'status' => 'in_progress',
            'urgency' => 'high', 'affected_students' => 50,
        ]);
        Incident::create([
            'school_id' => $b->id, 'reference_code' => 'W-3', 'title' => 'Vanne',
            'category' => 'water_point', 'status' => 'resolved',
            'urgency' => 'low', 'affected_students' => 10,
        ]);

        $res = $this->getJson('/api/v1/wash/overview');

        $res->assertOk()->assertExactJson([
            'open_incidents' => 2,
            'affected_students' => 450,
            'critical_incidents' => 1,
            'schools_tracked' => 2,
            'schools_with_open' => 1,
        ]);
    }
}
