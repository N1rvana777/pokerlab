$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$revision = git -C third_party/postflop-solver rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $revision -ne '9d1509fe5077d019825f833eed04b16d342dfda1') {
    throw 'Engine checkout is missing or differs from pinned revision. See README.'
}
python scripts/verify_engine.py
if ($LASTEXITCODE -ne 0) { throw 'Engine differs from documented patch.' }
if (Get-Command cargo -ErrorAction SilentlyContinue) {
    $previousRustFlags = $env:RUSTFLAGS
    try {
        $env:RUSTFLAGS = '-C target-cpu=native'
        cargo build --release --locked
    } finally { $env:RUSTFLAGS = $previousRustFlags }
} else {
    $workspace = (Get-Location).Path.Replace('\','/')
    $linuxWorkspace = '/mnt/' + $workspace.Substring(0,1).ToLower() + $workspace.Substring(2)
    wsl -d Ubuntu --cd $linuxWorkspace -- env 'RUSTFLAGS=-C target-cpu=native' cargo build --release --locked
}
if ($LASTEXITCODE -ne 0) { throw 'Native build failed' }
