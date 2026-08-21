param(
    [int]$DaysBack = 3,
    [int]$Limit = 250,
    [int]$SyncWorkers = 4
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$jobRoot = Join-Path $repoRoot "catalog\intake\nap_jobs"
New-Item -ItemType Directory -Force -Path $jobRoot | Out-Null

if (-not $env:NOTION_TOKEN) {
    throw "NOTION_TOKEN must be set in the environment before starting the nap job."
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$statusPath = Join-Path $repoRoot "catalog\intake\nap_job_status.json"
$logPath = Join-Path $jobRoot "nap_job_$timestamp.log"
$workerScript = Join-Path $PSScriptRoot "run_nap_job.ps1"
$powershell = (Get-Command powershell.exe).Source

$argList = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', $workerScript,
    '-DaysBack', "$DaysBack",
    '-Limit', "$Limit",
    '-SyncWorkers', "$SyncWorkers",
    '-StatusPath', $StatusPath,
    '-LogPath', $LogPath
)

$proc = Start-Process -FilePath $powershell -ArgumentList $argList -WindowStyle Hidden -PassThru

$launchStatus = [ordered]@{
    state         = "launching"
    launched_at   = (Get-Date).ToString("s")
    launcher_pid  = $PID
    worker_pid    = $proc.Id
    log_path      = $LogPath
    status_path   = $StatusPath
    days_back     = $DaysBack
    limit         = $Limit
    sync_workers  = $SyncWorkers
} | ConvertTo-Json -Depth 4

$launchStatus | Set-Content -Path $statusPath -Encoding UTF8

Write-Host "Nap job launched."
Write-Host "Worker PID: $($proc.Id)"
Write-Host "Log: $LogPath"
Write-Host "Status: $StatusPath"
