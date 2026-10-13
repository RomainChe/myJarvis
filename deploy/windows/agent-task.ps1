# Agent PC (lot 3) en tâche planifiée + règle de pare-feu limitée au mini-PC. À lancer en administrateur :
#   .\agent-task.ps1 -TailscaleHost 100.x.y.z -MiniPc 100.a.b.c
# Aucune adresse n'est dans le dépôt : elles se passent en paramètres. Retrait : -Remove.
param([string]$TailscaleHost, [string]$MiniPc, [int]$Port = 8788, [switch]$Remove)
$ErrorActionPreference = "Stop"
$task, $rule = "JARVIS - agent PC", "JARVIS agent PC (mini-PC seul)"
if ($Remove) {
    Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue
    return
}
if (-not $TailscaleHost -or -not $MiniPc) { throw "-TailscaleHost et -MiniPc requis" }
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$pyw = (Get-Command pythonw.exe).Source
[Environment]::SetEnvironmentVariable("JARVIS_AGENT_HOST", $TailscaleHost, "User")
[Environment]::SetEnvironmentVariable("JARVIS_AGENT_PORT", "$Port", "User")
New-NetFirewallRule -DisplayName $rule -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
    -LocalAddress $TailscaleHost -RemoteAddress $MiniPc | Out-Null
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $task -Principal $principal `
    -Action (New-ScheduledTaskAction -Execute $pyw -Argument "-m jarvis.agent serve" -WorkingDirectory $repo) `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) `
    -Settings (New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
               -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries) | Out-Null
Write-Host "Agent enregistré. Clé : python -m jarvis secret set agent_key (la même valeur sur le mini-PC)."
