#requires -Version 5.1

[CmdletBinding()]
param(
    [ValidateSet('menu', 'install', 'status', 'uninstall', 'verify')]
    [string]$Action = 'menu',
    [string]$Source,
    [switch]$DryRun,
    [string]$RepoRoot,
    [string[]]$Pack,
    [string]$BundleRef = 'v1.4.246-todo.1',
    [string]$BundleUrl = '',
    [string]$BundleManifestSha256 = '50fc1f15c3f26688df6fa46c022aa91015b4d32a1f512728a10cb444dd8695f9',
    [string]$BundleArchiveSha256 = '',
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
$script:BootstrapTempRoot = $null

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

function Resolve-BundleArchiveUrl {
    if ($BundleUrl) {
        return $BundleUrl
    }
    # Preserve TLS 1.3 when supported; older Windows PowerShell needs TLS 1.2 added.
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    if ($BundleRef -match '^[0-9a-f]{40}$') {
        return "https://codeload.github.com/realyasster/orca-advanced-orchestration/zip/$BundleRef"
    }
    try {
        $api = "https://api.github.com/repos/realyasster/orca-advanced-orchestration/commits/$BundleRef"
        $response = Invoke-RestMethod -UseBasicParsing -Headers @{
            'User-Agent' = 'orca-advanced-orchestration-installer'
        } -Uri $api
        $commit = [string]$response.sha
        if ($commit -notmatch '^[0-9a-f]{40}$') {
            throw "GitHub commit kimliği geçersiz: $commit"
        }
        return "https://github.com/realyasster/orca-advanced-orchestration/archive/$commit.zip"
    }
    catch {
        $status = 0
        try { $status = [int]$_.Exception.Response.StatusCode } catch { $status = 0 }
        if ($status -eq 403 -or $status -eq 429) {
            Write-Warn "GitHub API sınırına takıldı; '$BundleRef' referansı doğrudan arşivden indirilecek."
            return "https://codeload.github.com/realyasster/orca-advanced-orchestration/zip/$BundleRef"
        }
        throw "Paket referansı '$BundleRef' sabit commit'e çözümlenemedi. -BundleUrl ve -BundleManifestSha256 ile açık bir arşiv verin. Ayrıntı: $($_.Exception.Message)"
    }
}

function Install-BundleArchive {
    if ($script:ResolvedRepoRoot) {
        return
    }
    $url = Resolve-BundleArchiveUrl
    $temp = Join-Path ([System.IO.Path]::GetTempPath()) ("orca-ao-bundle-" + [guid]::NewGuid().ToString('N'))
    $script:BootstrapTempRoot = $temp
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    $archive = Join-Path $temp 'bundle.zip'
    Write-Host "Paket deposu yerelde yok; indiriliyor: $url" -ForegroundColor DarkGray
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive
    if ($BundleArchiveSha256) {
        $archiveActual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($archiveActual -ne $BundleArchiveSha256.ToLowerInvariant()) {
            throw "Paket arşivi hash'i eşleşmedi. Beklenen: $BundleArchiveSha256, gelen: $archiveActual"
        }
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $temp -Force
    $candidate = $null
    if (Test-RepoRoot $temp) {
        $candidate = Get-Item -LiteralPath $temp
    }
    else {
        $candidate = Get-ChildItem -LiteralPath $temp -Directory |
            Where-Object { Test-RepoRoot $_.FullName } |
            Select-Object -First 1
    }
    if ($null -eq $candidate) {
        throw "İndirilen arşivde bundle-manifest.json bulunamadı: $url"
    }
    if (-not $BundleManifestSha256) {
        throw 'Bootstrap için -BundleManifestSha256 zorunludur.'
    }
    $manifestFile = Join-Path $candidate.FullName 'bundle-manifest.json'
    $actual = (Get-FileHash -LiteralPath $manifestFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $BundleManifestSha256.ToLowerInvariant()) {
        throw "Paket manifest hash'i eşleşmedi. Beklenen: $BundleManifestSha256, gelen: $actual"
    }
    $manifestData = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
    $bootstrapHashes = $manifestData.bootstrap
    if ($null -eq $bootstrapHashes) {
        throw 'İndirilen manifest bootstrap script hash listesini içermiyor.'
    }
    foreach ($property in $bootstrapHashes.PSObject.Properties) {
        $relative = $property.Name -replace '/', [System.IO.Path]::DirectorySeparatorChar
        $scriptFile = Join-Path $candidate.FullName $relative
        if (-not (Test-Path -LiteralPath $scriptFile -PathType Leaf)) {
            throw "Bootstrap dosyası eksik: $($property.Name)"
        }
        if ($property.Name -eq 'install.ps1') {
            # The manifest hash line is self-referential; normalize it before hashing.
            $text = [System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($scriptFile))
            if ($text.Length -gt 0 -and [int][char]$text[0] -eq 0xFEFF) {
                $text = $text.Substring(1)
            }
            $normalized = [regex]::Replace(
                $text,
                "(BundleManifestSha256 = ')[0-9a-f]{64}(')",
                ('${1}' + ('0' * 64) + '${2}')
            )
            $sha = [System.Security.Cryptography.SHA256]::Create()
            try {
                $scriptActual = (
                    [System.BitConverter]::ToString(
                        $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($normalized))
                    ) -replace '-', ''
                ).ToLowerInvariant()
            }
            finally {
                $sha.Dispose()
            }
        }
        else {
            $scriptActual = (Get-FileHash -LiteralPath $scriptFile -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $scriptExpected = ([string]$property.Value).ToLowerInvariant()
        if ($scriptActual -ne $scriptExpected) {
            throw "Bootstrap dosyası hash'i eşleşmedi: $($property.Name)"
        }
    }
    $script:ResolvedRepoRoot = (Resolve-Path -LiteralPath $candidate.FullName).Path
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

    if (-not $RepoRoot) {
        Install-BundleArchive
        return $script:ResolvedRepoRoot
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

function Get-PackCatalog {
    $repo = Resolve-RepoRoot
    $manifestPath = Join-Path $repo 'bundle-manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    return @($manifest.packs)
}

function Select-Packs {
    $packs = @(Get-PackCatalog)
    if ($packs.Count -eq 0) {
        return @()
    }
    $selected = @{}
    foreach ($pack in $packs) {
        $selected[$pack.id] = $true
    }
    while ($true) {
        Write-Host ''
        Write-Host 'Kurulacak bileşenler:' -ForegroundColor Cyan
        for ($index = 0; $index -lt $packs.Count; $index++) {
            $pack = $packs[$index]
            $mark = ' '
            if ($selected[$pack.id]) {
                $mark = 'x'
            }
            Write-Host ("  [{0}] {1}) {2}" -f $mark, ($index + 1), $pack.label)
            Write-Host ("       {0}" -f $pack.description) -ForegroundColor DarkGray
        }
        Write-Host ''
        $answer = Read-Host 'Seçim [Enter=kur, A=tümü, N=hiçbiri, Q=iptal]'
        if ($null -eq $answer) {
            throw 'İşlem iptal edildi.'
        }
        $answer = $answer.Trim()
        if ($answer -eq '') {
            $chosen = @($packs | Where-Object { $selected[$_.id] } | ForEach-Object { $_.id })
            if ($chosen.Count -eq 0) {
                Write-Warn 'En az bir bileşen seçin.'
                continue
            }
            return $chosen
        }
        if ($answer -match '^(a|all|tümü|tumu)$') {
            foreach ($pack in $packs) { $selected[$pack.id] = $true }
            continue
        }
        if ($answer -match '^(n|none|hiçbiri|hicbiri)$') {
            foreach ($pack in $packs) { $selected[$pack.id] = $false }
            continue
        }
        if ($answer -match '^(q|quit|çık|çıkış|cikis)$') {
            throw 'İşlem iptal edildi.'
        }
        $number = 0
        if ([int]::TryParse($answer, [ref]$number) -and $number -ge 1 -and $number -le $packs.Count) {
            $pack = $packs[$number - 1]
            $selected[$pack.id] = -not $selected[$pack.id]
            continue
        }
        Write-Warn "Geçersiz seçim: $answer"
    }
}

function Expand-PackValues {
    param([string[]]$Values)
    return @(
        $Values |
            ForEach-Object { $_ -split ',' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    )
}

function Invoke-InstallAction {
    param(
        [switch]$DryRun,
        [switch]$SelectPacks
    )
    Assert-Git
    $source = Resolve-Source
    $arguments = @('install', '--source', $source)
    $chosenPacks = @()
    if ($Pack) {
        $chosenPacks = Expand-PackValues -Values $Pack
    }
    elseif ($SelectPacks -and -not $NoPause -and -not [Console]::IsInputRedirected) {
        $chosenPacks = @(Select-Packs)
    }
    elseif ($SelectPacks) {
        Write-Warn 'Bileşen seçimi atlandı (etkileşimsiz oturum); tüm pack''ler kurulacak.'
    }
    foreach ($packId in $chosenPacks) {
        $arguments += @('--pack', $packId)
    }
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

function Confirm-Uninstall {
    $answer = Read-Host 'Kaldırmak istediğinizden emin misiniz? (e/H)'
    if ($null -eq $answer) {
        return $false
    }
    return $answer.Trim() -match '^(e|evet|y|yes)$'
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
        Write-Host '  1) Kur (bileşen seçimiyle)'
        Write-Host '  2) Durum'
        Write-Host '  3) Kaldır'
        Write-Host '  4) Kurulum provası (bileşen seçimiyle)'
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
                '1' { $code = Invoke-InstallAction -SelectPacks }
                '2' { $code = Invoke-StatusAction }
                '3' {
                    if (Confirm-Uninstall) {
                        $code = Invoke-UninstallAction
                    }
                    else {
                        Write-Warn 'Kaldırma iptal edildi.'
                        $code = 0
                    }
                }
                '4' { $code = Invoke-InstallAction -DryRun -SelectPacks }
                '5' { $code = Invoke-UninstallAction -DryRun }
                '6' { $code = Invoke-VerifyAction }
                '7' {
                    $previousResolved = $script:ResolvedSource
                    $previousRequested = $script:RequestedSource
                    $script:ResolvedSource = $null
                    $script:RequestedSource = $null
                    try {
                        [void](Resolve-Source)
                        $code = 0
                    }
                    catch {
                        $script:ResolvedSource = $previousResolved
                        $script:RequestedSource = $previousRequested
                        Write-Warn "Kaynak yolu değiştirilmedi: $($_.Exception.Message)"
                        $code = 0
                    }
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
if ($script:BootstrapTempRoot -and (Test-Path -LiteralPath $script:BootstrapTempRoot)) {
    Remove-Item -LiteralPath $script:BootstrapTempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
if ($script:ScriptPath) {
    exit $exitCode
}
$global:LASTEXITCODE = $exitCode
