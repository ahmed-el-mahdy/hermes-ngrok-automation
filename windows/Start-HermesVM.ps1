param(
    [string]$VmPath = "E:\VM\Ubuntu Mini Serv2\Clone of Ubuntu 64-bit.vmx",
    [string]$VmwareExe = "C:\Program Files\VMware\VMware Workstation\vmware.exe",
    [string]$VmrunExe = "C:\Program Files\VMware\VMware Workstation\vmrun.exe",
    [string]$VmAddress = "192.168.1.5",
    [string]$PortalUrl = "https://depravity-backpedal-stress.ngrok-free.dev",
    [int]$StartupDelaySeconds = 10,
    [int]$VmReadyTimeoutSeconds = 300,
    [int]$PortalReadyTimeoutSeconds = 420,
    [string]$LogPath = "$env:LOCALAPPDATA\HermesVMStartup\startup.log"
)

$ErrorActionPreference = "Stop"

function Write-StartupLog {
    param([string]$Message)

    $logDirectory = Split-Path -Parent $LogPath
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    if ((Test-Path -LiteralPath $LogPath) -and
        (Get-Item -LiteralPath $LogPath).Length -gt 1MB) {
        Move-Item -LiteralPath $LogPath -Destination "$LogPath.previous" -Force
    }
    "[$(Get-Date -Format o)] $Message" | Add-Content -LiteralPath $LogPath
}

function Test-TcpPort {
    param(
        [string]$Address,
        [int]$Port,
        [int]$TimeoutMilliseconds = 2000
    )

    $client = [Net.Sockets.TcpClient]::new()
    try {
        $connection = $client.ConnectAsync($Address, $Port)
        if (-not $connection.Wait($TimeoutMilliseconds)) {
            return $false
        }
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Wait-ForCondition {
    param(
        [scriptblock]$Condition,
        [int]$TimeoutSeconds,
        [int]$PollSeconds = 3
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) {
            return $true
        }
        Start-Sleep -Seconds $PollSeconds
    }
    return $false
}

if ($StartupDelaySeconds -gt 0) {
    Start-Sleep -Seconds $StartupDelaySeconds
}

foreach ($requiredPath in @($VmPath, $VmwareExe, $VmrunExe)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        Write-StartupLog "Required file was not found: $requiredPath"
        throw "Required file was not found: $requiredPath"
    }
}

$expectedVmPath = [IO.Path]::GetFullPath($VmPath)
$runningOutput = @(& $VmrunExe list 2>&1)
if ($LASTEXITCODE -ne 0) {
    $details = $runningOutput -join [Environment]::NewLine
    Write-StartupLog "vmrun list failed: $details"
    throw "Unable to inspect running VMware machines."
}

$runningVmPaths = @($runningOutput | Select-Object -Skip 1)
$isRunning = $false
foreach ($runningVmPath in $runningVmPaths) {
    $candidate = "$runningVmPath".Trim()
    if (-not $candidate) {
        continue
    }
    if ([string]::Equals(
        [IO.Path]::GetFullPath($candidate),
        $expectedVmPath,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        $isRunning = $true
        break
    }
}

if ($isRunning) {
    Write-StartupLog "Ubuntu Mini Hermes is already running."
} else {
    Write-StartupLog "Starting Ubuntu Mini Hermes."
    $startOutput = @(& $VmrunExe start $VmPath gui 2>&1)
    if ($LASTEXITCODE -ne 0) {
        $details = $startOutput -join [Environment]::NewLine
        Write-StartupLog "vmrun start failed: $details"
        throw "VMware could not start Ubuntu Mini Hermes."
    }
}

# Open the VM tab even when vmrun found an already-running guest.
$vmwareArguments = '"{0}"' -f $VmPath
Start-Process -FilePath $VmwareExe -ArgumentList $vmwareArguments

$sshReady = Wait-ForCondition `
    -TimeoutSeconds $VmReadyTimeoutSeconds `
    -Condition { Test-TcpPort -Address $VmAddress -Port 22 }
if (-not $sshReady) {
    Write-StartupLog "Ubuntu became visible in VMware, but SSH at $VmAddress did not become ready."
    throw "Ubuntu Mini Hermes did not become reachable at $VmAddress."
}
Write-StartupLog "Ubuntu SSH is ready at $VmAddress."

$portalReady = Wait-ForCondition `
    -TimeoutSeconds $PortalReadyTimeoutSeconds `
    -PollSeconds 5 `
    -Condition {
        try {
            $response = Invoke-WebRequest `
                -Uri $PortalUrl `
                -UseBasicParsing `
                -TimeoutSec 10 `
                -Headers @{ "ngrok-skip-browser-warning" = "true" }
            return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
        } catch {
            return $false
        }
    }
if (-not $portalReady) {
    Write-StartupLog "Ubuntu is reachable, but the Hermes portal did not become ready: $PortalUrl"
    throw "Hermes portal did not become ready before the timeout."
}

Write-StartupLog "Hermes portal and Telegram gateway startup path are ready."
