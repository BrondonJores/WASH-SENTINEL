<?php

namespace Tests\Unit;

use App\Models\School;
use App\Services\MeshSmsParser;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class MeshSmsParserTest extends TestCase
{
    use RefreshDatabase;

    private MeshSmsParser $parser;

    protected function setUp(): void
    {
        parent::setUp();
        $this->parser = new MeshSmsParser();
    }

    public function test_parses_compact_format(): void
    {
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CE042', 'district' => 'Est']);

        $parsed = $this->parser->parse('WASH CE042 P pompe cassee');

        $this->assertTrue($parsed['ok']);
        $this->assertEquals($school->id, $parsed['school']->id);
        $this->assertEquals('P', $parsed['type']);
        $this->assertStringContainsString('POMPE CASSEE', $parsed['normalized']);
    }

    public function test_accepts_full_words_and_accents(): void
    {
        School::create(['name' => 'EP Test', 'code' => 'NO117', 'district' => 'Nord']);

        $parsed = $this->parser->parse('wash no117 latrines pleines');

        $this->assertTrue($parsed['ok']);
        $this->assertEquals('L', $parsed['type']);
    }

    public function test_accepts_code_with_dashes_and_eau_keyword(): void
    {
        School::create(['name' => 'EP Bonanjo', 'code' => 'DOU-BON-001', 'district' => 'Wouri']);

        $parsed = $this->parser->parse('EAU DOU-BON-001 EAU TROUBLE');

        $this->assertTrue($parsed['ok']);
        $this->assertEquals('E', $parsed['type']);
    }

    public function test_rejects_unknown_school_and_type(): void
    {
        $this->assertFalse($this->parser->parse('WASH XXX P')['ok']);
        $this->assertFalse($this->parser->parse('WASH')['ok']);

        School::create(['name' => 'EP Test', 'code' => 'CE1', 'district' => 'Est']);
        $this->assertFalse($this->parser->parse('WASH CE1 Z')['ok']);
    }

    public function test_acknowledge_fits_one_segment(): void
    {
        $school = School::create(['name' => 'EP Test', 'code' => 'CE042', 'district' => 'Est']);

        $ack = $this->parser->acknowledge($school, 'P', 'WASH-2026-0042');

        $this->assertLessThanOrEqual(160, strlen($ack));
        $this->assertStringContainsString('WASH-2026-0042', $ack);
    }
}
