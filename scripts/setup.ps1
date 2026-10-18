# Windows PowerShell operator setup for the loopback Docker deployment.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "Docker is required."
}

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Wrote .env from .env.example. Review the limits before large jobs."
}

docker compose build
docker compose up -d
Write-Host "Open http://127.0.0.1:8000"
Write-Host "Set the password in a terminal when ALLOW_HTTP_BOOTSTRAP=0:"
Write-Host "  docker compose exec -it app python -m app.cli bootstrap"
