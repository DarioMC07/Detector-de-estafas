# Inicia el servidor accesible desde los celulares conectados al mismo Wi-Fi.
# Uso (desde la carpeta del proyecto):  powershell -ExecutionPolicy Bypass -File .\iniciar_servidor_red.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host 'No se encontró .venv. Crea el entorno primero (ver README).' -ForegroundColor Red
    exit 1
}

$ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254*' -and $_.InterfaceAlias -notlike '*VirtualBox*' -and $_.IPAddress -ne '192.168.56.1' } |
    Select-Object -ExpandProperty IPAddress

Write-Host ''
Write-Host 'Escribe una de estas direcciones en la app (Servidor > Cambiar):' -ForegroundColor Cyan
foreach ($ip in $ips) { Write-Host "   http://${ip}:8000" -ForegroundColor Green }
Write-Host ''
Write-Host 'El teléfono debe estar en la misma red Wi-Fi. Ctrl+C para detener.' -ForegroundColor DarkGray
Write-Host ''

& $python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
