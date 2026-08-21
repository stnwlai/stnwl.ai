$json = Get-Content ($env:INPUT_JSON ?? '.\matched_emails.json') -Raw | ConvertFrom-Json
Write-Host "Total records: $($json.Count)"

# Show case distribution
$caseDist = @{}
foreach ($e in $json) {
    foreach ($c in $e.cases) {
        $name = $c.caseName
        if ($caseDist.ContainsKey($name)) { $caseDist[$name]++ } else { $caseDist[$name] = 1 }
    }
}
$caseDist.GetEnumerator() | Sort-Object -Property Value -Descending | ForEach-Object {
    Write-Host ("{0,4} | {1}" -f $_.Value, $_.Key)
}

# Show first 3 samples
Write-Host "`nSAMPLE EMAILS:"
for ($i = 0; $i -lt 3 -and $i -lt $json.Count; $i++) {
    $e = $json[$i]
    $subLen = [Math]::Min(80, $e.subject.Length)
    Write-Host ("  [{0}] {1}" -f $e.direction, $e.subject.Substring(0, $subLen))
    Write-Host ("    From: {0} | To: {1}" -f $e.from, $e.to)
    $caseNames = ($e.cases | ForEach-Object { $_.caseName }) -join ", "
    Write-Host ("    Case: {0}" -f $caseNames)
}
