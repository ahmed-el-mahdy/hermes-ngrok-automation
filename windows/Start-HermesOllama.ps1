param(
    [string]$OllamaExe = "C:\Users\A Elmahdy\AppData\Local\Programs\Ollama\ollama.exe",
    [string]$ModelsPath = "C:\Users\A Elmahdy\.ollama\models",
    [string]$ListenAddress = "0.0.0.0:11434",
    [string]$LogPath = "C:\ProgramData\HermesOllama\ollama.log"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $OllamaExe -PathType Leaf)) {
    throw "Ollama executable was not found: $OllamaExe"
}
if (-not (Test-Path -LiteralPath $ModelsPath -PathType Container)) {
    throw "Ollama model directory was not found: $ModelsPath"
}

$logDirectory = Split-Path -Parent $LogPath
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

$env:OLLAMA_HOST = $ListenAddress
$env:OLLAMA_MODELS = $ModelsPath
$env:OLLAMA_KEEP_ALIVE = "-1"
$env:OLLAMA_MAX_LOADED_MODELS = "1"
$env:OLLAMA_NUM_PARALLEL = "1"
$env:OLLAMA_FLASH_ATTENTION = "1"

$stdoutLog = Join-Path $logDirectory "ollama.stdout.log"
$stderrLog = Join-Path $logDirectory "ollama.stderr.log"
"[$(Get-Date -Format o)] Starting Ollama on $ListenAddress" | Add-Content -LiteralPath $LogPath
$server = Start-Process `
    -FilePath $OllamaExe `
    -ArgumentList "serve" `
    -PassThru `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog

try {
    $ready = $false
    for ($attempt = 1; $attempt -le 90; $attempt++) {
        Start-Sleep -Seconds 1
        if ($server.HasExited) {
            throw "Ollama exited during startup with code $($server.ExitCode)."
        }
        try {
            $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
            if ($tags.models.name -contains "qwen3-4b-gpu:latest") {
                $ready = $true
                break
            }
        } catch {
            # Continue until the bounded startup timeout expires.
        }
    }
    if (-not $ready) {
        throw "Ollama did not become ready within 90 seconds."
    }

    $preload = @{
        model = "qwen3-4b-gpu:latest"
        prompt = ""
        stream = $false
        keep_alive = -1
    } | ConvertTo-Json
    Invoke-RestMethod `
        -Uri "http://127.0.0.1:11434/api/generate" `
        -Method Post `
        -ContentType "application/json" `
        -Body $preload `
        -TimeoutSec 180 | Out-Null

    $processState = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/ps" -TimeoutSec 15
    $model = $processState.models | Where-Object { $_.name -eq "qwen3-4b-gpu:latest" } | Select-Object -First 1
    if (-not $model) {
        throw "qwen3-4b-gpu:latest was not loaded after preload."
    }
    if ([int64]$model.size_vram -ne [int64]$model.size) {
        throw "The Qwen model is not fully loaded on GPU: VRAM=$($model.size_vram), size=$($model.size)."
    }
    "[$(Get-Date -Format o)] qwen3-4b-gpu:latest preloaded 100% on GPU" |
        Add-Content -LiteralPath $LogPath

    Wait-Process -Id $server.Id
    exit $server.ExitCode
} finally {
    if (-not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
}
