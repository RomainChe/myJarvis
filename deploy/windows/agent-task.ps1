# Agent PC (lot 3) en tâche planifiée + Ollama sur l'IP Tailscale (D15) + pare-feu limité au mini-PC.
# À lancer en administrateur :
#   .\agent-task.ps1 -TailscaleHost 100.x.y.z -MiniPc 100.a.b.c
# Aucune adresse n'est dans le dépôt : elles se passent en paramètres. Relançable. Retrait : -Remove.
param([string]$TailscaleHost, [string]$MiniPc, [int]$Port = 8788, [switch]$Remove)
$ErrorActionPreference = "Stop"
$task = "JARVIS - agent PC"
$rules = @{ "JARVIS agent PC (mini-PC seul)" = $Port; "JARVIS Ollama (mini-PC seul)" = 11434 }
Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
foreach ($r in $rules.Keys) { Remove-NetFirewallRule -DisplayName $r -ErrorAction SilentlyContinue }
if ($Remove) {
    # Ollama revient sur 127.0.0.1 (INSTALL §3) ; à relancer pour que ce soit pris en compte.
    foreach ($v in "OLLAMA_HOST", "JARVIS_AGENT_HOST", "JARVIS_AGENT_PORT") {
        [Environment]::SetEnvironmentVariable($v, $null, "User")
    }
    return
}
if (-not $TailscaleHost -or -not $MiniPc) { throw "-TailscaleHost et -MiniPc requis" }
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$pyw = (Get-Command pythonw.exe).Source
[Environment]::SetEnvironmentVariable("JARVIS_AGENT_HOST", $TailscaleHost, "User")
[Environment]::SetEnvironmentVariable("JARVIS_AGENT_PORT", "$Port", "User")
# Jamais 0.0.0.0 : Ollama n'écoute que sur l'IP Tailscale du PC.
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "${TailscaleHost}:11434", "User")
foreach ($r in $rules.Keys) {
    New-NetFirewallRule -DisplayName $r -Direction Inbound -Action Allow -Protocol TCP -LocalPort $rules[$r] `
        -LocalAddress $TailscaleHost -RemoteAddress $MiniPc | Out-Null
}
# Une règle « Autoriser » plus large (installateur, fenêtre « Autoriser l'accès ») annulerait la restriction :
# la signaler. Relancer ce script après la relance d'Ollama, la fenêtre pouvant en créer une à son premier écoute.
# Les règles « tous ports, tous programmes » ne sont pas cherchées : le test depuis le téléphone (étape A.8) les couvre.
# foreach, pas un pipeline : Get-NetFirewallRule sans entrée renverrait toutes les règles.
$filters = @(Get-NetFirewallApplicationFilter | Where-Object Program -Match "ollama|python") +
           @(Get-NetFirewallPortFilter | Where-Object { @($_.LocalPort | Where-Object { $_ -in "$Port", "11434" }).Count })
$wide = foreach ($f in $filters) { $f | Get-NetFirewallRule }
$wide | Where-Object { $_.Direction -eq "Inbound" -and $_.Action -eq "Allow" -and $_.Enabled -eq "True" -and
                       $_.DisplayName -notin $rules.Keys } |
    Sort-Object DisplayName -Unique |
    ForEach-Object { Write-Warning "Règle entrante plus large à désactiver : $($_.DisplayName)" }
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $task -Principal $principal `
    -Action (New-ScheduledTaskAction -Execute $pyw -Argument "-m jarvis.agent serve" -WorkingDirectory $repo) `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) `
    -Settings (New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
               -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries) | Out-Null
Write-Host "Agent enregistré. Clé : python -m jarvis secret set agent_key (la même valeur sur le mini-PC)."
Write-Host "Relance Ollama (icône de la zone de notification > Quit, puis relancer) pour qu'il écoute sur $TailscaleHost."
