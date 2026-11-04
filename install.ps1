# Orca Advanced Orchestration installer. Safe to run through irm ... | iex.
param(
    [ValidateSet('menu', 'install', 'update', 'uninstall', 'status', 'verify')]
    [string]$Action = 'menu',
    [string]$Source,
    [string]$Version,
    [switch]$DryRun,
    [string]$RepoRoot,
    [switch]$NoPause
)

if ($PSVersionTable.PSVersion.Major -lt 5 -or
    ($PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -lt 1)) {
    throw 'PowerShell 5.1 veya daha yeni bir surum gerekir.'
}

$ErrorActionPreference = 'Stop'

$script:Repository = 'realyasster/orca-advanced-orchestration'
$script:OrcaRepository = 'https://github.com/stablyai/orca'
$script:AssetPrefix = 'orca-advanced-orchestration'
$script:ScriptPath = $PSCommandPath
if (-not $script:ScriptPath) {
    $script:ScriptPath = $MyInvocation.MyCommand.Path
}
$script:HasScriptPath = -not [string]::IsNullOrWhiteSpace($script:ScriptPath)
$script:PromptAllowed = ($Action -eq 'menu')
$script:Python = $null
$script:LocalBundleRoot = $null
$script:ResolvedSource = $null
$script:ResolvedVersion = $null
$script:ResolvedPackage = $null
$script:LatestVersion = $null
$script:LatestVersionTried = $false

if ($env:LOCALAPPDATA) {
    $script:CacheRoot = Join-Path $env:LOCALAPPDATA 'OrcaAdvancedOrchestration'
}
elseif ($HOME) {
    $script:CacheRoot = Join-Path $HOME '.local/share/OrcaAdvancedOrchestration'
}
else {
    $script:CacheRoot = Join-Path $env:TEMP 'OrcaAdvancedOrchestration'
}
$script:PackagesRoot = Join-Path $script:CacheRoot 'packages'
$script:DownloadsRoot = Join-Path $script:CacheRoot 'downloads'
$script:ConfigPath = Join-Path $script:CacheRoot 'config.json'

try {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
}
catch {
    # Older/newer runtimes may already enforce TLS or reject the enum.
}

function Write-Warn {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Red
}

function Write-Ok {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Cyan
}

function Test-LocalBundleRoot {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $false
    }
    return (Test-Path -LiteralPath (Join-Path $Path 'bundle-manifest.json') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path (Join-Path $Path 'scripts') 'manage_installation.py') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path (Join-Path $Path 'scripts') 'verify_bundle.py') -PathType Leaf)
}

function Find-LocalBundleRoot {
    $candidates = @()
    if ($RepoRoot) {
        $candidates += $RepoRoot
    }
    if ($script:ScriptPath) {
        $candidates += (Split-Path -Parent $script:ScriptPath)
    }
    $candidates += (Get-Location).Path
    foreach ($candidate in $candidates) {
        if (Test-LocalBundleRoot $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Read-Config {
    $config = @{}
    if (Test-Path -LiteralPath $script:ConfigPath -PathType Leaf) {
        try {
            $raw = Get-Content -LiteralPath $script:ConfigPath -Raw -ErrorAction Stop
            $parsed = $raw | ConvertFrom-Json
            if ($parsed -and $parsed.source) {
                $config['source'] = [string]$parsed.source
            }
        }
        catch {
            Write-Warn "Ayar dosyasi okunamadi, yok sayiliyor: $($script:ConfigPath)"
        }
    }
    return $config
}

function Save-ConfigSource {
    param([string]$Path)
    New-Item -ItemType Directory -Force -Path $script:CacheRoot | Out-Null
    $payload = [ordered]@{ source = $Path }
    $payload | ConvertTo-Json | Set-Content -LiteralPath $script:ConfigPath -Encoding UTF8
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
        $probeExit = 1
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $candidate.Exe @probe 2>$null | Out-Null
            $probeExit = $LASTEXITCODE
        }
        catch {
            $probeExit = 1
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($probeExit -eq 0) {
            $script:Python = $candidate
            return $script:Python
        }
    }
    throw "Python 3.9+ bulunamadi. Python'u kurup PATH'e ekleyin: https://www.python.org/downloads/"
}

function Assert-Git {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git bulunamadi. Git kurup PATH'e ekleyin: https://git-scm.com/downloads"
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
    param(
        [string]$PackageRoot,
        [string[]]$Arguments
    )
    $scriptPath = Join-Path (Join-Path $PackageRoot 'scripts') 'manage_installation.py'
    return Invoke-PythonFile -ScriptPath $scriptPath -Arguments $Arguments
}

function Invoke-VerifyBundle {
    param([string]$PackageRoot)
    $scriptPath = Join-Path (Join-Path $PackageRoot 'scripts') 'verify_bundle.py'
    return Invoke-PythonFile -ScriptPath $scriptPath
}

function Get-Manifest {
    param([string]$PackageRoot)
    $path = Join-Path $PackageRoot 'bundle-manifest.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Paket manifesti bulunamadi: $path"
    }
    return (Get-Content -LiteralPath $path -Raw | ConvertFrom-Json)
}

function Get-PackageVersion {
    param([string]$PackageRoot)
    $manifest = Get-Manifest $PackageRoot
    if (-not $manifest.package -or -not $manifest.package.version) {
        throw "Paket manifestinde package.version alani yok: $PackageRoot"
    }
    return [string]$manifest.package.version
}

function Normalize-Version {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }
    $trimmed = $Value.Trim()
    if ($trimmed.StartsWith('v') -or $trimmed.StartsWith('V')) {
        $trimmed = $trimmed.Substring(1)
    }
    if ($trimmed -notmatch '^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$') {
        throw "Gecersiz surum: $Value (orn. 1.0.0 veya v1.0.0)"
    }
    return $trimmed
}

function Compare-VersionValue {
    param([string]$Left, [string]$Right)
    $leftValue = $Left.Split('+')[0]
    $rightValue = $Right.Split('+')[0]
    $leftDash = $leftValue.IndexOf('-')
    $rightDash = $rightValue.IndexOf('-')
    if ($leftDash -ge 0) {
        $leftCore = $leftValue.Substring(0, $leftDash)
        $leftPre = $leftValue.Substring($leftDash + 1)
    }
    else {
        $leftCore = $leftValue
        $leftPre = $null
    }
    if ($rightDash -ge 0) {
        $rightCore = $rightValue.Substring(0, $rightDash)
        $rightPre = $rightValue.Substring($rightDash + 1)
    }
    else {
        $rightCore = $rightValue
        $rightPre = $null
    }

    $leftParts = $leftCore.Split('.')
    $rightParts = $rightCore.Split('.')
    for ($index = 0; $index -lt 3; $index++) {
        $leftNumber = 0
        $rightNumber = 0
        if ($leftParts.Count -gt $index) { $leftNumber = [long]$leftParts[$index] }
        if ($rightParts.Count -gt $index) { $rightNumber = [long]$rightParts[$index] }
        if ($leftNumber -lt $rightNumber) { return -1 }
        if ($leftNumber -gt $rightNumber) { return 1 }
    }

    $leftHasPre = -not [string]::IsNullOrEmpty($leftPre)
    $rightHasPre = -not [string]::IsNullOrEmpty($rightPre)
    if ($leftHasPre -and -not $rightHasPre) { return -1 }
    if (-not $leftHasPre -and $rightHasPre) { return 1 }
    if (-not $leftHasPre -and -not $rightHasPre) { return 0 }

    $leftIdentifiers = $leftPre.Split('.')
    $rightIdentifiers = $rightPre.Split('.')
    $limit = [Math]::Max($leftIdentifiers.Count, $rightIdentifiers.Count)
    for ($index = 0; $index -lt $limit; $index++) {
        if ($index -ge $leftIdentifiers.Count) { return -1 }
        if ($index -ge $rightIdentifiers.Count) { return 1 }
        $leftIdentifier = [string]$leftIdentifiers[$index]
        $rightIdentifier = [string]$rightIdentifiers[$index]
        $leftNumeric = $leftIdentifier -match '^[0-9]+$'
        $rightNumeric = $rightIdentifier -match '^[0-9]+$'
        if ($leftNumeric -and $rightNumeric) {
            $leftNumber = [long]$leftIdentifier
            $rightNumber = [long]$rightIdentifier
            if ($leftNumber -lt $rightNumber) { return -1 }
            if ($leftNumber -gt $rightNumber) { return 1 }
        }
        elseif ($leftNumeric) {
            return -1
        }
        elseif ($rightNumeric) {
            return 1
        }
        else {
            $comparison = [string]::CompareOrdinal($leftIdentifier, $rightIdentifier)
            if ($comparison -lt 0) { return -1 }
            if ($comparison -gt 0) { return 1 }
        }
    }
    return 0
}

function Get-CachedVersions {
    $versions = @()
    if (-not (Test-Path -LiteralPath $script:PackagesRoot -PathType Container)) {
        return @()
    }
    foreach ($directory in Get-ChildItem -LiteralPath $script:PackagesRoot -Directory -ErrorAction SilentlyContinue) {
        if (Test-Path -LiteralPath (Join-Path $directory.FullName '.verified') -PathType Leaf) {
            $versions += $directory.Name
        }
    }
    return @($versions | Sort-Object { $_ } -Descending)
}

function Get-HighestCachedVersion {
    $versions = @(Get-CachedVersions)
    if ($versions.Count -eq 0) {
        return $null
    }
    $best = $versions[0]
    foreach ($candidate in $versions) {
        if ((Compare-VersionValue $candidate $best) -gt 0) {
            $best = $candidate
        }
    }
    return $best
}

function Find-CachedPackage {
    param([string]$PackageVersion)
    if ([string]::IsNullOrWhiteSpace($PackageVersion)) {
        return $null
    }
    $path = Join-Path $script:PackagesRoot $PackageVersion
    if ((Test-Path -LiteralPath (Join-Path $path '.verified') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path (Join-Path $path 'scripts') 'manage_installation.py') -PathType Leaf)) {
        return $path
    }
    return $null
}

function Invoke-WebRequestChecked {
    param(
        [string]$Uri,
        [string]$OutFile,
        [hashtable]$Headers = @{}
    )
    $parameters = @{
        Uri = $Uri
        OutFile = $OutFile
        Headers = $Headers
        TimeoutSec = 60
        ErrorAction = 'Stop'
    }
    if ($PSVersionTable.PSVersion.Major -lt 6) {
        $parameters['UseBasicParsing'] = $true
    }
    $previous = $ProgressPreference
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest @parameters | Out-Null
    }
    finally {
        $ProgressPreference = $previous
    }
}

function Get-LatestVersion {
    if ($script:LatestVersionTried) {
        return $script:LatestVersion
    }
    $script:LatestVersionTried = $true
    $headers = @{
        'User-Agent' = 'orca-advanced-orchestration-installer'
        'Accept' = 'application/vnd.github+json'
    }
    try {
        New-Item -ItemType Directory -Force -Path $script:DownloadsRoot | Out-Null
        $temp = Join-Path $script:DownloadsRoot ("latest-{0}.json" -f [guid]::NewGuid().ToString('N'))
        try {
            Invoke-WebRequestChecked -Uri "https://api.github.com/repos/$($script:Repository)/releases/latest" -OutFile $temp -Headers $headers
            $release = (Get-Content -LiteralPath $temp -Raw | ConvertFrom-Json)
            $tag = [string]$release.tag_name
            if ([string]::IsNullOrWhiteSpace($tag)) {
                throw 'GitHub yanitinda tag_name yok.'
            }
            $script:LatestVersion = Normalize-Version $tag
        }
        finally {
            if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
        }
    }
    catch {
        $cached = Get-HighestCachedVersion
        if ($cached) {
            Write-Warn "Son surum GitHub'dan alinamadi; onbellekteki $cached kullanilacak."
            $script:LatestVersion = $cached
        }
        else {
            throw "GitHub Release surumu alinamadi: $($_.Exception.Message). Henuz yayimlanmis release yoksa -Version ile onbellekteki bir surumu secin."
        }
    }
    return $script:LatestVersion
}

function Resolve-TargetVersion {
    if ($Version) {
        return Normalize-Version $Version
    }
    if ($script:ResolvedVersion) {
        return $script:ResolvedVersion
    }
    $script:ResolvedVersion = Get-LatestVersion
    return $script:ResolvedVersion
}

function Expand-PackageArchive {
    param(
        [string]$ArchivePath,
        [string]$Destination
    )
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop | Out-Null
    $rootFull = [IO.Path]::GetFullPath($Destination)
    $rootPrefix = $rootFull.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    New-Item -ItemType Directory -Force -Path $rootFull | Out-Null
    $archive = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        foreach ($entry in $archive.Entries) {
            $relative = ($entry.FullName -replace '\\', '/')
            if ([string]::IsNullOrWhiteSpace($relative)) {
                continue
            }
            if ($relative.StartsWith('/') -or $relative -match '^[A-Za-z]:' -or [IO.Path]::IsPathRooted($relative)) {
                throw "Arsivde guvenli olmayan yol var: $($entry.FullName)"
            }
            foreach ($part in $relative.Split('/')) {
                if ($part -eq '..' -or $part -eq '.') {
                    throw "Arsivde guvenli olmayan yol var: $($entry.FullName)"
                }
            }
            $targetFull = [IO.Path]::GetFullPath((Join-Path $rootFull $relative))
            if (-not $targetFull.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Arsiv hedefi paket dizini disina cikiyor: $($entry.FullName)"
            }
            if ([string]::IsNullOrEmpty($entry.Name)) {
                New-Item -ItemType Directory -Force -Path $targetFull | Out-Null
                continue
            }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetFull) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $targetFull, $false)
        }
    }
    finally {
        $archive.Dispose()
    }
}

function Get-ChecksumFromFile {
    param([string]$Path)
    $line = Get-Content -LiteralPath $Path -TotalCount 1 -ErrorAction Stop
    $match = [regex]::Match([string]$line, '^[0-9A-Fa-f]{64}')
    if (-not $match.Success) {
        throw "SHA-256 dosyasi gecersiz: $Path"
    }
    return $match.Value.ToLowerInvariant()
}

function Install-PackageVersion {
    param([string]$PackageVersion)
    New-Item -ItemType Directory -Force -Path $script:PackagesRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $script:DownloadsRoot | Out-Null

    $final = Join-Path $script:PackagesRoot $PackageVersion
    $existing = Find-CachedPackage $PackageVersion
    if ($existing) {
        return $existing
    }
    if (Test-Path -LiteralPath $final) {
        Remove-Item -LiteralPath $final -Recurse -Force -ErrorAction Stop
    }

    $tag = "v$PackageVersion"
    $assetName = "$($script:AssetPrefix)-$PackageVersion.zip"
    $baseUri = "https://github.com/$($script:Repository)/releases/download/$tag"
    $token = [guid]::NewGuid().ToString('N')
    $zipPath = Join-Path $script:DownloadsRoot ("$assetName.$token.partial")
    $checksumPath = Join-Path $script:DownloadsRoot ("$assetName.$token.sha256")
    $tempRoot = Join-Path $script:PackagesRoot ("extract-$token")
    try {
        Write-Info "Release indiriliyor: $PackageVersion"
        Invoke-WebRequestChecked -Uri "$baseUri/$assetName.sha256" -OutFile $checksumPath
        $expected = Get-ChecksumFromFile $checksumPath
        Invoke-WebRequestChecked -Uri "$baseUri/$assetName" -OutFile $zipPath
        $actual = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) {
            throw "Paket butunlugu dogrulanamadi. Beklenen $expected, alinan $actual."
        }
        Expand-PackageArchive -ArchivePath $zipPath -Destination $tempRoot
        if (-not (Test-LocalBundleRoot $tempRoot)) {
            throw "Indirilen paket beklenen dosyalari icermiyor."
        }
        $manifestVersion = Get-PackageVersion $tempRoot
        if ($manifestVersion -ne $PackageVersion) {
            throw "Indirilen paket surumu uyusmuyor: manifest $manifestVersion, istenen $PackageVersion."
        }
        $verifyCode = Invoke-VerifyBundle $tempRoot
        if ($verifyCode -ne 0) {
            throw "Indirilen paket dogrulamasi basarisiz (kod $verifyCode)."
        }
        $expected | Set-Content -LiteralPath (Join-Path $tempRoot '.verified') -Encoding ASCII
        Move-Item -LiteralPath $tempRoot -Destination $final
        Write-Ok "Paket dogrulandi ve onbellege alindi: $final"
        return $final
    }
    finally {
        foreach ($path in @($zipPath, $checksumPath)) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            }
        }
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-Package {
    param([string]$RequestedVersion)
    if ($script:ResolvedPackage -and (-not $RequestedVersion -or $RequestedVersion -eq $script:ResolvedVersion)) {
        return $script:ResolvedPackage
    }
    if ($script:LocalBundleRoot) {
        $localVersion = Get-PackageVersion $script:LocalBundleRoot
        $explicit = $RequestedVersion
        if (-not $explicit -and $Version) {
            $explicit = $Version
        }
        if ($explicit -and (Normalize-Version $explicit) -ne $localVersion) {
            throw "Yerel paket $localVersion surumunde; istenen surum $explicit. Yerel kullanimda -Version verilemez."
        }
        $script:ResolvedVersion = $localVersion
        $script:ResolvedPackage = $script:LocalBundleRoot
        return $script:ResolvedPackage
    }
    $target = if ($RequestedVersion) { Normalize-Version $RequestedVersion } else { Resolve-TargetVersion }
    $script:ResolvedVersion = $target
    $cached = Find-CachedPackage $target
    if ($cached) {
        $script:ResolvedPackage = $cached
        return $script:ResolvedPackage
    }
    $script:ResolvedPackage = Install-PackageVersion $target
    return $script:ResolvedPackage
}

function Get-PackageForUninstall {
    param([string]$InstalledVersion)
    if ($script:LocalBundleRoot) {
        return $script:LocalBundleRoot
    }
    if ($InstalledVersion) {
        $cached = Find-CachedPackage $InstalledVersion
        if ($cached) {
            return $cached
        }
    }
    $highest = Get-HighestCachedVersion
    if ($highest) {
        Write-Warn "Kurulu surumun paketi onbellekte yok; onbellekteki $highest yonetim araci kullanilacak."
        return (Find-CachedPackage $highest)
    }
    if ($InstalledVersion) {
        Write-Warn "Kurulu surumun paketi onbellekte yok; $InstalledVersion indirilecek."
        return (Install-PackageVersion (Normalize-Version $InstalledVersion))
    }
    try {
        return (Get-Package)
    }
    catch {
        throw "Kaldirma icin onbellekte yonetim araci bulunamadi ve kurulu surum bilinmiyor. Cevrimici olup paketi indirin veya once kurulum yapin."
    }
}

function Test-OrcaCheckout {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $false
    }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $top = & git -C $resolved rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $top) {
        return $false
    }
    $topPath = ([string]($top | Select-Object -First 1)).Trim()
    try {
        return ([IO.Path]::GetFullPath($topPath) -eq [IO.Path]::GetFullPath($resolved))
    }
    catch {
        return $false
    }
}

function Get-OrcaHead {
    param([string]$Path)
    $head = & git -C $Path rev-parse HEAD 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Orca checkout HEAD okunamadi: $Path"
    }
    return ([string]($head | Select-Object -First 1)).Trim()
}

function Initialize-OrcaSource {
    param(
        [string]$PackageRoot,
        [string]$Path
    )
    $manifest = Get-Manifest $PackageRoot
    $upstream = $manifest.upstream
    $tag = "v$($upstream.version)"
    if (Test-Path -LiteralPath $Path) {
        $items = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)
        if ($items.Count -gt 0) {
            throw "Hedef dizin bos degil: $Path"
        }
    }
    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Write-Info "Orca $($upstream.version) kaynagi klonlaniyor: $Path"
    Write-Host "  git -c core.autocrlf=false clone --branch $tag --depth 1 $($upstream.repository) `"$Path`""
    & git -c core.autocrlf=false clone --branch $tag --depth 1 $upstream.repository $Path | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Orca kaynagi klonlanamadi (git kod $LASTEXITCODE)."
    }
    $head = Get-OrcaHead $Path
    if ($head -ne [string]$upstream.baseCommit) {
        throw "Klonlanan HEAD $head, paketin bekledigi $($upstream.baseCommit) degil. Otomatik reset/checkout yapilmadi."
    }
    Write-Ok "Orca kaynagi hazir: $Path"
}

function Resolve-Source {
    param([switch]$Quiet)
    if ($script:ResolvedSource) {
        return $script:ResolvedSource
    }
    $config = Read-Config
    $requested = $Source
    if ([string]::IsNullOrWhiteSpace($requested) -and $config.ContainsKey('source')) {
        $requested = $config['source']
    }

    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        if (Test-Path -LiteralPath $requested -PathType Container) {
            if (Test-OrcaCheckout $requested) {
                $script:ResolvedSource = (Resolve-Path -LiteralPath $requested).Path
                Save-ConfigSource $script:ResolvedSource
                return $script:ResolvedSource
            }
            if (-not $Quiet) {
                Write-Warn "Dizin bir Orca Git checkout koku degil: $requested"
            }
        }
        elseif (-not $Quiet) {
            Write-Warn "Orca kaynak yolu bulunamadi: $requested"
        }
    }

    $candidates = @()
    if ($script:LocalBundleRoot) {
        $candidates += (Join-Path (Split-Path -Parent $script:LocalBundleRoot) 'orca-dev')
    }
    $candidates += (Join-Path (Get-Location).Path 'orca-dev')
    if ($HOME) {
        $candidates += (Join-Path $HOME 'orca-dev')
    }
    foreach ($candidate in $candidates) {
        if (Test-OrcaCheckout $candidate) {
            $script:ResolvedSource = (Resolve-Path -LiteralPath $candidate).Path
            Save-ConfigSource $script:ResolvedSource
            return $script:ResolvedSource
        }
    }

    if ($Quiet) {
        return $null
    }
    if (-not $script:PromptAllowed) {
        throw "Orca kaynak checkout'u bulunamadi. -Source ile Git kokunu belirtin. Ornek: git clone --branch v1.4.246 --depth 1 $($script:OrcaRepository) C:\orca-dev"
    }

    $default = if ($HOME) { Join-Path $HOME 'orca-dev' } else { Join-Path (Get-Location).Path 'orca-dev' }
    while ($true) {
        $entered = Read-Host "Orca kaynak yolu [$default] (cikmak icin q)"
        if ($null -eq $entered) {
            throw 'Islem iptal edildi.'
        }
        $entered = $entered.Trim()
        if ($entered -eq 'q' -or $entered -eq 'Q') {
            throw 'Islem iptal edildi.'
        }
        if ([string]::IsNullOrWhiteSpace($entered)) {
            $entered = $default
        }
        if (Test-OrcaCheckout $entered) {
            $script:ResolvedSource = (Resolve-Path -LiteralPath $entered).Path
            Save-ConfigSource $script:ResolvedSource
            return $script:ResolvedSource
        }
        if (Test-Path -LiteralPath $entered -PathType Container) {
            Write-Warn "Bu dizin bir Orca Git checkout koku degil: $entered"
            continue
        }
        if ($DryRun) {
            throw "Prova icin mevcut bir Orca kaynagi gerekli; otomatik klonlama yapilmadi."
        }
        $answer = Read-Host "Dizin yok. Desteklenen Orca surumu buraya klonlansin mi? (e/H)"
        if ($null -ne $answer -and $answer.Trim() -match '^(e|evet|y|yes)$') {
            $package = Get-Package
            Initialize-OrcaSource -PackageRoot $package -Path $entered
            $script:ResolvedSource = (Resolve-Path -LiteralPath $entered).Path
            Save-ConfigSource $script:ResolvedSource
            return $script:ResolvedSource
        }
    }
    throw 'Orca kaynak yolu cozumlenemedi.'
}

function Get-InstalledRecord {
    param([string]$SourcePath)
    $gitDir = & git -C $SourcePath rev-parse --absolute-git-dir 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $gitDir) {
        return $null
    }
    $statePath = Join-Path ([string]($gitDir | Select-Object -First 1)).Trim() 'orca-advanced-orchestration/state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return $null
    }
    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        return $state.installation
    }
    catch {
        throw "Kurulum gunlugu okunamadi: $statePath"
    }
}

function Get-InstalledVersion {
    param($Record)
    if ($Record -and $Record.package -and $Record.package.version) {
        return [string]$Record.package.version
    }
    return $null
}

function Show-BuildInstructions {
    param([string]$SourcePath)
    Write-Host ''
    Write-Info 'Durum: kaynak dosyalari degistirildi.'
    Write-Warn 'Uygulama henuz kullanima hazir degil; paket derleme gerektirir.'
    Write-Host 'Derlemek icin:'
    Write-Host "  cd `"$SourcePath`""
    Write-Host '  pnpm install --frozen-lockfile'
    Write-Host '  pnpm build'
    Write-Host 'Gelistirme icin: pnpm dev --worktree-profile'
}

function Invoke-Build {
    param([string]$SourcePath)
    $pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
    if (-not $pnpm) {
        Write-Err "pnpm bulunamadi. Node.js 24 ve Orca'nin package.json icindeki pnpm surumunu kurun."
        return 1
    }
    Push-Location -LiteralPath $SourcePath
    try {
        & pnpm install --frozen-lockfile | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Err "pnpm install basarisiz (kod $LASTEXITCODE)."
            return $LASTEXITCODE
        }
        & pnpm build | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Err "pnpm build basarisiz (kod $LASTEXITCODE)."
            return $LASTEXITCODE
        }
        Write-Ok 'Derleme tamamlandi.'
        return 0
    }
    finally {
        Pop-Location
    }
}

function Offer-Build {
    param([string]$SourcePath)
    Show-BuildInstructions $SourcePath
    if (-not $script:PromptAllowed -or $NoPause) {
        return
    }
    $answer = Read-Host 'pnpm install ve pnpm build simdi calistirilsin mi? (e/H)'
    if ($null -ne $answer -and $answer.Trim() -match '^(e|evet|y|yes)$') {
        [void](Invoke-Build $SourcePath)
    }
}

function Invoke-InstallAction {
    param([switch]$DryRun)
    Assert-Git
    $package = Get-Package
    $manifest = Get-Manifest $package
    Write-Host "Paket surumu: $($manifest.package.version)"
    Write-Host "Hedef Orca tabani: $($manifest.upstream.version) ($($manifest.upstream.baseCommit))"
    $source = Resolve-Source
    $arguments = @('install', '--source', $source)
    if ($DryRun) {
        $arguments += '--dry-run'
    }
    $code = Invoke-Manage -PackageRoot $package -Arguments $arguments
    if ($code -eq 0) {
        if ($DryRun) {
            Write-Ok 'Kurulum provasi tamamlandi; hicbir dosya degistirilmedi.'
        }
        else {
            Write-Ok 'Kaynaga uygulama tamamlandi.'
            Offer-Build $source
        }
    }
    return $code
}

function Invoke-UpdateAction {
    param([switch]$DryRun)
    Assert-Git
    $source = Resolve-Source
    $record = Get-InstalledRecord $source
    if (-not $record -or $record.status -eq 'uninstalled') {
        Write-Warn 'Etkin kurulum yok. Guncelleme yerine Kur secenegini kullanin.'
        return 1
    }
    $installedVersion = Get-InstalledVersion $record
    if ($script:LocalBundleRoot) {
        $package = Get-Package
        $targetVersion = Get-PackageVersion $package
    }
    else {
        $targetVersion = Resolve-TargetVersion
        $package = Get-Package $targetVersion
    }
    $arguments = @('update', '--source', $source)
    if ($DryRun) {
        $arguments += '--dry-run'
    }
    $code = Invoke-Manage -PackageRoot $package -Arguments $arguments
    if ($code -eq 0) {
        if ($installedVersion -and $installedVersion -eq $targetVersion) {
            Write-Ok "Zaten guncel: $targetVersion. Dosyalar degistirilmedi."
        }
        elseif ($DryRun) {
            Write-Ok 'Guncelleme provasi tamamlandi; hicbir dosya degistirilmedi.'
        }
        else {
            $installedLabel = if ($installedVersion) { $installedVersion } else { 'bilinmiyor' }
            Write-Ok "Guncelleme tamamlandi: $installedLabel -> $targetVersion"
            Offer-Build $source
        }
    }
    return $code
}

function Invoke-UninstallAction {
    param([switch]$DryRun)
    Assert-Git
    $source = Resolve-Source
    $record = Get-InstalledRecord $source
    if (-not $record -or $record.status -eq 'uninstalled') {
        Write-Ok 'Etkin kurulum yok; kaldirilacak bir sey bulunamadi.'
        return 0
    }
    $installedVersion = Get-InstalledVersion $record
    $package = Get-PackageForUninstall $installedVersion
    $arguments = @('uninstall', '--source', $source)
    if ($DryRun) {
        $arguments += '--dry-run'
    }
    $code = Invoke-Manage -PackageRoot $package -Arguments $arguments
    if ($code -eq 0) {
        if ($DryRun) {
            Write-Ok 'Kaldirma provasi tamamlandi; hicbir dosya degistirilmedi.'
        }
        else {
            Write-Ok 'Kaldirma tamamlandi. Orca kaynak dizini silinmedi.'
        }
    }
    return $code
}

function Show-Versions {
    param([string]$SourcePath)
    Write-Host ''
    Write-Info 'Surumler'
    if ($SourcePath) {
        $record = Get-InstalledRecord $SourcePath
        $installed = Get-InstalledVersion $record
        if ($record) {
            Write-Host ("  Kurulu: {0} (durum: {1})" -f ($(if ($installed) { $installed } else { 'bilinmiyor' })), $record.status)
        }
        else {
            Write-Host '  Kurulu: yok'
        }
    }
    $cached = @(Get-CachedVersions)
    if ($cached.Count -gt 0) {
        Write-Host ("  Onbellek: {0}" -f ($cached -join ', '))
    }
    else {
        Write-Host '  Onbellek: bos'
    }
    if ($script:LocalBundleRoot) {
        Write-Host ("  Yerel paket: {0}" -f (Get-PackageVersion $script:LocalBundleRoot))
    }
    try {
        $latest = Get-LatestVersion
        Write-Host "  Son kararli: $latest"
    }
    catch {
        Write-Host "  Son kararli: alinamadi ($($_.Exception.Message))"
    }
}

function Invoke-StatusAction {
    Assert-Git
    $source = Resolve-Source
    $record = Get-InstalledRecord $source
    $installedVersion = Get-InstalledVersion $record
    try {
        if ($record) {
            $package = Get-PackageForUninstall $installedVersion
        }
        else {
            $package = Get-Package
        }
    }
    catch {
        Write-Err $_.Exception.Message
        Show-Versions $source
        return 1
    }
    $code = Invoke-Manage -PackageRoot $package -Arguments @('status', '--source', $source)
    Show-Versions $source
    if ($code -eq 0 -and $record -and $record.status -eq 'installed') {
        Write-Warn 'Not: kaynak dosyalari degistirilmis olsa da derleme tamamlanmadan yeni davranis calismaz.'
    }
    return $code
}

function Invoke-VerifyAction {
    $package = Get-Package
    $code = Invoke-VerifyBundle $package
    if ($code -ne 0) {
        return $code
    }
    $source = Resolve-Source -Quiet
    if (-not $source) {
        Write-Host 'Orca kaynak yolu belirtilmedi; yalnizca paket dogrulandi.'
        return 0
    }
    $installedVersion = Get-InstalledVersion (Get-InstalledRecord $source)
    $tool = $package
    if ($installedVersion) {
        $cached = Find-CachedPackage $installedVersion
        if ($cached) {
            $tool = $cached
        }
    }
    return (Invoke-Manage -PackageRoot $tool -Arguments @('verify', '--source', $source))
}

function Confirm-Uninstall {
    $answer = Read-Host 'Kaldirmak istediginizden emin misiniz? (e/H)'
    if ($null -eq $answer) {
        return $false
    }
    return $answer.Trim() -match '^(e|evet|y|yes)$'
}

function Change-SourcePath {
    $previous = $script:ResolvedSource
    $entered = Read-Host 'Yeni Orca kaynak yolu (iptal icin bos birakin)'
    if ([string]::IsNullOrWhiteSpace($entered)) {
        Write-Warn 'Kaynak yolu degistirilmedi.'
        return
    }
    $entered = $entered.Trim()
    if (Test-OrcaCheckout $entered) {
        $script:ResolvedSource = (Resolve-Path -LiteralPath $entered).Path
        Save-ConfigSource $script:ResolvedSource
        Write-Ok "Orca kaynak yolu kaydedildi: $($script:ResolvedSource)"
        return
    }
    $answer = Read-Host 'Dizin bir Git checkout degil veya yok. Desteklenen surum klonlansin mi? (e/H)'
    if ($null -eq $answer -or $answer.Trim() -notmatch '^(e|evet|y|yes)$') {
        Write-Warn "Kaynak yolu degistirilmedi: $previous"
        return
    }
    try {
        $package = Get-Package
        Initialize-OrcaSource -PackageRoot $package -Path $entered
        $script:ResolvedSource = (Resolve-Path -LiteralPath $entered).Path
        Save-ConfigSource $script:ResolvedSource
        Write-Ok "Orca kaynak yolu kaydedildi: $($script:ResolvedSource)"
    }
    catch {
        $script:ResolvedSource = $previous
        Write-Err "Kaynak yolu degistirilmedi: $($_.Exception.Message)"
    }
}

function Invoke-Rehearsal {
    Write-Host '  1) Kurulum provasi'
    Write-Host '  2) Guncelleme provasi'
    Write-Host '  3) Kaldirma provasi'
    $choice = Read-Host 'Prova secimi'
    if ($null -eq $choice) {
        return 0
    }
    switch ($choice.Trim()) {
        '1' { return Invoke-InstallAction -DryRun }
        '2' { return Invoke-UpdateAction -DryRun }
        '3' { return Invoke-UninstallAction -DryRun }
        default {
            Write-Warn "Gecersiz secim: $choice"
            return 0
        }
    }
}

function Show-Header {
    Write-Host ''
    Write-Host 'Orca Advanced Orchestration' -ForegroundColor Cyan
    if ($script:LocalBundleRoot) {
        Write-Host "Paket: yerel ($script:LocalBundleRoot)"
    }
    else {
        Write-Host "Paket: GitHub Releases (onbellek: $($script:PackagesRoot))"
    }
    $sourceLabel = '(kurulumda sorulacak)'
    if ($script:ResolvedSource) {
        $sourceLabel = $script:ResolvedSource
    }
    elseif ($Source) {
        $sourceLabel = $Source
    }
    Write-Host "Orca:  $sourceLabel"
    if ($script:ResolvedSource) {
        $record = Get-InstalledRecord $script:ResolvedSource
        $installed = Get-InstalledVersion $record
        if ($record) {
            Write-Host ("Kurulu: {0} ({1})" -f ($(if ($installed) { $installed } else { 'bilinmiyor' })), $record.status)
        }
        else {
            Write-Host 'Kurulu: yok'
        }
    }
    $cached = @(Get-CachedVersions)
    if ($cached.Count -gt 0) {
        Write-Host ("Onbellek: {0}" -f ($cached -join ', '))
    }
    if ($script:LatestVersion) {
        Write-Host "Son kararli: $($script:LatestVersion)"
    }
    Write-Host ''
}

function Show-Menu {
    while ($true) {
        Show-Header
        Write-Host '  1) Kur'
        Write-Host '  2) Guncelle'
        Write-Host '  3) Kaldir'
        Write-Host '  4) Durum ve surumler'
        Write-Host '  5) Dogrula'
        Write-Host '  6) Islem provasi (dry-run)'
        Write-Host '  7) Orca kaynak yolunu degistir'
        Write-Host '  0) Cikis'
        Write-Host ''

        $choice = Read-Host 'Secim'
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
                '2' { $code = Invoke-UpdateAction }
                '3' {
                    if (Confirm-Uninstall) {
                        $code = Invoke-UninstallAction
                    }
                    else {
                        Write-Warn 'Kaldirma iptal edildi.'
                        $code = 0
                    }
                }
                '4' { $code = Invoke-StatusAction }
                '5' { $code = Invoke-VerifyAction }
                '6' { $code = Invoke-Rehearsal }
                '7' { Change-SourcePath; $code = 0 }
                default {
                    Write-Warn "Gecersiz secim: $choice"
                }
            }
        }
        catch {
            Write-Err "Hata: $($_.Exception.Message)"
            $code = 1
        }

        if ($code -ne 0) {
            Write-Err "Islem basarisiz (kod $code)."
        }
        if (-not $NoPause) {
            [void](Read-Host 'Devam etmek icin Enter')
        }
    }
}

function Invoke-Main {
    $script:LocalBundleRoot = Find-LocalBundleRoot
    if ($script:LocalBundleRoot) {
        Write-Host "Yerel paket kullaniliyor: $($script:LocalBundleRoot)"
    }

    if ($Action -eq 'menu') {
        return Show-Menu
    }
    if ($DryRun -and $Action -notin @('install', 'update', 'uninstall')) {
        Write-Warn '-DryRun yalnizca install, update ve uninstall icin kullanilir; yok sayildi.'
    }

    switch ($Action) {
        'verify' { return Invoke-VerifyAction }
        'install' { return Invoke-InstallAction -DryRun:$DryRun }
        'update' { return Invoke-UpdateAction -DryRun:$DryRun }
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
if ($script:HasScriptPath) {
    exit $exitCode
}
$global:LASTEXITCODE = $exitCode
