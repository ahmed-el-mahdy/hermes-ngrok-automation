param(
    [string]$VmAddress = "192.168.1.5",
    [string]$OllamaExe = "C:\Users\A Elmahdy\AppData\Local\Programs\Ollama\ollama.exe",
    [string]$ModelsPath = "C:\Users\A Elmahdy\.ollama\models"
)

$ErrorActionPreference = "Stop"
$taskName = "Hermes Ollama Service"
$firewallName = "Hermes VM to Ollama"
$installDirectory = "C:\ProgramData\HermesOllama"
$installedLauncher = Join-Path $installDirectory "Start-HermesOllama.ps1"
$sourceLauncher = Join-Path $PSScriptRoot "Start-HermesOllama.ps1"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this installer from an elevated PowerShell session."
}

if (-not (Test-Path -LiteralPath $OllamaExe -PathType Leaf)) {
    throw "Ollama executable was not found: $OllamaExe"
}
if (-not (Test-Path -LiteralPath $ModelsPath -PathType Container)) {
    throw "Ollama model directory was not found: $ModelsPath"
}

New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
Copy-Item -LiteralPath $sourceLauncher -Destination $installedLauncher -Force

# Disable broad inbound application rules for Ollama before adding the VM-only rule.
Get-NetFirewallApplicationFilter -Program $OllamaExe -ErrorAction SilentlyContinue |
    Get-NetFirewallRule -ErrorAction SilentlyContinue |
    Where-Object { $_.Direction -eq "Inbound" -and $_.Action -eq "Allow" } |
    Disable-NetFirewallRule

Get-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
New-NetFirewallRule `
    -DisplayName $firewallName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 11434 `
    -RemoteAddress $VmAddress `
    -Profile Any | Out-Null

$arguments = @(
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"{0}"' -f $installedLauncher),
    "-OllamaExe", ('"{0}"' -f $OllamaExe),
    "-ModelsPath", ('"{0}"' -f $ModelsPath)
) -join " "
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$systemPrincipal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $systemPrincipal `
    -Description "Persistent native Ollama GPU service for the Hermes VM" `
    -Force | Out-Null

Get-Process -Name "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $taskName

$ready = $false
$gpuFullyLoaded = $false
for ($attempt = 1; $attempt -le 180; $attempt++) {
    Start-Sleep -Seconds 1
    try {
        $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
        $processState = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/ps" -TimeoutSec 3
        $model = $processState.models |
            Where-Object { $_.name -eq "qwen3-4b-gpu:latest" } |
            Select-Object -First 1
        $gpuFullyLoaded = $model -and ([int64]$model.size_vram -eq [int64]$model.size)
        if (($tags.models.name -contains "qwen3-4b-gpu:latest") -and $gpuFullyLoaded) {
            $ready = $true
            break
        }
    } catch {
        # Task Scheduler restarts the server if startup fails.
    }
}
if (-not $ready) {
    throw "The scheduled Ollama server did not preload Qwen fully on GPU within 180 seconds."
}

[pscustomobject]@{
    Task = $taskName
    TaskState = (Get-ScheduledTask -TaskName $taskName).State
    Listener = "0.0.0.0:11434"
    AllowedRemoteAddress = $VmAddress
    Model = "qwen3-4b-gpu:latest"
    GpuFullyLoaded = $gpuFullyLoaded
    Ready = $ready
}
