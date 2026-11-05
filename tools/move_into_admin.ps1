# One time: move PrintRouter (the whole folder, with its git history) into an ADMIN subfolder
# and leave only a PrintRouter shortcut in the top folder. Started by "Move into ADMIN folder.bat".
# Safe to run again: it only moves what is still in the top folder.
param([Parameter(Mandatory = $true)][string]$Root)

$root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
if ((Split-Path $root -Leaf) -ieq 'ADMIN') { $root = Split-Path $root -Parent }  # started from inside ADMIN
$admin = Join-Path $root 'ADMIN'
$link = Join-Path $root 'PrintRouter.lnk'
$oldBat = Join-Path $root 'PrintRouter.bat'
$newBat = Join-Path $admin 'PrintRouter.bat'

Write-Host "=== Move PrintRouter into $admin ==="
Write-Host ""

# PrintRouter must be closed: Windows can't move a folder the app is using.
$open = Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match '^(pythonw?|pyw?)\.exe$' -and $_.CommandLine -match 'app\.py' }
if ($open) {
    Write-Host "PrintRouter is open. Close its window, then run this again."
    exit 1
}

New-Item -ItemType Directory -Force -Path $admin | Out-Null
$failed = @()
foreach ($item in Get-ChildItem -LiteralPath $root -Force) {
    if ($item.Name -ieq 'ADMIN' -or $item.Name -ieq 'PrintRouter.lnk') { continue }
    $dest = Join-Path $admin $item.Name
    if (Test-Path -LiteralPath $dest) {
        $failed += "$($item.Name): there is already one in ADMIN"
        continue
    }
    try {
        Move-Item -LiteralPath $item.FullName -Destination $dest -ErrorAction Stop
    } catch {
        $failed += "$($item.Name): $($_.Exception.Message)"
    }
}

if (-not (Test-Path -LiteralPath $newBat)) {
    Write-Host "PrintRouter.bat is not in ADMIN. Nothing else was changed."
    $failed | ForEach-Object { Write-Host "  - $_" }
    exit 1
}

# The shortcut in the top folder.
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($link)
$s.TargetPath = $newBat
$s.WorkingDirectory = $admin
$s.Description = 'Open PrintRouter'
$s.Save()
Write-Host "Made the shortcut: $link"

# Shortcuts that opened the old PrintRouter.bat (desktop, Start menu, startup) now open the new one.
# Only the top of each place (desktops can hold huge folders); the Start menu two levels deep.
$shortcuts = @()
foreach ($place in @('Desktop', 'CommonDesktopDirectory', 'Startup', 'CommonStartup')) {
    $dir = [Environment]::GetFolderPath($place)
    if ($dir -and (Test-Path -LiteralPath $dir)) {
        $shortcuts += Get-ChildItem -LiteralPath $dir -Filter *.lnk -Force -ErrorAction SilentlyContinue
    }
}
foreach ($place in @('Programs', 'CommonPrograms')) {
    $dir = [Environment]::GetFolderPath($place)
    if ($dir -and (Test-Path -LiteralPath $dir)) {
        $shortcuts += Get-ChildItem -LiteralPath $dir -Filter *.lnk -Force -ErrorAction SilentlyContinue
        foreach ($sub in Get-ChildItem -LiteralPath $dir -Directory -Force -ErrorAction SilentlyContinue) {
            $shortcuts += Get-ChildItem -LiteralPath $sub.FullName -Filter *.lnk -Force -ErrorAction SilentlyContinue
        }
    }
}
foreach ($file in $shortcuts) {
    if ($true) {
        try {
            $old = $shell.CreateShortcut($file.FullName)
            if ($old.TargetPath -ieq $oldBat) {
                $old.TargetPath = $newBat
                $old.WorkingDirectory = $admin
                $old.Save()
                Write-Host "Updated the shortcut: $($file.FullName)"
            }
        } catch {
            Write-Host "Could not update the shortcut $($file.FullName): open its Properties and point it to $newBat"
        }
    }
}

# Git still works in its new place?
if (Get-Command git -ErrorAction SilentlyContinue) {
    $inside = & git -C $admin rev-parse --is-inside-work-tree 2>$null
    if ($inside -eq 'true') { Write-Host "Updates from GitHub: OK" } else { Write-Host "Updates from GitHub: NOT working (.git missing in ADMIN)" }
}

Write-Host ""
if ($failed) {
    Write-Host "Some things could not be moved (close any program or Explorer window using them, then run this again):"
    $failed | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host "Done. Open PrintRouter with the PrintRouter shortcut in $root."
exit 0
