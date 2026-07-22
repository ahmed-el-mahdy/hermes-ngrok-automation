param(
    [string]$TaskName = "Hermes Ollama Service",
    [string]$Model = "qwen3-4b-gpu:latest",
    [string]$ReportPath = "C:\ProgramData\HermesOllama\recovery-test.json",
    [int]$TimeoutSeconds = 240
)

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this recovery test from an elevated PowerShell session."
}

$task = Get-ScheduledTask -TaskName $TaskName
$before = Get-NetTCPConnection -LocalPort 11434 -State Listen |
    Select-Object -First 1
if (-not $before) {
    throw "Ollama is not listening on port 11434 before the recovery test."
}

$oldProcessId = $before.OwningProcess
$startedAt = Get-Date
Stop-Process -Id $oldProcessId -Force

$ready = $false
$newProcessId = $null
$fullGpu = $false
for ($attempt = 1; $attempt -le $TimeoutSeconds; $attempt++) {
    Start-Sleep -Seconds 1
    try {
        $listener = Get-NetTCPConnection -LocalPort 11434 -State Listen |
            Select-Object -First 1
        if (-not $listener -or $listener.OwningProcess -eq $oldProcessId) {
            continue
        }

        $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
        $processState = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/ps" -TimeoutSec 3
        $loaded = $processState.models |
            Where-Object { $_.name -eq $Model } |
            Select-Object -First 1
        $fullGpu = $loaded -and ([int64]$loaded.size_vram -eq [int64]$loaded.size)
        if (($tags.models.name -contains $Model) -and $fullGpu) {
            $newProcessId = $listener.OwningProcess
            $ready = $true
            break
        }
    } catch {
        # The listener and model are expected to be unavailable during restart.
    }
}

$result = [pscustomobject]@{
    Task = $TaskName
    TaskState = (Get-ScheduledTask -TaskName $TaskName).State.ToString()
    OldProcessId = $oldProcessId
    NewProcessId = $newProcessId
    Restarted = $ready -and $newProcessId -ne $oldProcessId
    Model = $Model
    GpuFullyLoaded = $fullGpu
    Seconds = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
    Passed = $ready
}

$reportDirectory = Split-Path -Parent $ReportPath
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$result | ConvertTo-Json | Set-Content -LiteralPath $ReportPath -Encoding utf8
$result

if (-not $ready) {
    throw "Ollama did not recover with the model fully on GPU within $TimeoutSeconds seconds."
}
