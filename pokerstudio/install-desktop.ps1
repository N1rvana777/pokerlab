param(
    [string]$DesktopPath = [Environment]::GetFolderPath('DesktopDirectory'),
    [string]$PythonPath
)
$ErrorActionPreference = 'Stop'
$workspacePath = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) {
    $PythonPath = (& python -c "import sys; print(sys.executable)").Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot find the Python used by Pokerstudio.' }
}
$pythonwPath = Join-Path (Split-Path -Parent $PythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwPath -PathType Leaf)) { throw "Missing pythonw.exe: $pythonwPath" }
if (-not (Test-Path -LiteralPath $DesktopPath -PathType Container)) { throw "Desktop folder not found: $DesktopPath" }
$desktopAbsolute = (Resolve-Path -LiteralPath $DesktopPath).Path
$shell = New-Object -ComObject WScript.Shell
$definitions = @(
    @{ Name = 'Pokerstudio'; App = 'pokerstudio'; Icon = 'pokerstudio.ico'; Description = 'Pokerstudio - local video editing and poker analysis' },
    @{ Name = 'Pokerlab Solver'; App = 'pokerlab'; Icon = 'pokerlab.ico'; Description = 'Pokerlab Solver - local postflop research workbench' }
)
# Validate all destinations before writing either shortcut.
foreach ($item in $definitions) {
    $iconPath = Join-Path $PSScriptRoot ('desktop-assets/' + $item.Icon)
    if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) { throw "Missing icon: $iconPath" }
    $shortcutPath = Join-Path $desktopAbsolute ($item.Name + '.lnk')
    if (Test-Path -LiteralPath $shortcutPath) {
        $existing = $shell.CreateShortcut($shortcutPath)
        if ($existing.WorkingDirectory -ne $workspacePath -or $existing.Arguments -notmatch 'pokerstudio\.desktop --app ') {
            throw "An unrelated shortcut already exists; it was not changed: $shortcutPath"
        }
    }
}
foreach ($item in $definitions) {
    $shortcutPath = Join-Path $desktopAbsolute ($item.Name + '.lnk')
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $pythonwPath
    $shortcut.Arguments = '-X utf8 -m pokerstudio.desktop --app ' + $item.App
    $shortcut.WorkingDirectory = $workspacePath
    $shortcut.IconLocation = (Join-Path $PSScriptRoot ('desktop-assets/' + $item.Icon)) + ',0'
    $shortcut.Description = $item.Description
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    $verified = $shell.CreateShortcut($shortcutPath)
    [PSCustomObject]@{
        Shortcut = $shortcutPath
        Target = $verified.TargetPath
        Arguments = $verified.Arguments
        WorkingDirectory = $verified.WorkingDirectory
        Icon = $verified.IconLocation
    }
}
