<?php

namespace Database\Seeders;

use Illuminate\Database\Seeder;
use Spatie\Permission\Models\Permission;
use Spatie\Permission\Models\Role;

class WashRoleSeeder extends Seeder
{
    public function run(): void
    {
        app(\Spatie\Permission\PermissionRegistrar::class)->forgetCachedPermissions();

        $permissions = [
            'create reports',
            'view own school reports',
            'view all incidents',
            'edit incidents',
            'assign incidents',
            'update incident status',
            'override ai priority',
            'use ai assistant',
            'view ai analytics',
            'manage schools',
            'manage users',
            'manage ai settings',
        ];

        foreach ($permissions as $name) {
            Permission::findOrCreate($name, 'web');
        }

        Role::findOrCreate('school_reporter', 'web')
            ->syncPermissions(['create reports', 'view own school reports', 'use ai assistant']);

        Role::findOrCreate('maintenance_agent', 'web')
            ->syncPermissions(['view all incidents', 'edit incidents', 'update incident status', 'use ai assistant']);

        Role::findOrCreate('wash_admin', 'web')
            ->syncPermissions(Permission::all());

        app(\Spatie\Permission\PermissionRegistrar::class)->forgetCachedPermissions();
    }
}
