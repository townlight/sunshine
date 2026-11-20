# Townlight Records - supported Windows installation
# Records is included in the Townlight Windows MSI; Docker Desktop is not required.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Write-Output 'Download the signed Townlight Windows installer:'
Write-Output 'https://github.com/townlight/townlight/releases/latest'
Write-Output 'Choose the Windows x64 MSI and follow the Suite manual:'
Write-Output 'https://townlight.github.io/manuals/suite.html'
Write-Output 'The standalone Docker deployment is an alternative for administrators; see docker-compose.yml and its documentation.'
