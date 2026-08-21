param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$uv = Join-Path $HOME ".local\bin\uv.exe"
if (-not (Test-Path $uv)) {
    throw "uv.exe not found at $uv"
}

& $uv run --python 3.14 --with pypdf --with cryptography python "$PSScriptRoot\ingest_onedrive.py" @Args
