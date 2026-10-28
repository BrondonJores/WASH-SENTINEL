<?php

namespace App\Contracts;

use App\Models\School;
use App\Models\User;
use Illuminate\Http\UploadedFile;

interface IncidentTriage
{
    public function ingest(School $school, string $channel, ?string $message, ?UploadedFile $audio, ?UploadedFile $photo, ?User $reporter = null): array;
}
