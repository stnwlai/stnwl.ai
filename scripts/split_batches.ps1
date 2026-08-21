# Split matched_emails.json into batch files of 50 emails each
# Set INPUT_JSON and BATCH_DIR env vars, or update the paths below to match your environment.
$json = Get-Content ($env:INPUT_JSON ?? '.\matched_emails.json') -Raw | ConvertFrom-Json
$batchSize = 50
$batchDir = $env:BATCH_DIR ?? '.\batches'

if (-not (Test-Path $batchDir)) { New-Item -ItemType Directory -Path $batchDir | Out-Null }

$totalBatches = [Math]::Ceiling($json.Count / $batchSize)

for ($i = 0; $i -lt $totalBatches; $i++) {
    $start = $i * $batchSize
    $end = [Math]::Min($start + $batchSize - 1, $json.Count - 1)
    $batch = $json[$start..$end]
    $batchJson = $batch | ConvertTo-Json -Depth 5 -Compress
    $batchFile = Join-Path $batchDir ("batch_{0:D3}.json" -f $i)
    [System.IO.File]::WriteAllText($batchFile, $batchJson, [System.Text.Encoding]::UTF8)
}

Write-Host "Created $totalBatches batch files in $batchDir"
