param(
    [string]$VmPath = "E:\VM\Ubuntu Mini Serv2\Clone of Ubuntu 64-bit.vmx",
    [string]$VmwareExe = "C:\Program Files\VMware\VMware Workstation\vmware.exe",
    [string]$VmrunExe = "C:\Program Files\VMware\VMware Workstation\vmrun.exe",
    [string]$VmAddress = "192.168.1.5",
    [string]$PortalUrl = "https://depravity-backpedal-stress.ngrok-free.dev"
)

$ErrorActionPreference = "Stop"
$taskName = "Hermes VM Autostart"
$installDirectory = Join-Path $env:LOCALAPPDATA "HermesVMStartup"
$installedLauncher = Join-Path $installDirectory "Start-HermesVM.ps1"
$sourceLauncher = Join-Path $PSScriptRoot "Start-HermesVM.ps1"

foreach ($requiredPath in @($VmPath, $VmwareExe, $VmrunExe, $sourceLauncher)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file was not found: $requiredPath"
    }
}

New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
Copy-Item -LiteralPath $sourceLauncher -Destination $installedLauncher -Force

$launcherArguments = @(
    "-NoProfile",
    "-NonInteractive",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"{0}"' -f $installedLauncher),
    "-VmPath", ('"{0}"' -f $VmPath),
    "-VmwareExe", ('"{0}"' -f $VmwareExe),
    "-VmrunExe", ('"{0}"' -f $VmrunExe),
    "-VmAddress", $VmAddress,
    "-PortalUrl", $PortalUrl
) -join " "

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $launcherArguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Open VMware, start Ubuntu Mini Hermes, and verify the Hermes portal at user logon" `
    -Force | Out-Null

Start-ScheduledTask -TaskName $taskName

$completed = $false
for ($attempt = 1; $attempt -le 900; $attempt++) {
    Start-Sleep -Seconds 1
    $task = Get-ScheduledTask -TaskName $taskName
    if ($task.State -ne "Running") {
        $completed = $true
        break
    }
}
if (-not $completed) {
    throw "The startup task did not finish its verification within 900 seconds."
}

$taskInfo = Get-ScheduledTaskInfo -TaskName $taskName
if ($taskInfo.LastTaskResult -ne 0) {
    throw "The startup task failed with result $($taskInfo.LastTaskResult). Check $installDirectory\startup.log."
}

[pscustomobject]@{
    Task = $taskName
    State = (Get-ScheduledTask -TaskName $taskName).State
    Trigger = "At logon for $env:USERNAME"
    Vm = $VmPath
    VmAddress = $VmAddress
    Portal = $PortalUrl
    LastTaskResult = $taskInfo.LastTaskResult
    Log = Join-Path $installDirectory "startup.log"
}
