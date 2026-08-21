param(
    [string]$StatusPath = ""
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $StatusPath) {
    $StatusPath = Join-Path $repoRoot "catalog\intake\nap_job_status.json"
}

if (-not (Test-Path $StatusPath)) {
    Write-Host "No nap job status file found at $StatusPath"
    exit 0
}

$status = Get-Content -Path $StatusPath -Raw | ConvertFrom-Json
$running = $false
if ($status.worker_pid) {
    $running = [bool](Get-Process -Id $status.worker_pid -ErrorAction SilentlyContinue)
}

Write-Host "State: $($status.state)"
Write-Host "Running: $running"
Write-Host "Worker PID: $($status.worker_pid)"
$when = if ($status.updated_at) { $status.updated_at } elseif ($status.launched_at) { $status.launched_at } elseif ($status.started_at) { $status.started_at } else { "" }
Write-Host "Updated: $when"
Write-Host "Log: $($status.log_path)"
if ($status.error) {
    Write-Host "Error: $($status.error)"
}

if ($status.log_path -and (Test-Path $status.log_path)) {
    Write-Host ""
    Write-Host "Last 20 log lines:"
    Get-Content -Path $status.log_path -Tail 20
}
