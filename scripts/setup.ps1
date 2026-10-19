# Windows PowerShell 5.1 and PowerShell 7: passwordless personal Docker profile.
# Ordinary Compose automatically loads docker-compose.override.yml.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
function Invoke-Docker {
    param([Parameter(Mandatory = $true)][string[]]$DockerArguments)
    & docker @DockerArguments
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw "Docker failed with exit code $code." }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is missing. Install Docker Desktop and Compose v2."
}
Invoke-Docker -DockerArguments @("compose", "version")
Invoke-Docker -DockerArguments @("info")
if (-not (Test-Path ".env")) {
    if (-not (Test-Path ".env.example")) {
        throw "Missing .env.example; restore the source template before setup."
    }
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example; existing configurations are preserved."
}
Invoke-Docker -DockerArguments @("compose", "config", "--quiet")
Invoke-Docker -DockerArguments @("compose", "build")
Invoke-Docker -DockerArguments @("compose", "up", "-d", "--wait", "--wait-timeout", "90")
Write-Host "Ready: http://127.0.0.1:8000"
Write-Host "Open this address in your browser. No login password is needed for personal local use."
