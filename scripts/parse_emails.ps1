# Parse email CSVs and match to Legal Matters cases
# Output: matched_emails.json
#
# CONFIGURATION:
# 1. Populate $cases with your Notion Legal Matters page IDs, case names, and matching keywords
# 2. Populate $files with paths to your Outlook CSV exports
# 3. Set $outputPath to your desired output location

$ErrorActionPreference = "Continue"

# Case matching data: [pageId, caseName, [keywords]]
# Keywords are lowercased for matching against subject lines.
# Populate this list with your firm's actual case names, Notion page IDs, and matching keywords.
$cases = @(
    # @("YOUR_NOTION_PAGE_ID", "Plaintiff v. Defendant", @("plaintiff", "keyword1", "CLAIM_NUMBER")),
)

# Also match on claim numbers generically
$claimPattern = "CLAIM#|CL#[0-9]+|[A-Z]{1,2}[0-9]{6,}"

function Match-Case {
    param([string]$subject)
    $subjectLower = $subject.ToLower()
    $matched = @()

    foreach ($case in $cases) {
        $pageId = $case[0]
        $caseName = $case[1]
        $keywords = $case[2]

        foreach ($kw in $keywords) {
            if ($subjectLower -match $kw) {
                $matched += @{ pageId = $pageId; caseName = $caseName }
                break
            }
        }
    }
    return $matched
}

# Files to process — set paths to your Outlook CSV exports.
# Export from Outlook: File → Open & Export → Import/Export → Export to a file → Comma Separated Values
# The CSV should include Subject, Body, From: (Name), From: (Address), To: (Name), To: (Address), CC: (Name)
$files = @(
    # @{ path = "C:\Path\To\Your\inbox_export.csv"; direction = "Inbox"; source = "inbox-label" },
    # @{ path = "C:\Path\To\Your\sent_export.csv";  direction = "Sent";  source = "sent-label" },
)

$allMatched = @()
$seen = @{}
$totalProcessed = 0
$totalMatched = 0

foreach ($fileInfo in $files) {
    $filePath = $fileInfo.path
    $direction = $fileInfo.direction
    $source = $fileInfo.source

    if (-not (Test-Path $filePath)) {
        Write-Host "SKIP (not found): $filePath"
        continue
    }

    Write-Host "Processing: $source..."

    try {
        $rows = Import-Csv -Path $filePath -Encoding UTF8
    } catch {
        Write-Host "ERROR reading $filePath : $_"
        continue
    }

    $fileCount = 0
    $fileMatched = 0

    foreach ($row in $rows) {
        $fileCount++
        $subject = $row.Subject
        if (-not $subject) { continue }

        # Dedup key
        $fromAddr = $row.'From: (Address)'
        $toAddr = $row.'To: (Address)'
        $dedupKey = "$subject|$fromAddr|$toAddr"
        if ($seen.ContainsKey($dedupKey)) { continue }
        $seen[$dedupKey] = $true

        # Match against cases
        $matches = Match-Case -subject $subject
        if ($matches.Count -eq 0) { continue }

        $fileMatched++

        # Truncate body to 2000 chars for Notion (full content gets very large)
        $body = $row.Body
        if ($body -and $body.Length -gt 2000) {
            $body = $body.Substring(0, 2000) + "`n`n[... truncated ...]"
        }

        $email = @{
            subject = $subject
            direction = $direction
            from = $row.'From: (Name)'
            fromEmail = $fromAddr
            to = $row.'To: (Name)'
            toAddr = $toAddr
            cc = $row.'CC: (Name)'
            body = $body
            source = $source
            cases = $matches
        }

        $allMatched += $email
    }

    $totalProcessed += $fileCount
    $totalMatched += $fileMatched
    Write-Host "  $fileCount emails processed, $fileMatched matched"
}

Write-Host "`nTOTAL: $totalProcessed emails processed, $totalMatched matched, $($allMatched.Count) unique"

# Output as JSON — configure output path to match your environment
$outputPath = $env:EMAIL_PARSE_OUTPUT
if (-not $outputPath) {
    $outputPath = Join-Path $PSScriptRoot "..\matched_emails.json"
}
$json = $allMatched | ConvertTo-Json -Depth 5 -Compress
$outputPath = $env:OUTPUT_JSON ?? '.\matched_emails.json'
[System.IO.File]::WriteAllText($outputPath, $json, [System.Text.Encoding]::UTF8)
Write-Host "Output written to: $outputPath"
