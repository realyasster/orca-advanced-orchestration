#requires -Version 5.1

[CmdletBinding()]
param(
    [ValidateSet('menu', 'install', 'status', 'uninstall', 'verify')]
    [string]$Action = 'menu',
    [string]$Source,
    [switch]$DryRun,
    [string]$RepoRoot,
    [switch]$NoPause
)

$OrcaCloneCommand = 'git clone --branch v1.4.246 --depth 1 https://github.com/stablyai/orca.git'
$script:ScriptPath = $PSCommandPath
if (-not $script:ScriptPath) {
    $script:ScriptPath = $MyInvocation.MyCommand.Path
}
$script:ResolvedRepoRoot = $null
$script:ResolvedSource = $null
$script:RequestedSource = $Source
$script:Python = $null

function Write-Warn {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Red
}

function Test-RepoRoot {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $false
    }
    $manage = Join-Path (Join-Path $Path 'scripts') 'manage_installation.py'
    $manifest = Join-Path $Path 'bundle-manifest.json'
    return (Test-Path -LiteralPath $manage -PathType Leaf) -and
        (Test-Path -LiteralPath $manifest -PathType Leaf)
}

function Resolve-RepoRoot {
    if ($script:ResolvedRepoRoot) {
        return $script:ResolvedRepoRoot
    }

    $candidates = @()
    if ($RepoRoot) {
        $candidates += $RepoRoot
    }
    if ($script:ScriptPath) {
        $candidates += (Split-Path -Parent $script:ScriptPath)
    }
    $candidates += (Get-Location).Path

    foreach ($candidate in $candidates) {
        if (Test-RepoRoot $candidate) {
            $script:ResolvedRepoRoot = (Resolve-Path -LiteralPath $candidate).Path
            return $script:ResolvedRepoRoot
        }
    }

    throw "Paket deposu bulunamadı. Bu script'i depo kökünden çalıştırın: cd orca-advanced-orchestration"
}

function Resolve-Python {
    if ($script:Python) {
        return $script:Python
    }

    $candidates = @(
        @{ Exe = 'py'; Prefix = @('-3') },
        @{ Exe = 'python'; Prefix = @() },
        @{ Exe = 'python3'; Prefix = @() }
    )
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
        if (-not $command) {
            continue
        }
        $probe = @($candidate.Prefix) + @(
            '-c',
            'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'
        )
        & $candidate.Exe @probe 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $script:Python = $candidate
            return $script:Python
        }
    }

    throw "Python 3.9+ bulunamadı. Python'u kurup PATH'e ekleyin: https://www.python.org/downloads/"
}

function Assert-Git {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git bulunamadı. Git kurup PATH'e ekleyin: https://git-scm.com/downloads"
    }
}

function Invoke-PythonFile {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments = @()
    )
    $python = Resolve-Python
    $all = @($python.Prefix) + @($ScriptPath) + @($Arguments)
    & $python.Exe @all | Out-Host
    return $LASTEXITCODE
}

function Invoke-Manage {
    param([string[]]$Arguments)
    $repo = Resolve-RepoRoot
    $scriptPath = Join-Path (Join-Path $repo 'scripts') 'manage_installation.py'
    return Invoke-PythonFile -ScriptPath $scriptPath -Arguments $Arguments
}

function Resolve-Source {
    if ($script:ResolvedSource) {
        return $script:ResolvedSource
    }

    if ($script:RequestedSource) {
        if (-not (Test-Path -LiteralPath $script:RequestedSource -PathType Container)) {
            throw "Orca kaynak checkout'u bulunamadı: $($script:RequestedSource)`n$OrcaCloneCommand `"$($script:RequestedSource)`""
        }
        $script:ResolvedSource = (Resolve-Path -LiteralPath $script:RequestedSource).Path
        return $script:ResolvedSource
    }

    $repo = Resolve-RepoRoot
    $default = Join-Path (Split-Path -Parent $repo) 'orca-dev'
    $candidates = @($default)
    if ($HOME) {
        $candidates += (Join-Path $HOME 'orca-dev')
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            $script:ResolvedSource = (Resolve-Path -LiteralPath $candidate).Path
            return $script:ResolvedSource
        }
    }

    Write-Warn "Orca kaynak checkout'u bulunamadı."
    Write-Host 'Örnek klonlama:'
    Write-Host "  $OrcaCloneCommand `"$default`""
    while ($true) {
        $entered = Read-Host "Orca kaynak yolu [$default] (çıkmak için q)"
        if ($null -eq $entered) {
            throw 'İşlem iptal edildi.'
        }
        $entered = $entered.Trim()
        if ($entered -eq 'q' -or $entered -eq 'Q') {
            throw 'İşlem iptal edildi.'
        }
        if ([string]::IsNullOrWhiteSpace($entered)) {
            $entered = $default
        }
        if (Test-Path -LiteralPath $entered -PathType Container) {
            $script:ResolvedSource = (Resolve-Path -LiteralPath $entered).Path
            return $script:ResolvedSource
        }
        Write-Warn "Dizin bulunamadı: $entered"
        Write-Host 'Önce klonlayın:'
        Write-Host "  $OrcaCloneCommand `"$entered`""
    }
}

function Invoke-InstallAction {
    param([switch]$DryRun)
    Assert-Git
    $source = Resolve-Source
    $arguments = @('install', '--source', $source)
    if ($DryRun) {
        $arguments += '--dry-run'
    }
    $code = Invoke-Manage -Arguments $arguments
    if ($code -eq 0) {
        if ($DryRun) {
            Write-Host 'Kurulum provası tamamlandı; hiçbir dosya değiştirilmedi.' -ForegroundColor Green
        }
        else {
            Write-Host 'Kurulum tamamlandı.' -ForegroundColor Green
            Write-Host "Sonraki adım: $source içinde"
            Write-Host '  pnpm install --frozen-lockfile'
            Write-Host '  pnpm build'
        }
    }
    return $code
}

function Invoke-StatusAction {
    Assert-Git
    $source = Resolve-Source
    return Invoke-Manage -Arguments @('status', '--source', $source)
}

function Invoke-UninstallAction {
    param([switch]$DryRun)
    Assert-Git
    $source = Resolve-Source
    $arguments = @('uninstall', '--source', $source)
    if ($DryRun) {
        $arguments += '--dry-run'
    }
    return Invoke-Manage -Arguments $arguments
}

function Invoke-VerifyAction {
    $repo = Resolve-RepoRoot
    $scriptPath = Join-Path (Join-Path $repo 'scripts') 'verify_bundle.py'
    $code = Invoke-PythonFile -ScriptPath $scriptPath
    if ($code -eq 0) {
        Write-Host 'Paket doğrulandı.' -ForegroundColor Green
    }
    return $code
}

function Show-Menu {
    while ($true) {
        $sourceLabel = '(kurulumda sorulacak)'
        if ($script:ResolvedSource) {
            $sourceLabel = $script:ResolvedSource
        }
        elseif ($script:RequestedSource) {
            $sourceLabel = $script:RequestedSource
        }

        Write-Host ''
        Write-Host 'Orca Advanced Orchestration' -ForegroundColor Cyan
        Write-Host "Paket: $(Resolve-RepoRoot)"
        Write-Host "Orca:  $sourceLabel"
        Write-Host ''
        Write-Host '  1) Kur'
        Write-Host '  2) Durum'
        Write-Host '  3) Kaldır'
        Write-Host '  4) Kurulum provası (dry-run)'
        Write-Host '  5) Kaldırma provası (dry-run)'
        Write-Host '  6) Paketi doğrula'
        Write-Host '  7) Orca kaynak yolunu değiştir'
        Write-Host '  0) Çıkış'
        Write-Host ''

        $choice = Read-Host 'Seçim'
        if ($null -eq $choice) {
            return 1
        }
        $choice = $choice.Trim()
        if ($choice -eq '0') {
            return 0
        }

        $code = 0
        try {
            switch ($choice) {
                '1' { $code = Invoke-InstallAction }
                '2' { $code = Invoke-StatusAction }
                '3' { $code = Invoke-UninstallAction }
                '4' { $code = Invoke-InstallAction -DryRun }
                '5' { $code = Invoke-UninstallAction -DryRun }
                '6' { $code = Invoke-VerifyAction }
                '7' {
                    $script:ResolvedSource = $null
                    $script:RequestedSource = $null
                    [void](Resolve-Source)
                    $code = 0
                }
                default {
                    Write-Warn "Geçersiz seçim: $choice"
                }
            }
        }
        catch {
            Write-Err "Hata: $($_.Exception.Message)"
            $code = 1
        }

        if ($code -ne 0) {
            Write-Err "İşlem başarısız (kod $code)."
        }
        if (-not $NoPause) {
            [void](Read-Host 'Devam etmek için Enter')
        }
    }
}

function Invoke-Main {
    [void](Resolve-RepoRoot)

    if ($Action -eq 'menu') {
        return Show-Menu
    }
    if ($DryRun -and $Action -ne 'install' -and $Action -ne 'uninstall') {
        Write-Warn '-DryRun yalnızca install ve uninstall için kullanılır; yok sayıldı.'
    }

    switch ($Action) {
        'verify' { return Invoke-VerifyAction }
        'install' { return Invoke-InstallAction -DryRun:$DryRun }
        'status' { return Invoke-StatusAction }
        'uninstall' { return Invoke-UninstallAction -DryRun:$DryRun }
    }
    return 2
}

$exitCode = 0
try {
    $exitCode = Invoke-Main
    if ($null -eq $exitCode) {
        $exitCode = 0
    }
}
catch {
    Write-Err "Hata: $($_.Exception.Message)"
    $exitCode = 1
}

$exitCode = [int]$exitCode
if ($script:ScriptPath) {
    exit $exitCode
}
$global:LASTEXITCODE = $exitCode
