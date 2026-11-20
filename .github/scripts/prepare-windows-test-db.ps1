param([switch]$WithVector)
$ErrorActionPreference = 'Stop'
$pgroot = $env:PGROOT
if (-not $pgroot) { $pgroot = 'C:\Program Files\PostgreSQL\17' }
$pgbin = Join-Path $pgroot 'bin'
if (-not (Test-Path (Join-Path $pgbin 'initdb.exe'))) { throw 'Hosted Windows PostgreSQL 17 tools are missing.' }
if ($WithVector) {
  $vector = Join-Path $env:RUNNER_TEMP 'townlight-test-pgvector'
  git clone --depth 1 --branch v0.8.2 https://github.com/pgvector/pgvector.git $vector
  if ($LASTEXITCODE -ne 0) { throw 'pgvector source checkout failed.' }
  $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
  $vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
  $devcmd = Join-Path $vs 'Common7\Tools\VsDevCmd.bat'
  if (-not (Test-Path $devcmd)) { throw 'Hosted MSVC build tools are missing.' }
  Push-Location $vector
  try {
    $command = 'call "' + $devcmd + '" -arch=x64 -host_arch=x64 >nul && set "PGROOT=' + $pgroot + '" && nmake /F Makefile.win && nmake /F Makefile.win install'
    & cmd.exe /d /s /c $command
    if ($LASTEXITCODE -ne 0) { throw 'Windows pgvector build/install failed.' }
  } finally { Pop-Location }
}
$cluster = Join-Path $env:RUNNER_TEMP 'townlight-test-pg'
$password = [Guid]::NewGuid().ToString('N')
Write-Output "::add-mask::$password"
$pwfile = Join-Path $env:RUNNER_TEMP 'townlight-test-pg-password'
[IO.File]::WriteAllText($pwfile, $password)
try {
  & "$pgbin\initdb.exe" -D $cluster -U postgres --auth=scram-sha-256 --pwfile=$pwfile --encoding=UTF8
  if ($LASTEXITCODE -ne 0) { throw 'Private test cluster initialization failed.' }
} finally { Remove-Item -LiteralPath $pwfile -Force }
& "$pgbin\pg_ctl.exe" -D $cluster -l (Join-Path $env:RUNNER_TEMP 'townlight-test-pg.log') -o '-h 127.0.0.1 -p 55439' -w start
if ($LASTEXITCODE -ne 0) { throw 'Private loopback test cluster failed to start.' }
$env:PGPASSWORD = $password
& "$pgbin\createdb.exe" -h 127.0.0.1 -p 55439 -U postgres planning_p1p2_test
if ($LASTEXITCODE -ne 0) { throw 'Private test database creation failed.' }
"DATABASE_URL=postgresql+asyncpg://postgres:$password@127.0.0.1:55439/postgres" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
"PLANNING_TEST_DATABASE_URL=postgresql+psycopg2://postgres:$password@127.0.0.1:55439/planning_p1p2_test" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
