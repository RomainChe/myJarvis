# Phase 2 étape 1 : commutateur externe + VM Home Assistant OS (docs/DOMOTIQUE_PLAN.md §1.2).
# À lancer dans un PowerShell administrateur : .\scripts\haos_vm.ps1 -Vhdx C:\HyperV\HAOS\haos_ova-XX.vhdx
param(
    [Parameter(Mandatory)][string]$Vhdx,
    [string]$Carte = "Ethernet"
)
#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

if (-not (Test-Path $Vhdx)) { throw "VHDX introuvable : $Vhdx" }
if (Get-VM -Name HomeAssistant -ErrorAction SilentlyContinue) { throw "La VM HomeAssistant existe déjà." }

if (-not (Get-VMSwitch -Name JarvisLAN -ErrorAction SilentlyContinue)) {
    New-VMSwitch -Name JarvisLAN -NetAdapterName $Carte -AllowManagementOS $true | Out-Null
}
New-VM -Name HomeAssistant -Generation 2 -MemoryStartupBytes 4GB -VHDPath $Vhdx -SwitchName JarvisLAN | Out-Null
Set-VM -Name HomeAssistant -ProcessorCount 2 -StaticMemory -CheckpointType Disabled `
    -AutomaticStartAction Start -AutomaticStartDelay 30 -AutomaticStopAction ShutDown
Set-VMFirmware -VMName HomeAssistant -EnableSecureBoot Off
Start-VM -Name HomeAssistant
Get-VM -Name HomeAssistant | Format-List Name, State, ProcessorCount, MemoryStartup
