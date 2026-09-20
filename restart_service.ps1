$ErrorActionPreference = "Stop"

$workspaceDir = $PSScriptRoot
$uvicornCommand = "uvicorn"
$appModule = "rewrite_service.app:app"

Write-Host "Looking for existing $appModule processes..."
# Find and stop existing uvicorn processes for this app
$processes = Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -match $appModule }
if ($processes) {
    foreach ($proc in $processes) {
        Write-Host "Stopping process ID $($proc.ProcessId)..."
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Stopped existing services."
} else {
    Write-Host "No existing services found."
}

# Start the new service
$venvPython = Join-Path $workspaceDir ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment not found at $venvPython. Please create it first."
    exit 1
}

Write-Host "Starting service..."
# Use Start-Process to run it in the background without keeping the window open
$startArgs = @(
    "-m", "uvicorn", 
    $appModule, 
    "--host", "127.0.0.1", 
    "--port", "8787"
)

Start-Process -FilePath $venvPython -ArgumentList $startArgs -WindowStyle Hidden -WorkingDirectory $workspaceDir -RedirectStandardOutput "service.out" -RedirectStandardError "service.err"

Write-Host "Service successfully started on http://127.0.0.1:8787"

Write-Host "Waiting for service to become available..."
$url = "http://127.0.0.1:8787/health"
$maxRetries = 30
$retryCount = 0
$serviceUp = $false

while ($retryCount -lt $maxRetries) {
    try {
        $response = Invoke-RestMethod -Uri $url -Method Get -ErrorAction Stop
        if ($response.status -eq "ok") {
            $serviceUp = $true
            break
        }
    } catch {
        # Ignore and retry
    }
    Start-Sleep -Seconds 1
    $retryCount++
}

if (-not $serviceUp) {
    Write-Warning "Service did not become available within 30 seconds."
    exit
}

Write-Host "Service is up. Triggering a warm-up call to initialize the Playwright session..."
$longText = "This is a dummy text string designed specifically to be long enough to bypass the thirty word minimum limit imposed by the upstream API. By sending this text, we ensure that the warm-up call succeeds and properly initializes the browser session without throwing any HTTP 422 validation errors along the way."
$body = @{ text = $longText } | ConvertTo-Json
try {
    $warmupResponse = Invoke-RestMethod http://127.0.0.1:8787/v1/rewrite -Method Post -ContentType "application/json" -Body $body -TimeoutSec 120
    Write-Host "Warm-up successful!"
} catch {
    Write-Warning "Warm-up call failed: $_"
}
