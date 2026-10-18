param([int]$Port = 0, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Docker-Checked {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed. Read the error above, fix it, then retry. Data volumes are retained." }
}
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Install and start Docker Desktop: https://docs.docker.com/get-docker/'
    }
    Docker-Checked compose version
    Docker-Checked buildx version
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker is unavailable. Start Docker Desktop and use Linux containers.' }
    $help = Docker-Checked compose up --help
    if (($help -join "`n") -notmatch '--wait-timeout') { throw 'Update Docker Compose; --wait-timeout is required.' }
    if ($Port -lt 0 -or $Port -gt 65535) { throw 'Port must be 1..65535 (0 uses the saved/default port).' }
    Remove-Item Env:DQ_DB_PASSWORD, Env:DQ_ROOT_PASSWORD, Env:DQ_HTTP_PORT -ErrorAction SilentlyContinue
    $config = Join-Path (Get-Location) '.docker.env'
    if ((Test-Path $config) -and ((Get-Item $config -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw '.docker.env must not be a symbolic link.'
    }
    if (-not (Test-Path $config)) {
        $volumes = Docker-Checked volume ls --filter label=com.docker.compose.project=dq-desktop --format '{{.Name}}'
        if ($volumes) { throw 'Existing dq-desktop volumes found but .docker.env is missing. Restore the original .docker.env; do not reset your data.' }
        function New-Password {
            $bytes = New-Object byte[] 32
            $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
            try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
            return -join ($bytes | ForEach-Object { $_.ToString('x2') })
        }
        $initialPort = if ($Port) { $Port } else { 18000 }
        $lines = @("DQ_DB_PASSWORD=$(New-Password)", "DQ_ROOT_PASSWORD=$(New-Password)", "DQ_HTTP_PORT=$initialPort")
        $bytes = [Text.Encoding]::ASCII.GetBytes(($lines -join "`n") + "`n")
        $file = [IO.File]::Open($config, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $file.Write($bytes, 0, $bytes.Length) } finally { $file.Dispose() }
    }
    $raw = [IO.File]::ReadAllText($config)
    if ($raw -notmatch '(?m)^DQ_DB_PASSWORD=[a-f0-9]{64}\r?$' -or $raw -notmatch '(?m)^DQ_ROOT_PASSWORD=[a-f0-9]{64}\r?$') {
        throw 'Invalid database password config; restore .docker.env.'
    }
    $match = [regex]::Match($raw, '(?m)^DQ_HTTP_PORT=([1-9][0-9]{0,4})\r?$')
    if (-not $match.Success -or [int]$match.Groups[1].Value -gt 65535) { throw 'Invalid port in .docker.env.' }
    $savedPort = [int]$match.Groups[1].Value
    if ($Port -and $Port -ne $savedPort) {
        $raw = [regex]::Replace($raw, '(?m)^DQ_HTTP_PORT=.*$', "DQ_HTTP_PORT=$Port")
        [IO.File]::WriteAllText($config, $raw, [Text.Encoding]::ASCII)
        $savedPort = $Port
    }
    $compose = @('compose', '-p', 'dq-desktop', '--env-file', $config, '-f', 'compose.yaml')
    Docker-Checked @compose config --quiet
    Write-Host 'Building and starting; first launch requires internet and may take several minutes.'
    Docker-Checked @compose up --build -d --quiet-pull --wait --wait-timeout 180
    $url = "http://127.0.0.1:$savedPort/setup"
    Write-Host "Ready: $url"
    Write-Host 'Configure your model and API key in the browser. Database is ready.'
    if (-not $NoBrowser) { Start-Process $url }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
