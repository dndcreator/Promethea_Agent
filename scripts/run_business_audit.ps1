param(
    [ValidateSet("smoke", "core", "contracts", "business", "full")]
    [string]$Suite = "business",
    [switch]$Live,
    [switch]$Coverage,
    [string]$Pattern = "",
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Resolve-Python {
    if ($env:PROMETHEA_PYTHON -and (Test-Path $env:PROMETHEA_PYTHON)) {
        return $env:PROMETHEA_PYTHON
    }

    $candidates = @(
        (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
        (Join-Path (Split-Path $RepoRoot -Parent) ".venv\Scripts\python.exe"),
        (Join-Path $RepoRoot "venv\Scripts\python.exe"),
        (Join-Path $RepoRoot "env\Scripts\python.exe")
    )

    foreach ($path in $candidates) {
        if (Test-Path $path) {
            return $path
        }
    }

    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    throw "Python interpreter not found. Set PROMETHEA_PYTHON or create .venv."
}

$python = Resolve-Python
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logDir = Join-Path $RepoRoot "logs\test-audit"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "${stamp}-${Suite}.log"
$tmpDir = Join-Path $RepoRoot ".tmp\pytest\$stamp"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$env:TEMP = $tmpDir
$env:TMP = $tmpDir
$env:PYTEST_DEBUG_TEMPROOT = $tmpDir

$args = @("tests/run_all_tests.py", "--suite", $Suite)
if ($Live) { $args += "--live" }
if ($Coverage) { $args += "--coverage" }
if ($Verbose) { $args += "--verbose" }
if ($Pattern) { $args += @("--pattern", $Pattern) }

Write-Host "[audit] repo:    $RepoRoot"
Write-Host "[audit] python:  $python"
Write-Host "[audit] suite:   $Suite"
Write-Host "[audit] log:     $logPath"
Write-Host "[audit] command: $python $($args -join ' ')"

& $python @args *>&1 | Tee-Object -FilePath $logPath
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "[audit] FAILED (exit=$exitCode). See: $logPath"
    exit $exitCode
}

Write-Host "[audit] PASSED. See: $logPath"
exit 0
