# Orca Advanced Orchestration kullanım rehberi

Bu paket, Orca v1.4.246 kaynak koduna otomatik görev yürütme değişiklikleri uygular. Bağımsız bir uygulama veya plugin değildir; kurulumdan sonra kaynak checkout'un derlenmesi gerekir.

[English](USAGE.en.md) · [README](../README.md) · [Teknik tasarım](DESIGN.md) · [Doğrulama](VALIDATION.md)

## Hızlı başlangıç

Windows PowerShell'de, herhangi bir çalışma dizininden:

```powershell
irm https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/v1.1.0/install.ps1 | iex
```

Menüden **Kur** seçin. Betik:

1. Python 3.9+ ve Git'i kontrol eder.
2. Son kararlı GitHub Release sürümünü bir kez çözümler (veya `-Version`).
3. Yalnızca kurulum dosyalarını içeren sürümlenmiş ZIP'i ve `.sha256` dosyasını indirir.
4. SHA-256 ile ZIP'i, ardından `bundle-manifest.json` içindeki 133 dosya hash'ini doğrular (patch ve örnek dahil toplam 135 paket dosyası).
5. Paketi `%LOCALAPPDATA%\OrcaAdvancedOrchestration\packages\<sürüm>\` altında önbelleğe alır.
6. Orca kaynak checkout'unu bulur; yoksa desteklenen upstream sürümünü klonlamayı önerir.
7. Hedef `HEAD` değerini paketin taban commit'i ile karşılaştırır.
8. Yedekleyip değişiklikleri uygular.

Tam repo, Git geçmişi, testler veya geliştirme dosyaları indirilmez.

### Gereksinimler

- Windows PowerShell 5.1 veya PowerShell 7.
- Python 3.9+ (`py -3`, `python` veya `python3`).
- Git.
- Derleme için Node.js 24 ve Orca'nın `package.json` içinde sabitlediği pnpm sürümü.

### Orca kaynak checkout'u

Mevcut bir checkout `-Source` ile verilebilir. Verilmezse araç konumu kendisi bulur; sıra:

1. Kayıtlı kaynak yolu (`config.json`).
2. Yerel paket deposunun yanında, çalışma dizininde ve üst dizininde `orca-dev` / `orca`.
3. `%USERPROFILE%` altındaki yaygın geliştirme konumları (`orca-dev`, `dev\orca`, `projects\orca`, `source\repos\orca` vb.) ve `C:\orca`, `C:\dev\orca` gibi sürücü kökleri.
4. `%USERPROFILE%` ve bilinen geliştirme köklerinin bir alt dizinindeki, `package.json` adı `orca` olan veya `origin` uzak adresi `stablyai/orca` olan Git checkout'u.

Hiçbiri bulunamazsa **Kur** işlemi desteklenen sürümü `%USERPROFILE%\orca-dev` konumuna soru sormadan klonlar:

```powershell
git -c core.autocrlf=false clone --branch v1.4.246 --depth 1 https://github.com/stablyai/orca.git <yol>
```

Klonlama başarısız olursa yarım kalan dizin silinir. Klonlanan `HEAD`, `bundle-manifest.json` içindeki `upstream.baseCommit` değilse araç otomatik `reset`/`checkout` yapmaz; açık hata verir.

- **`-Source` açıkça verilirse** yalnızca o yol kullanılır. Yol yoksa veya checkout değilse araç hemen hata verir; otomatik bulma veya klonlamaya düşmez.
- **Kayıtlı yol geçici olarak erişilemezse** (`config.json`) ayar silinmez; yol o çalıştırmada yok sayılır ve otomatik bulma denenir.
- **Birden fazla aday bulunursa** etkileşimli menüde numarayla seçim sorulur; etkileşimsiz çalıştırmada ilk aday kullanılır ve uyarı yazılır. Seçilen checkout'un `HEAD` değeri paketin taban commit'iyle uyuşmuyorsa uyarı verilir.
- **Güncelle** ve **Kaldır** otomatik klonlama yapmaz ve yol sormaz; kaynak bulunamazsa `-Source` isteyen net hata verir. **Durum** kaynak yokken yalnızca paket ve önbellek bilgisini gösterir.

## Menü

```text
  1) Kur (bileşen seçimiyle)
  2) Güncelle
  3) Kaldır
  4) Durum ve sürümler
  5) Doğrula
  6) İşlem provası (dry-run)
  7) Orca kaynak yolunu değiştir
  8) Dil değiştir (Türkçe/English)
  0) Çıkış
```

- **Kur (bileşen seçimiyle)**: Paketi indirir/doğrular, ardından **Orchestrator** ve **Todo** bileşenlerini ayrı ayrı seçtirir. Seçilen dosya grubu kaynağa uygulanır.
- **Güncelle**: Kurulu sürümle hedef sürümü karşılaştırır; aynıysa no-op. Yeni paketi tamamen indirip doğrular, ön kontrolleri yapar ve işlemi tek kilit altında yürütür.
- **Kaldır**: Özgün dosyaları geri yükler; sonradan değiştirilenleri kurtarma arşivine alır. Orca kaynak dizinini silmez. Onay ister.
- **Durum ve sürümler**: Kurulum durumunu, paket sürümünü, yedekleri, yerel değişiklikleri, önbellekteki sürümleri ve erişilebiliyorsa son kararlı sürümü gösterir.
- **Doğrula**: Paket hash'lerini ve varsa kurulum/yedek kaydını doğrular.
- **İşlem provası**: Kurulum, güncelleme veya kaldırmayı `--dry-run` ile gösterir; hiçbir dosya değişmez.
- **Orca kaynak yolunu değiştir**: Yeni yolu doğrular ve kalıcı kaydeder. İptal edilirse önceki yol korunur.
- **Dil değiştir**: Arayüzü Türkçe veya English yapar ve seçimi `config.json` içinde saklar. İlk menü açılışında dil sorulur; `-Lang tr|en` yalnızca o çalıştırma için geçerlidir.

`irm | iex` altında betik çağıranın shell'ini `exit` ile kapatmaz. `-File` ile çalıştırıldığında işlem kodu döndürür.

### Bileşen (pack) seçimi

Manifest iki bağımsız pack tanımlar:

- `orchestration`: otomatik orkestrasyon, CLI/RPC, migration ve karar kapıları (81 dosya).
- `todo`: ajan panosunun soluna kalıcı Todo sütunu (52 dosya).

Kurulum menüsünde numaraya basarak bileşenleri açıp kapatabilirsiniz. Enter seçili bileşenleri kurar; `A` tümünü, `N` hiçbirini seçer. Etkileşimsiz kurulumda `-Pack` verilmezse tüm pack'ler kurulur. Kurulu seçimi değiştirmek için önce `uninstall`, sonra yeni seçimle `install` gerekir.

```powershell
.\install.ps1 -Action install -Source C:\orca-dev -Pack todo
.\install.ps1 -Action install -Source C:\orca-dev -Pack orchestration,todo
```

`update` mevcut pack seçimini korur. Todo maddeleri ajan başlatmaz; her çalışma alanı için kalıcı listede tutulur.

## Etkileşimsiz kullanım

```powershell
.\install.ps1 -Action install -Source C:\orca-dev
.\install.ps1 -Action install -Source C:\orca-dev -Version 1.1.0 -DryRun
.\install.ps1 -Action install -Source C:\orca-dev -Pack todo
.\install.ps1 -Action update -Source C:\orca-dev
.\install.ps1 -Action update -Source C:\orca-dev -Version 1.1.0 -DryRun
.\install.ps1 -Action status -Source C:\orca-dev
.\install.ps1 -Action verify
.\install.ps1 -Action uninstall -Source C:\orca-dev
```

- `-Version` verilmezse GitHub Releases'teki son kararlı sürüm bir kez çözümlenir.
- `-Source` verilmezse kayıtlı yol ve bilinen konumlar denenir; bulunamazsa etkileşimsiz modda açık hata verilir.
- `-RepoRoot` yerel paket deposunu belirtir; bu seçenek indirmeyi atlar.
- `-Lang tr|en` arayüz dilini belirler; kayıtlı dil ayarını değiştirmez.
- `-NoPause` işlem sonu beklemesini kapatır.
- `-DryRun` yalnızca install, update ve uninstall ile anlamlıdır.

Yalnızca yerel paket deposundan çalıştırmak için:

```powershell
cd orca-advanced-orchestration
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -RepoRoot . -Action install -Source ..\orca-dev
```

Yerel modda `-Version` verilemez; sürüm `bundle-manifest.json` içinden okunur.

## Önbellek, çevrimdışı kullanım ve bütünlük

```text
%LOCALAPPDATA%\OrcaAdvancedOrchestration\
  config.json
  packages\<sürüm>\
    .verified
    bundle-manifest.json
    install.ps1
    scripts\...
    changes\...
  downloads\
```

- ZIP indirildikten sonra SHA-256 dosyasındaki değerle karşılaştırılır.
- Arşiv yolları dizin dışına çıkamaz (`..`, kök yol, sürücü sözdizimi reddedilir).
- Paket hash'leri doğrulandıktan sonra `.verified` yazılır.
- Aynı sürüm tekrar kullanılırsa önbellekten alınır; sürüm işlem başına bir kez çözümlenir.
- Kaldırma, önbellekteki yönetim aracıyla ağ bağlantısı olmadan çalışabilir. Önbellek boşsa ve kurulu sürüm bilinmiyorsa açık hata verilir.

## Kurulum sonrası derleme

Kurulum yalnızca kaynak dosyaları değiştirir. Araç derleme yapmaz, uygulamayı başlatmaz, veritabanı migrasyonu çalıştırmaz ve kurulu binary'yi değiştirmez. Kaynağın değiştirilmiş olması ile uygulamanın kullanıma hazır olması ayrı durumlardır.

```powershell
cd <orca-kaynak>
pnpm install --frozen-lockfile
pnpm build
```

Geliştirme için:

```powershell
pnpm dev --worktree-profile
```

Kurulum/güncelleme sonrası menü derleme komutlarını gösterir ve etkileşimli modda çalıştırmayı önerir.

## Doğrudan Python aracı

PowerShell betiği Python aracını çağırır. Aynı işlemler doğrudan da yapılabilir:

```sh
python scripts/manage_installation.py install --source ../orca-dev --dry-run
python scripts/manage_installation.py install --source ../orca-dev
python scripts/manage_installation.py update --source ../orca-dev --dry-run
python scripts/manage_installation.py update --source ../orca-dev
python scripts/manage_installation.py status --source ../orca-dev
python scripts/manage_installation.py status --source ../orca-dev --json
python scripts/manage_installation.py verify --source ../orca-dev
python scripts/manage_installation.py uninstall --source ../orca-dev --dry-run
python scripts/manage_installation.py uninstall --source ../orca-dev
```

`--bundle` doğrudan komut satırında yoktur; araç kendi paket kökünü (`bundle-manifest.json` üst dizini) kullanır. Önbellekteki bir sürümü kullanmak için o sürümün dizinindeki `scripts/manage_installation.py` dosyasını çalıştırın; kaldırma güncel paket manifestine ihtiyaç duymaz.

## Kurulum işleyişi

1. Manifest, patch, örnek ve 133 dosyanın SHA-256 değerlerini doğrular.
2. Hedefin Git checkout'unu, taban commit'i, yönetilen yolları ve symlink/junction durumunu kontrol eder.
3. Patch'i mevcut etkilenen dosyaların geçici kopyalarına uygular. Patch ile uyumlu yerel düzenlemeler korunur; uygulanamayan patch hedefi değiştirmeden durur.
4. Mevcut yönetilen dosyaların ham baytlarını ve izinlerini checkout'un Git veri dizini altında yedekler, hash'leri doğrular ve kalıcı JSON günlük yazar.
5. Dosyaları atomik olarak değiştirir, ilerlemeyi kaydeder ve sonuç hash'lerini doğrular.
6. Yazma hatasında değiştirilmiş dosyaları ilk yedekten geri alır. Geri alma tamamlanamazsa `recovery_required` işaretler ve başarı iddia etmez.

Yedek konumu checkout'a özgüdür:

```text
<git-dizini>/orca-advanced-orchestration/<kurulum-kimliği>/backup
```

Bağlı (linked) worktree kullanılıyorsa Git'in o worktree için döndürdüğü veri dizini kullanılır.

## Güncelleme işleyişi

- Kurulu kayıt yoksa veya durum `uninstalled` ise güncelleme reddedilir; Kur kullanılmalıdır.
- Paket fingerprint'i aynıysa no-op; hiçbir dosya veya günlük yazılmaz.
- Aynı sürüm farklı içerikle gelirse sessizce değiştirilmez; yeni sürüm numarası istenir.
- Kurulum sonrası yerel olarak değiştirilmiş/eksik dosya varsa güncelleme hiçbir dosyaya dokunmadan reddedilir.
- Kurulu paketin ve yeni paketin upstream tabanı aynı olmalıdır. Farklı taban veya checkout `HEAD` uyuşmazlığında otomatik reset/checkout yapılmaz.
- Yeni dosya seti eklenen/kaldırılan yolları destekler. Yeni yönetilen bir yol önceden varsa özgün içerik olarak yedeklenir.
- İşlem öncesi önceki kurulu sürümün baytları, hedef dosyalara dokunmadan önce doğrulanmış bir geri alma anlık görüntüsüne alınır.
- Tek `installation.lock` ve kalıcı günlük kullanılır. Hata veya kesintide önceki kurulu sürüm geri getirilir; kesinti sonrası düzenlenmiş yabancı içerik önce kurtarma arşivine alınır.
- Başarılı güncelleme yeni bir kümülatif özgün yedek oluşturur; ilk kurulum öncesi özgün yedek dizini korunur.

Güncelleme sırasında `.git` altında geçici olarak `updating` durumu görülebilir. Bir sonraki komut önce bu günlüğü uzlaştırır ve komutun yeniden çalıştırılmasını ister.

## Durum ve doğrulama

`status` salt okunurdur; kurulum kimliği, paket sürümü, yedek, kurtarma arşivleri, kurulum sonrası değişen/eksik dosyalar ve bekleyen kesintiyi gösterir. `--json` makine okunabilir çıktı verir.

`verify` paket hash'lerini ve kurulum kaydını doğrular: yönetilen dosyaların kurulu hash'leri, yedek manifesti ve yedek baytları. `recovery_required` durumunda otomatik devam etmez.

## Kaldırma ve kurtarma arşivi

`uninstall` güncel manifeste değil, kurulum anında kaydedilen listeye ve özgün yedeğe dayanır. Paket sonradan silinse veya güncellense bile çalışır.

1. Checkout kimliğini, kayıtlı yolları ve yedek hash'lerini doğrular.
2. Kurulumdan sonra değiştirilen dosyaları kurtarma arşivine alır; uninstall öncesi silinmiş özgün dosyaları yokluk kaydıyla yazar.
3. Arşivi tekrar doğrulamadan hedefe dokunmaz.
4. Özgün dosyaları bayt ve izin olarak geri yükler.
5. Kurulumun eklediği dosyaları kaldırır; sonradan düzenlenmiş olanları önce arşivler.
6. Yalnızca kurulumun oluşturduğu ve boş kalan dizinleri temizler.
7. Sonuç hash'lerini doğrular ve `uninstalled` yazar.

Kurtarma arşivi:

```text
<git-dizini>/orca-advanced-orchestration/<kurulum-kimliği>/recovery/<arşiv-kimliği>/
```

`manifest.json` her dosyanın neden arşivlendiğini, hash'ini ve arşiv içi yolunu kaydeder. İlk yedek ve arşivler uninstall sonrasında silinmez. Tekrar `uninstall` güvenli no-op'tur. `uninstall` Orca kaynak dizinini silmez.

## Kesinti, kilit ve güvenlik

Kayıt durumları: `installing`, `installed`, `updating`, `uninstalling`, `uninstalled`, `recovery_required`.

- Kesilen işlem sonraki çağrıda uzlaştırılır; yeni mutasyon aynı çağrıda başlamaz.
- Kesilen kurulum özgün dosyalara, kesilen güncelleme önceki kurulu sürüme döner; kesilen uninstall kaldığı yerden devam eder.
- `recovery_required` durumunda araç otomatik devam etmez; günlükteki yolu ve dosyaları incelemek gerekir.
- Aynı checkout'ta eşzamanlı işlem kilit ile engellenir. Eski kilit yalnızca sahibinin çalışmadığı kanıtlanabiliyorsa kurtarılır.
- Manifest, kayıt ve hedef yolları checkout dışına çıkacak şekilde veya symlink/junction üzerinden yazacak şekilde reddedilir.
- `--dry-run` hiçbir dosya, yedek, kilit veya günlük oluşturmaz; `status` her zaman salt okunurdur.

## Release paketi üretme ve yayımlama

Yerel üretim:

```powershell
python scripts/build_release.py --output dist
```

Çıktılar:

```text
dist/orca-advanced-orchestration-1.1.0.zip
dist/orca-advanced-orchestration-1.1.0.zip.sha256
```

Arşiv yalnızca şunları içerir: `install.ps1`, `bundle-manifest.json`, `LICENSE`, yönetim Python modülleri, patch, örnek ve 133 değişiklik anlık görüntüsü. Testler, `orca-source/`, `.git`, README ve geliştirme dosyaları dışarıdadır. ZIP deterministik üretilir.

Sürüm kaynağı `bundle-manifest.json` içindeki `package.version` alanıdır. Sürüm artırılmadan aynı etiketle yayımlamayın.

GitHub Actions (`.github/workflows/release.yml`):

- `v*` etiketiyle veya manuel çalışır.
- Paket doğrulamasını ve Python testlerini çalıştırır.
- Etiket sürümünü `package.version` ile karşılaştırır.
- ZIP ve `.sha256` üretir; workflow artifact'i yükler.
- Etiketli çalışmada GitHub Release oluşturur/günceller.

Henüz yayımlanmış release yoksa `irm` ile gerçek indirme çalışmaz. Bu durumda `-Version` ve önceden doldurulmuş önbellek ile çevrimdışı doğrulama yapılabilir.

## Manuel kurulum

Otomatik aracı kullanmak istemiyorsanız:

```sh
cd orca-dev
git rev-parse HEAD
git switch -c feature/automatic-orchestration
git apply --check ../orca-advanced-orchestration/patches/automatic-orchestration.patch
git apply ../orca-advanced-orchestration/patches/automatic-orchestration.patch
```

`git rev-parse HEAD` çıktısı taban commit ile aynı olmalıdır. Manuel yöntem yedek, günlük, durum takibi veya otomatik geri yükleme sağlamaz.

## Sınırlar

- Araç Orca'yı derlemez, başlatmaz veya kurulu paketi değiştirmez.
- Diğer Orca sürümlerine uygulanabilirlik doğrulanmadı; farklı upstream tabanında otomatik geçiş yapılmaz.
- Güncelleme, yönetilen dosyalarda kurulum sonrası yerel değişiklik varsa reddedilir. Önce değişikliği geri alın veya kaldırıp yeniden kurun.
- macOS/Linux PowerShell davranışı bu depoda Windows kadar kapsamlı doğrulanmadı.

## Lisans ve kaynak

Çalışma, Orca v1.4.246 çekirdeğine dayanır. Paket içindeki Orca kaynakları ve uyarlamaları [MIT lisansı](../LICENSE) kapsamındadır; upstream telif bildirimi korunmuştur. Bu depo resmi Orca projesiyle bağlılık veya onay iddiası taşımaz.
