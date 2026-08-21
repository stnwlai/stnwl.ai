param(
    [int]$DaysBack = 3,
    [int]$Limit = 250,
    [int]$SyncWorkers = 4,
    [string]$StatusPath = "",
    [string]$LogPath = ""
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$jobRoot = Join-Path $repoRoot "catalog\intake\nap_jobs"
New-Item -ItemType Directory -Force -Path $jobRoot | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $StatusPath) {
    $StatusPath = Join-Path $repoRoot "catalog\intake\nap_job_status.json"
}
if (-not $LogPath) {
    $LogPath = Join-Path $jobRoot "nap_job_$timestamp.log"
}

if (-not $env:NOTION_TOKEN) {
    throw "NOTION_TOKEN must be set in the environment before launching the nap job."
}

function Write-NapStatus {
    param(
        [string]$State,
        [hashtable]$Extra = @{}
    )

    $payload = [ordered]@{
        state        = $State
        updated_at   = (Get-Date).ToString("s")
        worker_pid   = $PID
        log_path     = $LogPath
        days_back    = $DaysBack
        limit        = $Limit
        sync_workers = $SyncWorkers
        since        = (Get-Date).AddDays(-$DaysBack).ToString("yyyy-MM-dd")
    }

    foreach ($key in $Extra.Keys) {
        $payload[$key] = $Extra[$key]
    }

    $payload | ConvertTo-Json -Depth 4 | Set-Content -Path $StatusPath -Encoding UTF8
}

$briefPath = Join-Path $jobRoot "nap_job_brief_$timestamp.txt"
$since = (Get-Date).AddDays(-$DaysBack).ToString("yyyy-MM-dd")

Set-Location $repoRoot
Start-Transcript -Path $LogPath -Append | Out-Null

try {
    Write-NapStatus -State "running" -Extra @{
        started_at = (Get-Date).ToString("s")
        brief_path = $briefPath
    }

    Write-Host "Stonewall nap job started at $(Get-Date -Format s)"
    Write-Host "Repo root: $repoRoot"
    Write-Host "Since: $since | Limit: $Limit | Sync workers: $SyncWorkers"

    & "$PSScriptRoot\ingest_onedrive.ps1" refresh-cases --output "scripts/case_index.json"
    & "$PSScriptRoot\ingest_onedrive.ps1" ingest --root all --since $since --limit $Limit --sync-notion --sync-workers $SyncWorkers
    & "$PSScriptRoot\ingest_onedrive.ps1" report --output "catalog/intake/onedrive_status_report.md"
    python scripts\tactical_brief.py today | Tee-Object -FilePath $briefPath

    Write-NapStatus -State "completed" -Extra @{
        completed_at = (Get-Date).ToString("s")
        brief_path   = $briefPath
    }
}
catch {
    Write-NapStatus -State "failed" -Extra @{
        failed_at = (Get-Date).ToString("s")
        error     = $_.Exception.Message
        brief_path = $briefPath
    }
    throw
}
finally {
    Stop-Transcript | Out-Null
}
