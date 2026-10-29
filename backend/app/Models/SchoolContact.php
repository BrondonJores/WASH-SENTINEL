<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class SchoolContact extends Model
{
    protected $fillable = ['school_id', 'phone', 'name', 'role', 'is_verified'];

    protected $casts = ['is_verified' => 'boolean'];

    public function school(): BelongsTo
    {
        return $this->belongsTo(School::class);
    }

    public static function normalizePhone(string $phone): string
    {
        return (string) preg_replace('/\D/', '', $phone);
    }
}
