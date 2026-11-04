# Orca Advanced Orchestration

Orca'da Codex ve Claude gibi ajanların görevlerini otomatik sıraya koyar. İş akışını bir kez tanımlarsınız; bir görev bitince sıradaki başlar, bağımsız görevler paralel çalışır.

Örnek: **Kod yaz → Test ve incelemeyi paralel çalıştır → Gerekirse düzelt → Sonucu raporla.**

## Ne sağlar?

- Ajanları tek tek başlatma ve sürekli durum kontrolü ihtiyacını azaltır.
- Görev bağımlılıklarını, çalışma alanı paylaşımını ve inceleme kararlarını yönetir.
- Akışı duraklatma, sürdürme ve iptal etme desteği sunar.
- Rutin geçişlerdeki gereksiz koordinatör çağrılarını azaltmayı hedefler; ajanlar token tüketmeye devam eder.

## Kurulum

Repoyu klonlamadan Windows PowerShell'de tek komut:

```powershell
irm https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/main/install.ps1 | iex
```

Menüden **Kur** seçin. Betik yalnızca kurulum için gereken dosyaları içeren sürümlenmiş ZIP'i GitHub Releases'ten indirir, SHA-256 ve paket hash'lerini doğrular, `%LOCALAPPDATA%\OrcaAdvancedOrchestration` altında sürümüne göre önbelleğe alır. Tam repo, Git geçmişi, testler veya geliştirme dosyaları indirilmez.

Gereksinimler: **Python 3.9+** ve **Git**. Orca kaynak checkout'u yoksa menü, paketin desteklediği upstream sürümü klonlamayı önerebilir. Klonlanan `HEAD`, paketin beklediği taban commit'ten farklıysa araç otomatik `reset`/`checkout` yapmaz; açık hata verir.

Bu depo bağımsız uygulama veya plugin değildir: **Orca v1.4.246 kaynak kodunu değiştirir**. Kurulumdan sonra kaynak değişmiş olur; yeni davranışın çalışması için ayrıca derleme gerekir:

```powershell
cd <orca-kaynak>
pnpm install --frozen-lockfile
pnpm build
```

Menü: **Kur**, **Güncelle**, **Kaldır**, **Durum ve sürümler**, **Doğrula**, **İşlem provası**, **Orca kaynak yolunu değiştir**, **Çıkış**. Kaynak yolu kalıcı olarak kaydedilir.

Etkileşimsiz kullanım:

```powershell
# Kurulum/önbellek paketini indirip kur
irm https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/main/install.ps1 | iex

# Doğrudan eylem (yerel betik)
.\install.ps1 -Action install -Source C:\orca-dev
.\install.ps1 -Action update -Source C:\orca-dev
.\install.ps1 -Action update -Source C:\orca-dev -Version 1.0.0 -DryRun
.\install.ps1 -Action status -Source C:\orca-dev
.\install.ps1 -Action verify
.\install.ps1 -Action uninstall -Source C:\orca-dev
```

`-Version` belirtilmezse son kararlı GitHub Release çözümlenir; sürüm işlem başına bir kez çözümlenir. `-DryRun` kurulum, güncelleme veya kaldırma provası yapar ve hiçbir dosyayı değiştirmez. `irm | iex` içinde betik çağıranın shell'ini `exit` ile kapatmaz.

## Güncelleme ve geri alma

- Kurulu sürümle hedef sürüm aynıysa güncelleme no-op'tur.
- Yeni paket tamamen indirilip doğrulanmadan hiçbir dosya değiştirilmez.
- Yerel değişiklikler, farklı upstream tabanı veya paket sürümü uyuşmazlığı önceden kontrol edilir; uyumsuzlukta otomatik reset/checkout yapılmaz.
- Güncelleme tek kilit ve kalıcı işlem günlüğüyle yürür. Hata veya kesintide önceki kurulu sürüm geri getirilir.
- İlk kurulum öncesi özgün yedek korunur. Kaldırma, özgün dosyaları geri yükler; sonradan değiştirilen dosyaları kurtarma arşivine alır ve Orca kaynak dizinini silmez.
- Önbellekteki yönetim aracı sayesinde ağ olmadan kaldırma yapılabilir.

## Paket yayımlama

Release paketi yalnızca kurulumda gereken dosyaları içerir. Yerelde üretmek için:

```powershell
python scripts/build_release.py --output dist
```

Bu komut `bundle-manifest.json` içindeki `package.version` ile sürümlenmiş ZIP ve `.sha256` dosyasını üretir. `.github/workflows/release.yml`, `v*` etiketiyle tetiklendiğinde testleri çalıştırır, etiket sürümünü manifest ile karşılaştırır ve GitHub Release'e iki dosyayı yükler. Henüz yayımlanmış bir release yoksa `irm` ile gerçek indirme çalışmaz; `-Version` ve önceden doldurulmuş önbellek ile çevrimdışı kullanılabilir.

**[Kurulum ve kullanım rehberi](docs/USAGE.md)** · [Örnek iş akışı](examples/workflow.json)

[English](README.en.md) · [Teknik tasarım](docs/DESIGN.md) · [Test sonuçları ve bilinen sınırlamalar](docs/VALIDATION.md) · [MIT lisansı](LICENSE)
