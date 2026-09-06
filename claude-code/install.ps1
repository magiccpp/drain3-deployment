# Install the logsum PreToolUse hook into Claude Code on Windows (summarizer runs in WSL2).
# Usage (PowerShell):  .\install.ps1 -Distro Ubuntu-24.04 -LogsumPath /home/<user>/.local/bin/logsum
param(
  [string]$Distro = "Ubuntu-24.04",
  [string]$LogsumPath = "",
  [string]$Agent = "claude-code"
)
$ErrorActionPreference = "Stop"
if (-not $LogsumPath) {
  $wslUser = (wsl.exe -d $Distro -- bash -c 'echo $HOME').Trim()
  $LogsumPath = "$wslUser/.local/bin/logsum"
}
$hooksDir = Join-Path $env:USERPROFILE ".claude\hooks"
New-Item -ItemType Directory -Force $hooksDir | Out-Null
Copy-Item (Join-Path $PSScriptRoot "logsum-hook.js") (Join-Path $hooksDir "logsum-hook.js") -Force
$cfg = @{ distro = $Distro; logsum = $LogsumPath; agent = $Agent } | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $hooksDir "logsum-hook.config.json"), $cfg, (New-Object Text.UTF8Encoding $false))

# Merge the hook into ~/.claude/settings.json without touching other settings.
$settingsPath = Join-Path $env:USERPROFILE ".claude\settings.json"
$settings = @{}
if (Test-Path $settingsPath) {
  Copy-Item $settingsPath "$settingsPath.before-logsum" -Force
  $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
}
$hookEntry = [pscustomobject]@{
  matcher = "Bash|PowerShell"
  hooks = @([pscustomobject]@{ type = "command"; command = "node"; args = @((Join-Path $hooksDir "logsum-hook.js")); timeout = 10 })
}
if (-not $settings.PSObject.Properties["hooks"]) { $settings | Add-Member -NotePropertyName hooks -NotePropertyValue ([pscustomobject]@{}) }
$pre = @()
if ($settings.hooks.PSObject.Properties["PreToolUse"]) { $pre = @($settings.hooks.PreToolUse | Where-Object { ($_.hooks | ForEach-Object { "$($_.args)" }) -notmatch "logsum-hook" }) }
$pre += $hookEntry
if ($settings.hooks.PSObject.Properties["PreToolUse"]) { $settings.hooks.PreToolUse = $pre } else { $settings.hooks | Add-Member -NotePropertyName PreToolUse -NotePropertyValue $pre }
[IO.File]::WriteAllText($settingsPath, ($settings | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding $false))

Write-Host "Installed hook: $hooksDir\logsum-hook.js"
Write-Host "Config:         distro=$Distro logsum=$LogsumPath agent=$Agent"
Write-Host "Settings:       $settingsPath (backup: $settingsPath.before-logsum)"
Write-Host "Smoke test:     wsl.exe -d $Distro -- $LogsumPath < some.log"
