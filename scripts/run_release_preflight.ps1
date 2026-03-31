param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [ValidateSet("smoke", "core", "contracts", "business", "full")]
    [string[]]$Suites = @("smoke", "core", "contracts", "business"),
    [switch]$SkipSuites,
    [int]$TimeoutSec = 20,
    [switch]$FailOnHighDoctor
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$reportDir = Join-Path $RepoRoot "logs\release-preflight\$stamp"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

function Write-JsonFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Data
    )
    $Data | ConvertTo-Json -Depth 20 | Set-Content -Path $Path -Encoding UTF8
}

function Invoke-EndpointCheck {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )
    $uri = "$BaseUrl$Path"
    try {
        $response = Invoke-RestMethod -Uri $uri -TimeoutSec $TimeoutSec -Method Get
        Write-JsonFile -Path (Join-Path $reportDir "$(($Path.TrimStart('/')).Replace('/', '_')).json") -Data $response
        return @{
            ok = $true
            path = $Path
            uri = $uri
            response = $response
            error = $null
        }
    } catch {
        return @{
            ok = $false
            path = $Path
            uri = $uri
            response = $null
            error = $_.Exception.Message
        }
    }
}

Write-Host "[preflight] repo:      $RepoRoot"
Write-Host "[preflight] base url:  $BaseUrl"
Write-Host "[preflight] report dir:$reportDir"

$endpointPaths = @(
    "/api/health",
    "/api/status",
    "/api/ops/framework-check",
    "/api/ops/surfaces",
    "/api/ops/readiness",
    "/api/doctor"
)

$endpointResults = @{}
$endpointFailures = @()
foreach ($p in $endpointPaths) {
    $ret = Invoke-EndpointCheck -Path $p
    $endpointResults[$p] = $ret
    if (-not $ret.ok) {
        $endpointFailures += "$p -> $($ret.error)"
    }
}

$readiness = $endpointResults["/api/ops/readiness"].response
$doctor = $endpointResults["/api/doctor"].response

$readinessGo = $false
$readinessReason = "readiness unavailable"
if ($readiness) {
    $goNoGo = [string]($readiness.readiness.go_no_go)
    $readinessGo = ($goNoGo -eq "go")
    $readinessReason = [string]($readiness.readiness.reason)
}

$doctorCritical = @()
$doctorHigh = @()
if ($doctor -and $doctor.recommendations) {
    $doctorCritical = @($doctor.recommendations | Where-Object { [string]$_.severity -eq "critical" })
    $doctorHigh = @($doctor.recommendations | Where-Object { [string]$_.severity -eq "high" })
}

$doctorPass = ($doctorCritical.Count -eq 0)
if ($FailOnHighDoctor) {
    $doctorPass = $doctorPass -and ($doctorHigh.Count -eq 0)
}

$suiteResults = @()
if (-not $SkipSuites) {
    foreach ($suite in $Suites) {
        Write-Host "[preflight] running suite: $suite"
        & (Join-Path $PSScriptRoot "run_business_audit.ps1") -Suite $suite
        $exitCode = $LASTEXITCODE
        $suiteResults += @{
            suite = $suite
            exit_code = $exitCode
            ok = ($exitCode -eq 0)
        }
        if ($exitCode -ne 0) {
            Write-Host "[preflight] suite failed: $suite (exit=$exitCode)"
            break
        }
    }
} else {
    Write-Host "[preflight] skipped suite execution"
}

$suitePass = ($suiteResults.Count -eq 0) -or (@($suiteResults | Where-Object { -not $_.ok }).Count -eq 0)

$blockers = @()
if ($endpointFailures.Count -gt 0) {
    $blockers += "endpoint failures: $($endpointFailures -join '; ')"
}
if (-not $readinessGo) {
    $blockers += "readiness is not go: $readinessReason"
}
if (-not $doctorPass) {
    if ($FailOnHighDoctor) {
        $blockers += "doctor has critical/high recommendations (critical=$($doctorCritical.Count), high=$($doctorHigh.Count))"
    } else {
        $blockers += "doctor has critical recommendations (count=$($doctorCritical.Count))"
    }
}
if (-not $suitePass) {
    $failedSuites = @($suiteResults | Where-Object { -not $_.ok } | ForEach-Object { $_.suite })
    $blockers += "suite failures: $($failedSuites -join ', ')"
}

$goNoGo = if ($blockers.Count -eq 0) { "GO" } else { "NO-GO" }

$summary = @{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    base_url = $BaseUrl
    report_dir = $reportDir
    decision = $goNoGo
    checks = @{
        endpoints_pass = ($endpointFailures.Count -eq 0)
        readiness_go = $readinessGo
        doctor_pass = $doctorPass
        suites_pass = $suitePass
    }
    doctor = @{
        critical_count = $doctorCritical.Count
        high_count = $doctorHigh.Count
    }
    suites = $suiteResults
    blockers = $blockers
}

Write-JsonFile -Path (Join-Path $reportDir "summary.json") -Data $summary

$md = @()
$md += "# Release Preflight Report"
$md += ""
$md += "- Generated (UTC): $($summary.generated_at)"
$md += "- Base URL: $BaseUrl"
$md += "- Decision: **$goNoGo**"
$md += ""
$md += "## Checks"
$md += ""
$md += "- Endpoints pass: $($summary.checks.endpoints_pass)"
$md += "- Readiness go: $($summary.checks.readiness_go)"
$md += "- Doctor pass: $($summary.checks.doctor_pass) (critical=$($summary.doctor.critical_count), high=$($summary.doctor.high_count))"
$md += "- Suites pass: $($summary.checks.suites_pass)"
$md += ""
$md += "## Blockers"
$md += ""
if ($blockers.Count -eq 0) {
    $md += "- none"
} else {
    foreach ($b in $blockers) {
        $md += "- $b"
    }
}
$md += ""
$md += "## Suite Results"
$md += ""
if ($suiteResults.Count -eq 0) {
    $md += "- skipped"
} else {
    foreach ($s in $suiteResults) {
        $md += "- $($s.suite): ok=$($s.ok), exit=$($s.exit_code)"
    }
}

$reportMd = Join-Path $reportDir "REPORT.md"
$md | Set-Content -Path $reportMd -Encoding UTF8

Write-Host "[preflight] decision: $goNoGo"
Write-Host "[preflight] summary:  $reportMd"

if ($goNoGo -eq "GO") {
    exit 0
}
exit 1
