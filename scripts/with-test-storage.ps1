$ErrorActionPreference = 'Stop'
if ($args.Count -eq 0) {
    throw 'Usage: with-test-storage.ps1 <command> [arguments...]'
}
$command, $commandArgs = $args
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$scratch = Join-Path $repo '.tmp'
$storage = Join-Path $scratch 'test-storage'

# Do not follow a junction back to the system drive.
foreach ($path in @($scratch, $storage)) {
    [void][IO.Directory]::CreateDirectory($path)
    if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Test storage cannot use a junction or symlink: $path"
    }
}

$directories = @{
    TEMP = 'temp'
    TMP = 'temp'
    TMPDIR = 'temp'
    PIP_CACHE_DIR = 'pip'
    UV_CACHE_DIR = 'uv'
    NPM_CONFIG_CACHE = 'npm'
    PLAYWRIGHT_BROWSERS_PATH = 'playwright'
    NODE_COMPILE_CACHE = 'node'
}
$previous = @{}
try {
    foreach ($name in $directories.Keys) {
        $path = Join-Path $storage $directories[$name]
        [void][IO.Directory]::CreateDirectory($path)
        if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Test storage cannot use a junction or symlink: $path"
        }
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $path, 'Process')
    }
    $global:LASTEXITCODE = 0
    & $command @commandArgs
    exit $LASTEXITCODE
}
finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}
