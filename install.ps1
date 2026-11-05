# Install BetterGravity to Antigravity global plugin directory
$ErrorActionPreference = "Stop"

$targetDir = Join-Path $env:USERPROFILE ".gemini\config\plugins\budget-orchestrator"
$sourceDir = $PSScriptRoot

Write-Host ">>> Installing BetterGravity to Antigravity Global Environment..." -ForegroundColor Cyan
Write-Host "Target: $targetDir" -ForegroundColor Gray

if (!(Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

# Copy files
Copy-Item -Path (Join-Path $sourceDir "plugin.json") -Destination $targetDir -Force
Copy-Item -Path (Join-Path $sourceDir "rules") -Destination $targetDir -Recurse -Force
Copy-Item -Path (Join-Path $sourceDir "scripts") -Destination $targetDir -Recurse -Force

# Clean runtime logs in target if any
$unneeded = @(
    (Join-Path $targetDir "scripts\__pycache__"),
    (Join-Path $targetDir "quota_watcher_state.json"),
    (Join-Path $targetDir "watcher.log")
)
foreach ($item in $unneeded) {
    if (Test-Path $item) {
        Remove-Item -Path $item -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ">>> [SUCCESS] Installation completed successfully!" -ForegroundColor Green
Write-Host ">>> Antigravity will now automatically enforce budget guards & concurrency rules globally." -ForegroundColor Green
