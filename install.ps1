# Orca Advanced Orchestration installer. Safe to run through irm ... | iex.
param(
    [ValidateSet('menu', 'install', 'update', 'uninstall', 'status', 'verify')]
    [string]$Action = 'menu',
    [string]$Source,
    [string]$Version,
    [switch]$DryRun,
    [string]$RepoRoot,
    [string[]]$Pack,
    [switch]$NoPause,
    [ValidateSet('tr', 'en', 'tur', 'eng')]
    [string]$Lang = 'tr'
)

$script:LangExplicit = $PSBoundParameters.ContainsKey('Lang')

if ($PSVersionTable.PSVersion.Major -lt 5 -or
    ($PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -lt 1)) {
    throw 'PowerShell 5.1 veya daha yeni bir surum gerekir. / PowerShell 5.1 or newer is required.'
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
$script:Language = $null
$script:ConfigCache = $null

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

$script:Text = @{
    tr = @{
        'common.cancel'                    = 'Islem iptal edildi.'
        'common.invalid_choice'            = 'Gecersiz secim: {0}'
        'common.unknown'                   = 'bilinmiyor'
        'common.pause'                     = 'Devam etmek icin Enter'
        'common.error'                     = 'Hata: {0}'
        'common.action_failed'             = 'Islem basarisiz (kod {0}).'

        'lang.prompt'                      = 'Dil / Language [1] Turkce [2] English (Enter=1)'
        'lang.saved'                       = 'Dil kaydedildi: {0}'
        'lang.invalid'                     = 'Dil secilmedi; mevcut dil korunuyor.'
        'lang.tr'                          = 'Turkce'
        'lang.en'                          = 'English'

        'start.local_bundle'               = 'Yerel paket kullaniliyor: {0}'
        'start.dry_run_ignored'            = '-DryRun yalnizca install, update ve uninstall icin kullanilir; yok sayildi.'
        'config.read_failed'               = 'Ayar dosyasi okunamadi, yok sayiliyor: {0}'

        'dep.python_missing'               = "Python 3.9+ bulunamadi. Python'u kurup PATH'e ekleyin: https://www.python.org/downloads/"
        'dep.git_missing'                  = "Git bulunamadi. Git kurup PATH'e ekleyin: https://git-scm.com/downloads"

        'pkg.manifest_missing'             = 'Paket manifesti bulunamadi: {0}'
        'pkg.version_missing'              = 'Paket manifestinde package.version alani yok: {0}'
        'pkg.invalid_version'              = 'Gecersiz surum: {0} (orn. 1.0.0 veya v1.0.0)'
        'pkg.tag_missing'                  = 'GitHub yanitinda tag_name yok.'
        'pkg.latest_cached'                = "Son surum GitHub'dan alinamadi; onbellekteki {0} kullanilacak."
        'pkg.latest_failed'                = "GitHub Release surumu alinamadi: {0}. Henuz yayimlanmis release yoksa -Version ile onbellekteki bir surumu secin."
        'pkg.unsafe_path'                  = 'Arsivde guvenli olmayan yol var: {0}'
        'pkg.target_escapes'               = 'Arsiv hedefi paket dizini disina cikiyor: {0}'
        'pkg.checksum_invalid'             = 'SHA-256 dosyasi gecersiz: {0}'
        'pkg.downloading'                  = 'Release indiriliyor: {0}'
        'pkg.checksum_mismatch'            = 'Paket butunlugu dogrulanamadi. Beklenen {0}, alinan {1}.'
        'pkg.incomplete'                   = 'Indirilen paket beklenen dosyalari icermiyor.'
        'pkg.version_mismatch'             = 'Indirilen paket surumu uyusmuyor: manifest {0}, istenen {1}.'
        'pkg.verify_failed'                = 'Indirilen paket dogrulamasi basarisiz (kod {0}).'
        'pkg.cached'                       = 'Paket dogrulandi ve onbellege alindi: {0}'
        'pkg.local_version_conflict'       = 'Yerel paket {0} surumunde; istenen surum {1}. Yerel kullanimda -Version verilemez.'
        'pkg.uninstall_cached'             = 'Kurulu surumun paketi onbellekte yok; onbellekteki {0} yonetim araci kullanilacak.'
        'pkg.uninstall_download'           = 'Kurulu surumun paketi onbellekte yok; {0} indirilecek.'
        'pkg.uninstall_no_tool'            = 'Kaldirma icin onbellekte yonetim araci bulunamadi ve kurulu surum bilinmiyor. Cevrimici olup paketi indirin veya once kurulum yapin.'

        'source.head_unreadable'           = 'Orca checkout HEAD okunamadi: {0}'
        'source.target_not_empty'          = 'Hedef dizin bos degil: {0}'
        'source.cloning'                   = 'Orca {0} kaynagi klonlaniyor: {1}'
        'source.clone_failed'              = 'Orca kaynagi klonlanamadi (git kod {0}).'
        'source.clone_head_mismatch'       = 'Klonlanan HEAD {0}, paketin bekledigi {1} degil. Otomatik reset/checkout yapilmadi.'
        'source.ready'                     = 'Orca kaynagi hazir: {0}'
        'source.not_checkout'              = 'Dizin bir Orca Git checkout koku degil: {0}'
        'source.saved_ignored'             = 'Kayitli kaynak yolu su anda kullanilamiyor; bu calistirmada yok sayiliyor (ayar korunuyor): {0}'
        'source.explicit_missing'          = '-Source yolu bulunamadi: {0}'
        'source.explicit_not_checkout'     = '-Source yolu bir Orca Git checkout koku degil: {0}'
        'source.discovered'                = 'Orca kaynagi otomatik bulundu: {0}'
        'source.multiple_heading'          = 'Birden fazla Orca kaynagi bulundu:'
        'source.multiple_prompt'           = 'Secim [Enter=1]'
        'source.multiple_auto'             = 'Birden fazla Orca kaynagi var; ilk siradaki kullaniliyor: {0}'
        'source.head_mismatch'             = 'Uyari: {0} checkout HEAD degeri paketin bekledigi taban ile uyusmuyor (bulunan {1}, beklenen {2}).'
        'source.auto_clone'                = 'Orca kaynagi bulunamadi. Desteklenen surum {0} otomatik klonlanacak: {1}'
        'source.clone_dest_taken'          = 'Otomatik klon hedefi zaten dolu: {0}. Kullanmak istediginiz checkout''u -Source ile belirtin.'
        'source.install_hint'              = "Orca kaynak checkout'u bulunamadi. -Source ile Git kokunu belirtin. Ornek: git clone --branch v1.4.246 --depth 1 {0} C:\orca-dev"
        'source.required_hint'             = "Bu islem icin mevcut bir Orca kaynak checkout'u gerekli. -Source ile checkout'u belirtin."
        'source.dry_run_requires_existing' = 'Prova icin mevcut bir Orca kaynagi gerekli; otomatik klonlama yapilmadi.'
        'source.state_unreadable'          = 'Kurulum gunlugu okunamadi: {0}'

        'build.status_modified'            = 'Durum: kaynak dosyalari degistirildi.'
        'build.required'                   = 'Uygulama henuz kullanima hazir degil; paket derleme gerektirir.'
        'build.heading'                    = 'Derlemek icin:'
        'build.dev_hint'                   = 'Gelistirme icin: pnpm dev --worktree-profile'
        'build.pnpm_missing'               = "pnpm bulunamadi. Node.js 24 ve Orca'nin package.json icindeki pnpm surumunu kurun."
        'build.install_failed'             = 'pnpm install basarisiz (kod {0}).'
        'build.failed'                     = 'pnpm build basarisiz (kod {0}).'
        'build.done'                       = 'Derleme tamamlandi.'
        'build.question'                   = 'pnpm install ve pnpm build simdi calistirilsin mi? (e/H)'

        'packs.heading'                    = 'Kurulacak bilesenler:'
        'packs.prompt'                     = 'Secim [Enter=kur, A=tumu, N=hicbiri, Q=iptal]'
        'packs.empty'                      = 'En az bir bilesen secin.'
        'packs.skipped'                    = "Bilesen secimi atlandi (etkilesimsiz oturum); tum pack'ler kurulacak."

        'action.package_version'           = 'Paket surumu: {0}'
        'action.target_base'               = 'Hedef Orca tabani: {0} ({1})'
        'action.install_dry'               = 'Kurulum provasi tamamlandi; hicbir dosya degistirilmedi.'
        'action.install_ok'                = 'Kaynaga uygulama tamamlandi.'
        'action.update_missing'            = 'Etkin kurulum yok. Guncelleme yerine Kur secenegini kullanin.'
        'action.update_current'            = 'Zaten guncel: {0}. Dosyalar degistirilmedi.'
        'action.update_dry'                = 'Guncelleme provasi tamamlandi; hicbir dosya degistirilmedi.'
        'action.update_ok'                 = 'Guncelleme tamamlandi: {0} -> {1}'
        'action.uninstall_missing'         = 'Etkin kurulum yok; kaldirilacak bir sey bulunamadi.'
        'action.uninstall_dry'             = 'Kaldirma provasi tamamlandi; hicbir dosya degistirilmedi.'
        'action.uninstall_ok'              = 'Kaldirma tamamlandi. Orca kaynak dizini silinmedi.'
        'action.versions'                  = 'Surumler'
        'action.installed'                 = '  Kurulu: {0} (durum: {1})'
        'action.not_installed'             = '  Kurulu: yok'
        'action.cache'                     = '  Onbellek: {0}'
        'action.cache_empty'               = '  Onbellek: bos'
        'action.local_package'             = '  Yerel paket: {0}'
        'action.latest'                    = '  Son kararli: {0}'
        'action.latest_failed'             = '  Son kararli: alinamadi ({0})'
        'action.build_note'                = 'Not: kaynak dosyalari degistirilmis olsa da derleme tamamlanmadan yeni davranis calismaz.'
        'action.verify_no_source'          = 'Orca kaynak yolu belirtilmedi; yalnizca paket dogrulandi.'
        'action.no_source'                 = 'Orca kaynagi bulunamadi; yalnizca paket ve onbellek bilgileri gosteriliyor.'
        'action.confirm_uninstall'         = 'Kaldirmak istediginizden emin misiniz? (e/H)'
        'action.new_source'                = 'Yeni Orca kaynak yolu (iptal icin bos birakin)'
        'action.source_unchanged'          = 'Kaynak yolu degistirilmedi.'
        'action.source_saved'              = 'Orca kaynak yolu kaydedildi: {0}'
        'action.change_clone_question'     = 'Dizin bir Git checkout degil veya yok. Desteklenen surum klonlansin mi? (e/H)'
        'action.source_unchanged_detail'   = 'Kaynak yolu degistirilmedi: {0}'
        'action.rehearsal_install'         = '  1) Kurulum provasi'
        'action.rehearsal_update'          = '  2) Guncelleme provasi'
        'action.rehearsal_uninstall'       = '  3) Kaldirma provasi'
        'action.rehearsal_prompt'          = 'Prova secimi'
        'action.uninstall_cancelled'       = 'Kaldirma iptal edildi.'

        'menu.title'                       = 'Orca Advanced Orchestration'
        'menu.package_local'               = 'Paket: yerel ({0})'
        'menu.package_remote'              = 'Paket: GitHub Releases (onbellek: {0})'
        'menu.source_pending'              = '(kurulumda sorulacak)'
        'menu.orca'                        = 'Orca:  {0}'
        'menu.installed'                   = 'Kurulu: {0} ({1})'
        'menu.not_installed'               = 'Kurulu: yok'
        'menu.cache'                       = 'Onbellek: {0}'
        'menu.latest'                      = 'Son kararli: {0}'
        'menu.install'                     = '  1) Kur (bilesen secimiyle)'
        'menu.update'                      = '  2) Guncelle'
        'menu.uninstall'                   = '  3) Kaldir'
        'menu.status'                      = '  4) Durum ve surumler'
        'menu.verify'                      = '  5) Dogrula'
        'menu.rehearsal'                   = '  6) Islem provasi (dry-run)'
        'menu.source'                      = '  7) Orca kaynak yolunu degistir'
        'menu.lang'                        = '  8) Dil degistir (Turkce/English)'
        'menu.exit'                        = '  0) Cikis'
        'menu.prompt'                      = 'Secim'
    }
    en = @{
        'common.cancel'                    = 'Operation cancelled.'
        'common.invalid_choice'            = 'Invalid choice: {0}'
        'common.unknown'                   = 'unknown'
        'common.pause'                     = 'Press Enter to continue'
        'common.error'                     = 'Error: {0}'
        'common.action_failed'             = 'Operation failed (code {0}).'

        'lang.prompt'                      = 'Language / Dil [1] Turkce [2] English (Enter=1)'
        'lang.saved'                       = 'Language saved: {0}'
        'lang.invalid'                     = 'No language selected; keeping the current language.'
        'lang.tr'                          = 'Turkce'
        'lang.en'                          = 'English'

        'start.local_bundle'               = 'Using local package: {0}'
        'start.dry_run_ignored'            = '-DryRun only applies to install, update and uninstall; ignored.'
        'config.read_failed'               = 'Could not read the settings file; ignoring it: {0}'

        'dep.python_missing'               = "Python 3.9+ was not found. Install Python and add it to PATH: https://www.python.org/downloads/"
        'dep.git_missing'                  = "Git was not found. Install Git and add it to PATH: https://git-scm.com/downloads"

        'pkg.manifest_missing'             = 'Package manifest not found: {0}'
        'pkg.version_missing'              = 'Package manifest has no package.version field: {0}'
        'pkg.invalid_version'              = 'Invalid version: {0} (e.g. 1.0.0 or v1.0.0)'
        'pkg.tag_missing'                  = 'The GitHub response has no tag_name.'
        'pkg.latest_cached'                = 'Could not fetch the latest release from GitHub; using cached {0}.'
        'pkg.latest_failed'                = 'Could not fetch the GitHub Release version: {0}. If no release is published yet, pick a cached version with -Version.'
        'pkg.unsafe_path'                  = 'Archive contains an unsafe path: {0}'
        'pkg.target_escapes'               = 'Archive target escapes the package directory: {0}'
        'pkg.checksum_invalid'             = 'Invalid SHA-256 file: {0}'
        'pkg.downloading'                  = 'Downloading release: {0}'
        'pkg.checksum_mismatch'            = 'Package integrity check failed. Expected {0}, got {1}.'
        'pkg.incomplete'                   = 'The downloaded package is missing expected files.'
        'pkg.version_mismatch'             = 'Downloaded package version mismatch: manifest {0}, requested {1}.'
        'pkg.verify_failed'                = 'Downloaded package verification failed (code {0}).'
        'pkg.cached'                       = 'Package verified and cached: {0}'
        'pkg.local_version_conflict'       = 'The local package is version {0}; requested {1}. -Version cannot be used with a local package.'
        'pkg.uninstall_cached'             = 'The installed version is not cached; using cached management tool {0}.'
        'pkg.uninstall_download'           = 'The installed version is not cached; downloading {0}.'
        'pkg.uninstall_no_tool'            = 'No cached management tool was found and the installed version is unknown. Go online and download the package, or install first.'

        'source.head_unreadable'           = 'Could not read the Orca checkout HEAD: {0}'
        'source.target_not_empty'          = 'Target directory is not empty: {0}'
        'source.cloning'                   = 'Cloning Orca {0} source into {1}'
        'source.clone_failed'              = 'Could not clone the Orca source (git exit code {0}).'
        'source.clone_head_mismatch'       = 'Cloned HEAD {0} does not match the expected {1}. No automatic reset/checkout was performed.'
        'source.ready'                     = 'Orca source is ready: {0}'
        'source.not_checkout'              = 'Directory is not an Orca Git checkout root: {0}'
        'source.saved_ignored'             = 'The saved source path is currently unavailable; ignoring it for this run (setting kept): {0}'
        'source.explicit_missing'          = '-Source path was not found: {0}'
        'source.explicit_not_checkout'     = '-Source path is not an Orca Git checkout root: {0}'
        'source.discovered'                = 'Found Orca source automatically: {0}'
        'source.multiple_heading'          = 'Multiple Orca sources were found:'
        'source.multiple_prompt'           = 'Choice [Enter=1]'
        'source.multiple_auto'             = 'Multiple Orca sources found; using the first one: {0}'
        'source.head_mismatch'             = 'Warning: {0} checkout HEAD does not match the package base (found {1}, expected {2}).'
        'source.auto_clone'                = 'No Orca source checkout was found. Cloning supported version {0} into {1}.'
        'source.clone_dest_taken'          = 'The automatic clone destination already exists: {0}. Pass the checkout you want with -Source.'
        'source.install_hint'              = "Could not find an Orca source checkout. Pass the Git root with -Source. Example: git clone --branch v1.4.246 --depth 1 {0} C:\orca-dev"
        'source.required_hint'             = 'This action needs an existing Orca source checkout. Pass it with -Source.'
        'source.dry_run_requires_existing' = 'A rehearsal requires an existing Orca source; no automatic clone was performed.'
        'source.state_unreadable'          = 'Could not read the installation record: {0}'

        'build.status_modified'            = 'Status: source files were modified.'
        'build.required'                   = 'The application is not ready to use yet; the package requires a build.'
        'build.heading'                    = 'To build:'
        'build.dev_hint'                   = 'For development: pnpm dev --worktree-profile'
        'build.pnpm_missing'               = "pnpm was not found. Install Node.js 24 and the pnpm version pinned in Orca's package.json."
        'build.install_failed'             = 'pnpm install failed (code {0}).'
        'build.failed'                     = 'pnpm build failed (code {0}).'
        'build.done'                       = 'Build completed.'
        'build.question'                   = 'Run pnpm install and pnpm build now? (y/N)'

        'packs.heading'                    = 'Components to install:'
        'packs.prompt'                     = 'Choice [Enter=install, A=all, N=none, Q=cancel]'
        'packs.empty'                      = 'Select at least one component.'
        'packs.skipped'                    = 'Component selection skipped (non-interactive session); all packs will be installed.'

        'action.package_version'           = 'Package version: {0}'
        'action.target_base'               = 'Target Orca base: {0} ({1})'
        'action.install_dry'               = 'Installation rehearsal completed; no files were changed.'
        'action.install_ok'                = 'Changes applied to the source.'
        'action.update_missing'            = 'No active installation. Use Install instead of Update.'
        'action.update_current'            = 'Already up to date: {0}. No files were changed.'
        'action.update_dry'                = 'Update rehearsal completed; no files were changed.'
        'action.update_ok'                 = 'Update completed: {0} -> {1}'
        'action.uninstall_missing'         = 'No active installation; nothing to uninstall.'
        'action.uninstall_dry'             = 'Uninstall rehearsal completed; no files were changed.'
        'action.uninstall_ok'              = 'Uninstall completed. The Orca source directory was not deleted.'
        'action.versions'                  = 'Versions'
        'action.installed'                 = '  Installed: {0} (status: {1})'
        'action.not_installed'             = '  Installed: none'
        'action.cache'                     = '  Cache: {0}'
        'action.cache_empty'               = '  Cache: empty'
        'action.local_package'             = '  Local package: {0}'
        'action.latest'                    = '  Latest stable: {0}'
        'action.latest_failed'             = '  Latest stable: unavailable ({0})'
        'action.build_note'                = 'Note: source files are modified, but the new behavior does not run until the build completes.'
        'action.verify_no_source'          = 'No Orca source path was provided; only the package was verified.'
        'action.no_source'                 = 'No Orca source checkout was found; showing package and cache information only.'
        'action.confirm_uninstall'         = 'Are you sure you want to uninstall? (y/N)'
        'action.new_source'                = 'New Orca source path (leave empty to cancel)'
        'action.source_unchanged'          = 'Source path was not changed.'
        'action.source_saved'              = 'Orca source path saved: {0}'
        'action.change_clone_question'     = 'Directory is not a Git checkout or does not exist. Clone the supported version? (y/N)'
        'action.source_unchanged_detail'   = 'Source path was not changed: {0}'
        'action.rehearsal_install'         = '  1) Installation rehearsal'
        'action.rehearsal_update'          = '  2) Update rehearsal'
        'action.rehearsal_uninstall'       = '  3) Uninstall rehearsal'
        'action.rehearsal_prompt'          = 'Rehearsal choice'
        'action.uninstall_cancelled'       = 'Uninstall cancelled.'

        'menu.title'                       = 'Orca Advanced Orchestration'
        'menu.package_local'               = 'Package: local ({0})'
        'menu.package_remote'              = 'Package: GitHub Releases (cache: {0})'
        'menu.source_pending'              = '(asked during install)'
        'menu.orca'                        = 'Orca:  {0}'
        'menu.installed'                   = 'Installed: {0} ({1})'
        'menu.not_installed'               = 'Installed: none'
        'menu.cache'                       = 'Cache: {0}'
        'menu.latest'                      = 'Latest stable: {0}'
        'menu.install'                     = '  1) Install (component selection)'
        'menu.update'                      = '  2) Update'
        'menu.uninstall'                   = '  3) Uninstall'
        'menu.status'                      = '  4) Status and versions'
        'menu.verify'                      = '  5) Verify'
        'menu.rehearsal'                   = '  6) Rehearsal (dry-run)'
        'menu.source'                      = '  7) Change Orca source path'
        'menu.lang'                        = '  8) Change language (Turkce/English)'
        'menu.exit'                        = '  0) Exit'
        'menu.prompt'                      = 'Choice'
    }
}

function Normalize-Lang {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }
    switch ($Value.Trim().ToLowerInvariant()) {
        'tr' { return 'tr' }
        'tur' { return 'tr' }
        'turkce' { return 'tr' }
        'en' { return 'en' }
        'eng' { return 'en' }
        'english' { return 'en' }
    }
    return $null
}

function Get-Lang {
    if ($script:Language) {
        return $script:Language
    }
    return 'tr'
}

function T {
    param([string]$Key)
    $table = $script:Text[(Get-Lang)]
    if ($table -and $table.ContainsKey($Key)) {
        return $table[$Key]
    }
    return "[$Key]"
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
    if ($null -ne $script:ConfigCache) {
        return $script:ConfigCache
    }
    $config = @{}
    if (Test-Path -LiteralPath $script:ConfigPath -PathType Leaf) {
        try {
            $raw = Get-Content -LiteralPath $script:ConfigPath -Raw -ErrorAction Stop
            $parsed = $raw | ConvertFrom-Json
            if ($parsed -and $parsed.source) {
                $config['source'] = [string]$parsed.source
            }
            if ($parsed -and $parsed.lang) {
                $savedLang = Normalize-Lang ([string]$parsed.lang)
                if ($savedLang) {
                    $config['lang'] = $savedLang
                }
            }
        }
        catch {
            Write-Warn ((T 'config.read_failed') -f $script:ConfigPath)
        }
    }
    $script:ConfigCache = $config
    return $config
}

function Save-Config {
    $config = Read-Config
    New-Item -ItemType Directory -Force -Path $script:CacheRoot | Out-Null
    $payload = [ordered]@{}
    if ($config.ContainsKey('source') -and -not [string]::IsNullOrWhiteSpace($config['source'])) {
        $payload['source'] = [string]$config['source']
    }
    if ($config.ContainsKey('lang') -and $config['lang']) {
        $payload['lang'] = [string]$config['lang']
    }
    $payload | ConvertTo-Json | Set-Content -LiteralPath $script:ConfigPath -Encoding UTF8
}

function Save-ConfigSource {
    param([string]$Path)
    $config = Read-Config
    $config['source'] = $Path
    Save-Config
}

function Save-ConfigLang {
    param([string]$Value)
    $config = Read-Config
    $config['lang'] = $Value
    Save-Config
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
    throw (T 'dep.python_missing')
}

function Assert-Git {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw (T 'dep.git_missing')
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
        throw ((T 'pkg.manifest_missing') -f $path)
    }
    return (Get-Content -LiteralPath $path -Raw | ConvertFrom-Json)
}

function Get-PackageVersion {
    param([string]$PackageRoot)
    $manifest = Get-Manifest $PackageRoot
    if (-not $manifest.package -or -not $manifest.package.version) {
        throw ((T 'pkg.version_missing') -f $PackageRoot)
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
        throw ((T 'pkg.invalid_version') -f $Value)
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
                throw (T 'pkg.tag_missing')
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
            Write-Warn ((T 'pkg.latest_cached') -f $cached)
            $script:LatestVersion = $cached
        }
        else {
            throw ((T 'pkg.latest_failed') -f $_.Exception.Message)
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
                throw ((T 'pkg.unsafe_path') -f $entry.FullName)
            }
            foreach ($part in $relative.Split('/')) {
                if ($part -eq '..' -or $part -eq '.') {
                    throw ((T 'pkg.unsafe_path') -f $entry.FullName)
                }
            }
            $targetFull = [IO.Path]::GetFullPath((Join-Path $rootFull $relative))
            if (-not $targetFull.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw ((T 'pkg.target_escapes') -f $entry.FullName)
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
        throw ((T 'pkg.checksum_invalid') -f $Path)
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
        Write-Info ((T 'pkg.downloading') -f $PackageVersion)
        Invoke-WebRequestChecked -Uri "$baseUri/$assetName.sha256" -OutFile $checksumPath
        $expected = Get-ChecksumFromFile $checksumPath
        Invoke-WebRequestChecked -Uri "$baseUri/$assetName" -OutFile $zipPath
        $actual = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) {
            throw ((T 'pkg.checksum_mismatch') -f $expected, $actual)
        }
        Expand-PackageArchive -ArchivePath $zipPath -Destination $tempRoot
        if (-not (Test-LocalBundleRoot $tempRoot)) {
            throw (T 'pkg.incomplete')
        }
        $manifestVersion = Get-PackageVersion $tempRoot
        if ($manifestVersion -ne $PackageVersion) {
            throw ((T 'pkg.version_mismatch') -f $manifestVersion, $PackageVersion)
        }
        $verifyCode = Invoke-VerifyBundle $tempRoot
        if ($verifyCode -ne 0) {
            throw ((T 'pkg.verify_failed') -f $verifyCode)
        }
        $expected | Set-Content -LiteralPath (Join-Path $tempRoot '.verified') -Encoding ASCII
        Move-Item -LiteralPath $tempRoot -Destination $final
        Write-Ok ((T 'pkg.cached') -f $final)
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
            throw ((T 'pkg.local_version_conflict') -f $localVersion, $explicit)
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
        Write-Warn ((T 'pkg.uninstall_cached') -f $highest)
        return (Find-CachedPackage $highest)
    }
    if ($InstalledVersion) {
        Write-Warn ((T 'pkg.uninstall_download') -f $InstalledVersion)
        return (Install-PackageVersion (Normalize-Version $InstalledVersion))
    }
    try {
        return (Get-Package)
    }
    catch {
        throw (T 'pkg.uninstall_no_tool')
    }
}

function Test-OrcaCheckout {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $false
    }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    try {
        $top = & git -C $resolved rev-parse --show-toplevel 2>$null
    }
    catch {
        return $false
    }
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

function Test-OrcaSourceRoot {
    param([string]$Path)
    if (-not (Test-OrcaCheckout $Path)) {
        return $false
    }
    $packageJson = Join-Path $Path 'package.json'
    if (Test-Path -LiteralPath $packageJson -PathType Leaf) {
        try {
            $package = Get-Content -LiteralPath $packageJson -Raw -ErrorAction Stop | ConvertFrom-Json
            if ($package -and ([string]$package.name).Trim() -ieq 'orca') {
                return $true
            }
        }
        catch {
        }
    }
    try {
        $remote = & git -C $Path remote get-url origin 2>$null
    }
    catch {
        return $false
    }
    if ($LASTEXITCODE -eq 0 -and $remote) {
        $url = ([string]($remote | Select-Object -First 1)).Trim()
        return [bool]($url -match 'stablyai[\\/]orca(\.git)?/?$')
    }
    return $false
}

function Get-OrcaSourceCandidates {
    $candidates = @()
    if ($script:LocalBundleRoot) {
        $bundleParent = Split-Path -Parent $script:LocalBundleRoot
        $candidates += (Join-Path $bundleParent 'orca-dev')
        $candidates += (Join-Path $bundleParent 'orca')
    }
    $here = (Get-Location).Path
    $candidates += (Join-Path $here 'orca-dev')
    $candidates += (Join-Path $here 'orca')
    $parent = Split-Path -Parent $here
    if ($parent) {
        $candidates += (Join-Path $parent 'orca-dev')
        $candidates += (Join-Path $parent 'orca')
    }
    if ($HOME) {
        foreach ($relative in @(
            'orca-dev', 'orca', 'dev/orca', 'Dev/orca', 'projects/orca', 'Projects/orca',
            'source/repos/orca', 'repos/orca', 'code/orca', 'src/orca'
        )) {
            $candidates += (Join-Path $HOME $relative)
        }
    }
    if ($env:SystemDrive) {
        foreach ($relative in @('orca', 'orca-dev', 'dev/orca', 'src/orca', 'projects/orca')) {
            $candidates += (Join-Path "$($env:SystemDrive)\" $relative)
        }
    }
    return $candidates
}

function Find-OrcaSource {
    $found = @()
    $roots = @()
    if ($HOME) {
        $roots += $HOME
        foreach ($relative in @('source/repos', 'projects', 'Projects', 'dev', 'Dev', 'code', 'checkouts', 'workspaces', 'repos', 'src')) {
            $roots += (Join-Path $HOME $relative)
        }
    }
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }
        foreach ($child in @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue)) {
            if ($child.Name.StartsWith('.')) {
                continue
            }
            if (-not (Test-Path -LiteralPath (Join-Path $child.FullName '.git'))) {
                continue
            }
            if (Test-OrcaSourceRoot $child.FullName) {
                $found += (Resolve-Path -LiteralPath $child.FullName).Path
            }
        }
    }
    return $found
}

function Get-OrcaSourceMatches {
    $matches = @()
    foreach ($candidate in (Get-OrcaSourceCandidates)) {
        if (Test-OrcaSourceRoot $candidate) {
            $matches += (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    $matches += @(Find-OrcaSource)
    $seen = @{}
    $unique = @()
    foreach ($path in $matches) {
        if ([string]::IsNullOrWhiteSpace($path)) {
            continue
        }
        $key = $path.ToLowerInvariant()
        if (-not $seen.ContainsKey($key)) {
            $seen[$key] = $true
            $unique += $path
        }
    }
    return $unique
}

function Read-SourceChoice {
    param([string[]]$Candidates)
    Write-Host (T 'source.multiple_heading')
    for ($index = 0; $index -lt $Candidates.Count; $index++) {
        Write-Host ("  {0}) {1}" -f ($index + 1), $Candidates[$index])
    }
    while ($true) {
        $answer = Read-Host (T 'source.multiple_prompt')
        if ($null -eq $answer -or [string]::IsNullOrWhiteSpace($answer)) {
            return $Candidates[0]
        }
        $number = 0
        if ([int]::TryParse($answer.Trim(), [ref]$number) -and $number -ge 1 -and $number -le $Candidates.Count) {
            return $Candidates[$number - 1]
        }
        Write-Warn ((T 'common.invalid_choice') -f $answer)
    }
}

function Write-SourceHeadCheck {
    param([string]$Path)
    try {
        $manifest = Get-Manifest (Get-Package)
    }
    catch {
        return
    }
    $expected = [string]$manifest.upstream.baseCommit
    if ([string]::IsNullOrWhiteSpace($expected)) {
        return
    }
    try {
        $head = Get-OrcaHead $Path
    }
    catch {
        return
    }
    if ($head -ne $expected) {
        Write-Warn ((T 'source.head_mismatch') -f $Path, $head, $expected)
    }
}

function Set-ResolvedSourcePath {
    param([string]$Path, [switch]$NoPersist)
    $script:ResolvedSource = (Resolve-Path -LiteralPath $Path).Path
    if (-not $NoPersist) {
        Save-ConfigSource $script:ResolvedSource
    }
    return $script:ResolvedSource
}

function Get-OrcaHead {
    param([string]$Path)
    try {
        $head = & git -C $Path rev-parse HEAD 2>$null
    }
    catch {
        throw ((T 'source.head_unreadable') -f $Path)
    }
    if ($LASTEXITCODE -ne 0) {
        throw ((T 'source.head_unreadable') -f $Path)
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
            throw ((T 'source.target_not_empty') -f $Path)
        }
    }
    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Write-Info ((T 'source.cloning') -f $upstream.version, $Path)
    Write-Host "  git -c core.autocrlf=false clone --branch $tag --depth 1 $($upstream.repository) `"$Path`""
    & git -c core.autocrlf=false clone --branch $tag --depth 1 $upstream.repository $Path | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw ((T 'source.clone_failed') -f $LASTEXITCODE)
    }
    $head = Get-OrcaHead $Path
    if ($head -ne [string]$upstream.baseCommit) {
        throw ((T 'source.clone_head_mismatch') -f $head, $upstream.baseCommit)
    }
    Write-Ok ((T 'source.ready') -f $Path)
}

function Resolve-Source {
    param([switch]$Quiet, [switch]$NoPrompt, [switch]$AllowClone)
    if ($script:ResolvedSource) {
        return $script:ResolvedSource
    }
    $config = Read-Config

    if (-not [string]::IsNullOrWhiteSpace($Source)) {
        if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
            throw ((T 'source.explicit_missing') -f $Source)
        }
        if (-not (Test-OrcaCheckout $Source)) {
            throw ((T 'source.explicit_not_checkout') -f $Source)
        }
        return (Set-ResolvedSourcePath $Source)
    }

    $savedIgnored = $false
    if ($config.ContainsKey('source') -and -not [string]::IsNullOrWhiteSpace($config['source'])) {
        $saved = [string]$config['source']
        if (Test-Path -LiteralPath $saved -PathType Container) {
            if (Test-OrcaCheckout $saved) {
                return (Set-ResolvedSourcePath $saved)
            }
            if (-not $Quiet) {
                Write-Warn ((T 'source.not_checkout') -f $saved)
            }
        }
        elseif (-not $Quiet) {
            Write-Warn ((T 'source.saved_ignored') -f $saved)
        }
        $savedIgnored = $true
    }

    $matches = @(Get-OrcaSourceMatches)
    if ($matches.Count -gt 0) {
        $chosen = $matches[0]
        if ($matches.Count -gt 1) {
            if ($script:PromptAllowed -and -not $NoPrompt -and -not $Quiet -and
                -not [Console]::IsInputRedirected) {
                $chosen = Read-SourceChoice -Candidates $matches
            }
            elseif (-not $Quiet) {
                Write-Warn ((T 'source.multiple_auto') -f $chosen)
            }
        }
        if (-not $Quiet) {
            Write-Info ((T 'source.discovered') -f $chosen)
            Write-SourceHeadCheck $chosen
        }
        return (Set-ResolvedSourcePath $chosen -NoPersist:$savedIgnored)
    }

    if ($Quiet -or $NoPrompt) {
        return $null
    }

    if ($AllowClone) {
        $destination = if ($HOME) { Join-Path $HOME 'orca-dev' } else { Join-Path (Get-Location).Path 'orca-dev' }
        if (Test-Path -LiteralPath $destination) {
            $existing = @(Get-ChildItem -LiteralPath $destination -Force -ErrorAction SilentlyContinue)
            if ($existing.Count -gt 0) {
                throw ((T 'source.clone_dest_taken') -f $destination)
            }
        }
        $package = Get-Package
        $manifest = Get-Manifest $package
        Write-Info ((T 'source.auto_clone') -f $manifest.upstream.version, $destination)
        try {
            Initialize-OrcaSource -PackageRoot $package -Path $destination
        }
        catch {
            if (Test-Path -LiteralPath $destination) {
                Remove-Item -LiteralPath $destination -Recurse -Force -ErrorAction SilentlyContinue
            }
            throw
        }
        return (Set-ResolvedSourcePath $destination -NoPersist:$savedIgnored)
    }

    if ($DryRun) {
        throw (T 'source.dry_run_requires_existing')
    }
    throw ((T 'source.install_hint') -f $script:OrcaRepository)
}

function Get-InstalledRecord {
    param([string]$SourcePath)
    try {
        $gitDir = & git -C $SourcePath rev-parse --absolute-git-dir 2>$null
    }
    catch {
        return $null
    }
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
        throw ((T 'source.state_unreadable') -f $statePath)
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
    Write-Info (T 'build.status_modified')
    Write-Warn (T 'build.required')
    Write-Host (T 'build.heading')
    Write-Host "  cd `"$SourcePath`""
    Write-Host '  pnpm install --frozen-lockfile'
    Write-Host '  pnpm build'
    Write-Host (T 'build.dev_hint')
}

function Invoke-Build {
    param([string]$SourcePath)
    $pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
    if (-not $pnpm) {
        Write-Err (T 'build.pnpm_missing')
        return 1
    }
    Push-Location -LiteralPath $SourcePath
    try {
        & pnpm install --frozen-lockfile | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Err ((T 'build.install_failed') -f $LASTEXITCODE)
            return $LASTEXITCODE
        }
        & pnpm build | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Err ((T 'build.failed') -f $LASTEXITCODE)
            return $LASTEXITCODE
        }
        Write-Ok (T 'build.done')
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
    $answer = Read-Host (T 'build.question')
    if ($null -ne $answer -and $answer.Trim() -match '^(e|evet|y|yes)$') {
        [void](Invoke-Build $SourcePath)
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

function Select-Packs {
    param($Manifest)
    $packs = @($Manifest.packs)
    if ($packs.Count -eq 0) {
        return @()
    }
    $selected = @{}
    foreach ($pack in $packs) {
        $selected[$pack.id] = $true
    }
    while ($true) {
        Write-Host ''
        Write-Host (T 'packs.heading') -ForegroundColor Cyan
        for ($index = 0; $index -lt $packs.Count; $index++) {
            $pack = $packs[$index]
            $mark = ' '
            if ($selected[$pack.id]) {
                $mark = 'x'
            }
            $description = $pack.description
            if ((Get-Lang) -eq 'en' -and $pack.descriptionEn) {
                $description = [string]$pack.descriptionEn
            }
            Write-Host ("  [{0}] {1}) {2}" -f $mark, ($index + 1), $pack.label)
            Write-Host ("       {0}" -f $description) -ForegroundColor DarkGray
        }
        Write-Host ''
        $answer = Read-Host (T 'packs.prompt')
        if ($null -eq $answer) {
            throw (T 'common.cancel')
        }
        $answer = $answer.Trim()
        if ($answer -eq '') {
            $chosen = @($packs | Where-Object { $selected[$_.id] } | ForEach-Object { $_.id })
            if ($chosen.Count -eq 0) {
                Write-Warn (T 'packs.empty')
                continue
            }
            return $chosen
        }
        if ($answer -match '^(a|all|tumu)$') {
            foreach ($pack in $packs) { $selected[$pack.id] = $true }
            continue
        }
        if ($answer -match '^(n|none|hicbiri)$') {
            foreach ($pack in $packs) { $selected[$pack.id] = $false }
            continue
        }
        if ($answer -match '^(q|quit|cikis)$') {
            throw (T 'common.cancel')
        }
        $number = 0
        if ([int]::TryParse($answer, [ref]$number) -and $number -ge 1 -and $number -le $packs.Count) {
            $pack = $packs[$number - 1]
            $selected[$pack.id] = -not $selected[$pack.id]
            continue
        }
        Write-Warn ((T 'common.invalid_choice') -f $answer)
    }
}

function Invoke-InstallAction {
    param(
        [switch]$DryRun,
        [switch]$SelectPacks
    )
    Assert-Git
    $package = Get-Package
    $manifest = Get-Manifest $package
    Write-Host ((T 'action.package_version') -f $manifest.package.version)
    Write-Host ((T 'action.target_base') -f $manifest.upstream.version, $manifest.upstream.baseCommit)
    $chosenPacks = @()
    if ($Pack) {
        $chosenPacks = Expand-PackValues -Values $Pack
    }
    elseif ($SelectPacks -and $script:PromptAllowed -and -not $NoPause -and -not [Console]::IsInputRedirected) {
        $chosenPacks = @(Select-Packs -Manifest $manifest)
    }
    elseif ($SelectPacks) {
        Write-Warn (T 'packs.skipped')
    }
    $source = Resolve-Source -AllowClone:(-not $DryRun)
    $arguments = @('install', '--source', $source)
    foreach ($packId in $chosenPacks) {
        $arguments += @('--pack', $packId)
    }
    if ($DryRun) {
        $arguments += '--dry-run'
    }
    $code = Invoke-Manage -PackageRoot $package -Arguments $arguments
    if ($code -eq 0) {
        if ($DryRun) {
            Write-Ok (T 'action.install_dry')
        }
        else {
            Write-Ok (T 'action.install_ok')
            Offer-Build $source
        }
    }
    return $code
}

function Invoke-UpdateAction {
    param([switch]$DryRun)
    Assert-Git
    $source = Resolve-Source -NoPrompt
    if (-not $source) {
        throw (T 'source.required_hint')
    }
    $record = Get-InstalledRecord $source
    if (-not $record -or $record.status -eq 'uninstalled') {
        Write-Warn (T 'action.update_missing')
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
            Write-Ok ((T 'action.update_current') -f $targetVersion)
        }
        elseif ($DryRun) {
            Write-Ok (T 'action.update_dry')
        }
        else {
            $installedLabel = if ($installedVersion) { $installedVersion } else { (T 'common.unknown') }
            Write-Ok ((T 'action.update_ok') -f $installedLabel, $targetVersion)
            Offer-Build $source
        }
    }
    return $code
}

function Invoke-UninstallAction {
    param([switch]$DryRun)
    Assert-Git
    $source = Resolve-Source -NoPrompt
    if (-not $source) {
        throw (T 'source.required_hint')
    }
    $record = Get-InstalledRecord $source
    if (-not $record -or $record.status -eq 'uninstalled') {
        Write-Ok (T 'action.uninstall_missing')
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
            Write-Ok (T 'action.uninstall_dry')
        }
        else {
            Write-Ok (T 'action.uninstall_ok')
        }
    }
    return $code
}

function Show-Versions {
    param([string]$SourcePath)
    Write-Host ''
    Write-Info (T 'action.versions')
    if ($SourcePath) {
        $record = Get-InstalledRecord $SourcePath
        $installed = Get-InstalledVersion $record
        if ($record) {
            $installedLabel = if ($installed) { $installed } else { (T 'common.unknown') }
            Write-Host ((T 'action.installed') -f $installedLabel, $record.status)
        }
        else {
            Write-Host (T 'action.not_installed')
        }
    }
    $cached = @(Get-CachedVersions)
    if ($cached.Count -gt 0) {
        Write-Host ((T 'action.cache') -f ($cached -join ', '))
    }
    else {
        Write-Host (T 'action.cache_empty')
    }
    if ($script:LocalBundleRoot) {
        Write-Host ((T 'action.local_package') -f (Get-PackageVersion $script:LocalBundleRoot))
    }
    try {
        $latest = Get-LatestVersion
        Write-Host ((T 'action.latest') -f $latest)
    }
    catch {
        Write-Host ((T 'action.latest_failed') -f $_.Exception.Message)
    }
}

function Invoke-StatusAction {
    Assert-Git
    $source = Resolve-Source -NoPrompt
    if (-not $source) {
        Write-Warn (T 'action.no_source')
        Show-Versions $null
        return 0
    }
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
        Write-Warn (T 'action.build_note')
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
        Write-Host (T 'action.verify_no_source')
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
    $answer = Read-Host (T 'action.confirm_uninstall')
    if ($null -eq $answer) {
        return $false
    }
    return $answer.Trim() -match '^(e|evet|y|yes)$'
}

function Change-SourcePath {
    $previous = $script:ResolvedSource
    $entered = Read-Host (T 'action.new_source')
    if ([string]::IsNullOrWhiteSpace($entered)) {
        Write-Warn (T 'action.source_unchanged')
        return
    }
    $entered = $entered.Trim()
    if (Test-OrcaCheckout $entered) {
        $script:ResolvedSource = (Resolve-Path -LiteralPath $entered).Path
        Save-ConfigSource $script:ResolvedSource
        Write-Ok ((T 'action.source_saved') -f $script:ResolvedSource)
        return
    }
    $answer = Read-Host (T 'action.change_clone_question')
    if ($null -eq $answer -or $answer.Trim() -notmatch '^(e|evet|y|yes)$') {
        Write-Warn ((T 'action.source_unchanged_detail') -f $previous)
        return
    }
    try {
        $package = Get-Package
        Initialize-OrcaSource -PackageRoot $package -Path $entered
        $script:ResolvedSource = (Resolve-Path -LiteralPath $entered).Path
        Save-ConfigSource $script:ResolvedSource
        Write-Ok ((T 'action.source_saved') -f $script:ResolvedSource)
    }
    catch {
        $script:ResolvedSource = $previous
        Write-Err ((T 'action.source_unchanged_detail') -f $_.Exception.Message)
    }
}

function Invoke-Rehearsal {
    Write-Host (T 'action.rehearsal_install')
    Write-Host (T 'action.rehearsal_update')
    Write-Host (T 'action.rehearsal_uninstall')
    $choice = Read-Host (T 'action.rehearsal_prompt')
    if ($null -eq $choice) {
        return 0
    }
    switch ($choice.Trim()) {
        '1' { return Invoke-InstallAction -DryRun -SelectPacks }
        '2' { return Invoke-UpdateAction -DryRun }
        '3' { return Invoke-UninstallAction -DryRun }
        default {
            Write-Warn ((T 'common.invalid_choice') -f $choice)
            return 0
        }
    }
}

function Select-Language {
    $answer = Read-Host (T 'lang.prompt')
    if ($null -eq $answer) {
        Write-Warn (T 'lang.invalid')
        return $null
    }
    $answer = $answer.Trim()
    $chosen = Normalize-Lang $answer
    if (-not $chosen) {
        switch ($answer) {
            '1' { $chosen = 'tr' }
            '2' { $chosen = 'en' }
        }
    }
    if (-not $chosen) {
        Write-Warn (T 'lang.invalid')
        return $null
    }
    $script:Language = $chosen
    Save-ConfigLang $chosen
    return $chosen
}

function Resolve-Language {
    if ($script:LangExplicit) {
        return (Normalize-Lang $Lang)
    }
    $config = Read-Config
    if ($config.ContainsKey('lang')) {
        return [string]$config['lang']
    }
    if ($Action -eq 'menu' -and -not $NoPause -and -not [Console]::IsInputRedirected) {
        $chosen = Select-Language
        if ($chosen) {
            Write-Ok ((T 'lang.saved') -f (T "lang.$chosen"))
            return $chosen
        }
    }
    return 'tr'
}

function Show-Header {
    Write-Host ''
    Write-Host (T 'menu.title') -ForegroundColor Cyan
    if ($script:LocalBundleRoot) {
        Write-Host ((T 'menu.package_local') -f $script:LocalBundleRoot)
    }
    else {
        Write-Host ((T 'menu.package_remote') -f $script:PackagesRoot)
    }
    $sourceLabel = T 'menu.source_pending'
    if ($script:ResolvedSource) {
        $sourceLabel = $script:ResolvedSource
    }
    elseif ($Source) {
        $sourceLabel = $Source
    }
    Write-Host ((T 'menu.orca') -f $sourceLabel)
    if ($script:ResolvedSource) {
        $record = Get-InstalledRecord $script:ResolvedSource
        $installed = Get-InstalledVersion $record
        if ($record) {
            $installedLabel = if ($installed) { $installed } else { (T 'common.unknown') }
            Write-Host ((T 'menu.installed') -f $installedLabel, $record.status)
        }
        else {
            Write-Host (T 'menu.not_installed')
        }
    }
    $cached = @(Get-CachedVersions)
    if ($cached.Count -gt 0) {
        Write-Host ((T 'menu.cache') -f ($cached -join ', '))
    }
    if ($script:LatestVersion) {
        Write-Host ((T 'menu.latest') -f $script:LatestVersion)
    }
    Write-Host ''
}

function Show-Menu {
    while ($true) {
        Show-Header
        Write-Host (T 'menu.install')
        Write-Host (T 'menu.update')
        Write-Host (T 'menu.uninstall')
        Write-Host (T 'menu.status')
        Write-Host (T 'menu.verify')
        Write-Host (T 'menu.rehearsal')
        Write-Host (T 'menu.source')
        Write-Host (T 'menu.lang')
        Write-Host (T 'menu.exit')
        Write-Host ''

        $choice = Read-Host (T 'menu.prompt')
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
                '2' { $code = Invoke-UpdateAction }
                '3' {
                    if (Confirm-Uninstall) {
                        $code = Invoke-UninstallAction
                    }
                    else {
                        Write-Warn (T 'action.uninstall_cancelled')
                        $code = 0
                    }
                }
                '4' { $code = Invoke-StatusAction }
                '5' { $code = Invoke-VerifyAction }
                '6' { $code = Invoke-Rehearsal }
                '7' { Change-SourcePath; $code = 0 }
                '8' { [void](Select-Language); $code = 0 }
                default {
                    Write-Warn ((T 'common.invalid_choice') -f $choice)
                }
            }
        }
        catch {
            Write-Err ((T 'common.error') -f $_.Exception.Message)
            $code = 1
        }

        if ($code -ne 0) {
            Write-Err ((T 'common.action_failed') -f $code)
        }
        if (-not $NoPause) {
            [void](Read-Host (T 'common.pause'))
        }
    }
}

function Invoke-Main {
    $script:Language = Resolve-Language
    $script:LocalBundleRoot = Find-LocalBundleRoot
    if ($script:LocalBundleRoot) {
        Write-Host ((T 'start.local_bundle') -f $script:LocalBundleRoot)
    }

    if ($Action -eq 'menu') {
        return Show-Menu
    }
    if ($DryRun -and $Action -notin @('install', 'update', 'uninstall')) {
        Write-Warn (T 'start.dry_run_ignored')
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
    Write-Err ((T 'common.error') -f $_.Exception.Message)
    $exitCode = 1
}

$exitCode = [int]$exitCode
if ($script:HasScriptPath) {
    exit $exitCode
}
$global:LASTEXITCODE = $exitCode
