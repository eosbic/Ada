param(
    [ValidateSet("api", "bot", "both")]
    [string]$Target = "api",
    [string]$EnvFile = ".env",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [int]$MaxPortProbe = 20
)

$ErrorActionPreference = "Stop"

function Import-DotEnv {
    param([string]$Path)

    if (!(Test-Path $Path)) {
        throw "No se encontro archivo de entorno: $Path"
    }

    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ([string]::IsNullOrWhiteSpace($line)) { return }
        if ($line.StartsWith("#")) { return }
        if ($line -notmatch "=") { return }

        $parts = $line.Split("=", 2)
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()

        if ($name) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Test-PortListening {
    param([int]$LocalPort)

    $listener = Get-NetTCPConnection -State Listen -LocalPort $LocalPort -ErrorAction SilentlyContinue
    return [bool]$listener
}

function Resolve-ApiPort {
    param(
        [int]$DesiredPort,
        [int]$MaxProbe
    )

    $candidate = $DesiredPort
    for ($i = 0; $i -lt $MaxProbe; $i++) {
        if (-not (Test-PortListening -LocalPort $candidate)) {
            return $candidate
        }
        $candidate++
    }

    throw "No se encontro un puerto libre desde $DesiredPort en el rango de $MaxProbe intentos."
}

function Stop-ProjectPythonProcesses {
    param(
        [string]$RepoRootPath,
        [string[]]$CommandMarkers
    )

    $targets = Get-CimInstance Win32_Process -Filter "name='python.exe'" |
        Where-Object {
            $cmd = $_.CommandLine
            $_.CommandLine -and
            $cmd -like "*$RepoRootPath*" -and
            ($CommandMarkers | Where-Object { $_ -and $_.Length -gt 0 -and $cmd -like "*$_*" })
        }

    foreach ($p in $targets) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Host "Proceso detenido (PID: $($p.ProcessId)) -> $($p.CommandLine)"
        }
        catch {
            Write-Host "No se pudo detener PID $($p.ProcessId): $($_.Exception.Message)"
        }
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExe = Join-Path $repoRoot "venv\\Scripts\\python.exe"
$envPath = if ([System.IO.Path]::IsPathRooted($EnvFile)) { $EnvFile } else { Join-Path $repoRoot $EnvFile }

if (!(Test-Path $pythonExe)) {
    throw "No se encontro Python del entorno virtual en: $pythonExe"
}

Import-DotEnv -Path $envPath

Write-Host "Entorno cargado desde $envPath"

if ($Target -in @("api", "both")) {
    Stop-ProjectPythonProcesses -RepoRootPath $repoRoot -CommandMarkers @("-m uvicorn api.main:app")
}
if ($Target -in @("bot", "both")) {
    Stop-ProjectPythonProcesses -RepoRootPath $repoRoot -CommandMarkers @("-m bot.telegram_bot")
}

$apiPort = $Port
if ($Target -in @("api", "both")) {
    $apiPort = Resolve-ApiPort -DesiredPort $Port -MaxProbe $MaxPortProbe
    if ($apiPort -ne $Port) {
        Write-Host "Puerto $Port ocupado. Usando puerto libre $apiPort."
    }

    $apiHostForBot = if ($BindHost -eq "0.0.0.0") { "127.0.0.1" } else { $BindHost }
    $apiUrl = "http://$apiHostForBot`:$apiPort"
    [Environment]::SetEnvironmentVariable("ADA_API_URL", $apiUrl, "Process")
    Write-Host "ADA_API_URL=$apiUrl"
}

if ($Target -eq "api") {
    & $pythonExe -m uvicorn api.main:app --host $BindHost --port $apiPort
    exit $LASTEXITCODE
}

if ($Target -eq "bot") {
    & $pythonExe -m bot.telegram_bot
    exit $LASTEXITCODE
}

# both
$botProc = Start-Process -FilePath $pythonExe -ArgumentList "-m", "bot.telegram_bot" -WorkingDirectory $repoRoot -NoNewWindow -PassThru
Write-Host "Bot iniciado (PID: $($botProc.Id))"

try {
    & $pythonExe -m uvicorn api.main:app --host $BindHost --port $apiPort
    exit $LASTEXITCODE
}
finally {
    if ($botProc -and -not $botProc.HasExited) {
        Stop-Process -Id $botProc.Id -Force
        Write-Host "Bot detenido (PID: $($botProc.Id))"
    }
}
