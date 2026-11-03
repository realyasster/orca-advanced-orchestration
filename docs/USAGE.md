# Orca Advanced Orchestration

Orca için geliştirdiğimiz **olay tabanlı otomatik görev yürütme sisteminin değişiklik paketi**.

[English](../README.en.md) · [Tasarım](../docs/DESIGN.md) · [Doğrulama](../docs/VALIDATION.md) · [MIT lisansı](../LICENSE)

Görev akışını bir kez tanımlayın; bağımlılıkları tamamlandıkça sıradaki ajanı Orca başlatsın. Orkestratör planlama, sorular, hatalar ve karar noktalarında devreye girsin.

Bu bağımsız depo yalnızca geliştirdiğimiz çekirdek değişikliklerini, bunların testlerini, bir örnek akışı ve belgeleri içerir. **Tam Orca kaynak deposunu veya geçmişini içermez.** Kod, Orca çekirdeğine uygulanır; tek başına çalışan bir uygulama veya plugin değildir.

## Çözdüğü problem

Bir ajanın işinin bitmesini sürekli kontrol etmek ve her normal geçişte sıradaki ajanı başlatmak için orkestratör modelini çalıştırmak gereksiz çağrılar oluşturur. Buradaki yürütücü görev bağımlılıklarını Orca runtime içinde ilerletir.

Örnek akış:

```text
Uygulama (Codex)
    ├── Test (Codex)
    └── İnceleme (Claude)
              ↓
       Gerekiyorsa karar / düzeltme
              ↓
         Sonuç raporu
```

İşçi ajanların token tüketimi devam eder. Amaç, bekleme ve öngörülebilir geçişlerdeki gereksiz **orkestratör** çağrılarını azaltmaktır; ölçülmüş bir tasarruf yüzdesi iddia edilmez.

## İçerdiği değişiklikler

- Mevcut elle yönetilen Run'larla birlikte isteğe bağlı otomatik yürütme.
- Sıralı, paralel ve birleşen görev bağımlılıkları; varsayılan iki eşzamanlı işçi.
- Sürüm kontrollü akış güncelleme; başlamış görevlerin sessizce değiştirilmemesi.
- Kalıcı yürütme olayları, yinelenen bildirimlerin ele alınması ve kesinti sonrası uzlaştırma.
- Çalışma alanı okuma/yazma zamanlaması ve önceki görev çıktılarının aktarılması.
- İnceleme karar kapıları ve en fazla iki düzeltme turu.
- Duraklatma, sürdürme ve kontrollü iptal.
- CLI, RPC, veritabanı migrasyonu, mevcut görev/ajan gösterimleri ve orchestration kılavuzu güncellemeleri.

## Depo yapısı

| Yol | İçerik |
| --- | --- |
| [`scripts/manage_installation.py`](../scripts/manage_installation.py) | Kaynak checkout için yedeklemeli install / status / uninstall aracı |
| [`install.ps1`](../install.ps1) | Windows için etkileşimli PowerShell kurulum menüsü |
| [`scripts/orca_install/`](../scripts/orca_install/) | Aracın paket doğrulama, kilit, günlük, yedek ve geri yükleme modülleri |
| [`patches/automatic-orchestration.patch`](../patches/automatic-orchestration.patch) | Upstream tabana uygulanacak gerçek değişiklikler |
| [`changes/`](../changes/) | Değişen veya eklenen 77 dosyanın uygulama sonrası halleri; özgün yollar korunur |
| [`examples/workflow.json`](../examples/workflow.json) | Uygulama → paralel test ve inceleme örneği |
| [`bundle-manifest.json`](../bundle-manifest.json) | Taban commit, kaynak commit, dosya listesi ve SHA-256 değerleri |
| [`scripts/verify_bundle.py`](../scripts/verify_bundle.py) | Paket bütünlüğü kontrolü |
| [`tests/`](../tests/) | Python standart kütüphanesiyle çalışan installer testleri |

`changes/` içindeki mevcut upstream dosyaları entegrasyonun okunabilmesi için tam halleriyle bulunur. Hangi satırların değiştiğini patch gösterir.

## Orca'ya uygulama

Hedef taban: [stablyai/orca](https://github.com/stablyai/orca), **v1.4.246**, commit `55ccff19ad4cd8ba28b6f3d2be798c1e626a2c2c`.

Otomatik araç, yalnızca **desteklenen taban commit'indeki bir Orca kaynak checkout'unu** yönetir. Kurulu/paketlenmiş Orca uygulamasını değiştirmez. Hedef checkout'un `HEAD` değeri taban commit değilse araç hiçbir dosyayı değiştirmeden reddeder.

### Otomatik kurulum (önerilen)

Paketi ve ayrı bir Orca kaynak checkout'unu hazırlayın (Python 3.9+ ve Git gerekir; üçüncü taraf Python paketi gerekmez):

```sh
git clone https://github.com/realyasster/orca-advanced-orchestration.git
git -c core.autocrlf=false clone --branch v1.4.246 --depth 1 https://github.com/stablyai/orca.git orca-dev
cd orca-advanced-orchestration
python scripts/manage_installation.py install --source ../orca-dev
```

Komutlar iki klonun aynı üst klasörde olduğunu varsayar. `--source` mutlaka checkout'un Git kök klasörü olmalıdır. Windows'ta `core.autocrlf=false` kullanılması, patch'in beklediği LF satır sonlarının korunmasını sağlar.

### PowerShell menüsü (Windows)

Depo ve `orca-dev` checkout'u hazır olduktan sonra tek komutla menüyü açabilirsiniz:

```powershell
cd orca-advanced-orchestration
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

Menüden seçim yapın:

```text
  1) Kur
  2) Durum
  3) Kaldır
  4) Kurulum provası (dry-run)
  5) Kaldırma provası (dry-run)
  6) Paketi doğrula
  7) Orca kaynak yolunu değiştir
  0) Çıkış
```

Menüde `3) Kaldır` işlem başlamadan önce onay ister; onaylanmazsa hiçbir şey yapılmaz. Doğrudan `-Action uninstall` çağrısı onay sormaz. `7) Orca kaynak yolunu değiştir` seçeneğinde işlem iptal edilirse önceki kaynak yolu korunur.

`install.ps1` yalnızca mevcut Python aracını çağırır. Depoyu veya Orca checkout'unu **klonlamaz**; ikisinin de önceden hazır olması gerekir. `-Source` verilmezse önce `..\orca-dev` aranır, bulunamazsa yol sorulur.

Doğrudan eylem seçmek için:

```powershell
.\install.ps1 -Action install -Source ..\orca-dev
.\install.ps1 -Action install -Source ..\orca-dev -DryRun
.\install.ps1 -Action status -Source ..\orca-dev
.\install.ps1 -Action uninstall -Source ..\orca-dev
.\install.ps1 -Action verify
```

`-NoPause` otomasyon için işlem sonu beklemesini kapatır; depo kökü otomatik bulunamazsa `-RepoRoot` ile belirtin.

Depo kökündeyken `irm ... | iex` de aynı menüyü açar; depo dışından çalıştırılırsa script depoyu bulamaz:

```powershell
irm https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/main/install.ps1 | iex
```

`iex` uzaktan indirilen betiği doğrudan çalıştırır; URL'yi ve betiği önce inceleyin.

Önce yapılacakları görmek için:

```sh
python scripts/manage_installation.py install --source ../orca-dev --dry-run
```

Kurulumda araç sırasıyla:

1. `bundle-manifest.json` içindeki patch, örnek ve 77 dosyanın SHA-256 değerlerini doğrular.
2. Hedefin Git checkout'unu, taban commit'i, yönetilen yolları ve symlink/junction durumunu kontrol eder.
3. Patch'i, mevcut etkilenen dosyaların geçici kopyaları üzerinde uygular. Patch ile uyumlu yerel düzenlemeler korunur; uygulanamayan patch hedefi değiştirmeden durur.
4. Yönetilen mevcut dosyaların **ham baytlarını ve izinlerini** Git veri dizini altında yedekler, yedek hash'lerini doğrular ve kalıcı bir JSON günlük yazar.
5. Dosyaları tek tek atomik olarak değiştirir, ilerlemeyi günlüğe kaydeder ve sonuç hash'lerini doğrular.
6. Yazma hatasında değiştirilmiş dosyaları ilk yedekten geri alır. Geri alma tamamlanamazsa başarı iddia etmez; kurulumu `recovery_required` olarak işaretler.

Yedek konumu checkout'a özgüdür:

```text
<git-dizini>/orca-advanced-orchestration/<kurulum-kimliği>/backup
```

`<git-dizini>` değerini `git -C ../orca-dev rev-parse --absolute-git-dir` ile bulabilirsiniz. Bağlı (linked) worktree kullanılıyorsa Git'in o worktree için döndürdüğü veri dizini kullanılır; ana checkout'un yedeğiyle karışmaz.

Araç derleme yapmaz, uygulama başlatmaz, veritabanı migrasyonu çalıştırmaz ve kurulu binary'yi değiştirmez. Kaynak dosyalar geri yüklendikten veya patch uygulandıktan sonra geliştirme sürümünü ayrıca derlemeniz gerekir.

### Kurulumdan sonra derleme

Kurulum yalnızca kaynak dosyaları değiştirir; değişikliklerin çalışması için patch uygulanmış Orca checkout'unda derleme yapılmalıdır:

```sh
cd ../orca-dev
pnpm install --frozen-lockfile
pnpm build
```

`pnpm dev --worktree-profile` geliştirme için gerekli paketleri kendisi derler. Tam masaüstü ve native derlemesi için `pnpm build` kullanın; derleme tamamlanmadan yeni otomasyon davranışı çalışmaz.

### Durum ve tekrar kurulum

```sh
python scripts/manage_installation.py status --source ../orca-dev
```

`status` salt okunurdur; kurulum kimliğini, paketi, yedek konumunu, kurtarma arşivlerini, kurulum sonrası değişen/eksik dosyaları ve varsa bekleyen kesintiyi gösterir. Hiçbir dosya, yedek, kilit veya günlük oluşturmaz.

Aynı paket zaten kuruluysa `install` tekrar çalıştırılabilir: işlem başarılı ve değişikliksiz döner, **ilk yedek asla ezilmez**. Kurulumdan sonra yerelde düzenlenmiş dosyalar da bu sırada sessizce geri alınmaz. Farklı bir paket sürümü kuruluysa önce `uninstall` çalıştırılmalıdır.

### Kaldırma ve kurtarma arşivi

```sh
python scripts/manage_installation.py uninstall --source ../orca-dev --dry-run
python scripts/manage_installation.py uninstall --source ../orca-dev
```

`uninstall`, güncel paket manifestine değil **kurulum anında kaydedilen listeye ve ilk yedeğe** dayanır; paket daha sonra güncellense veya silinse bile çalışır. İşlem sırasıyla:

1. Hedef checkout kimliğini, kayıtlı yolları ve bütün yedek dosyalarının hash'lerini doğrular. Yedek eksik/bozuksa hiçbir hedef dosya değişmez.
2. Kurulumdan sonra değiştirilmiş dosyaların mevcut halini ayrı bir kurtarma arşivine alır; uninstall öncesi silinmiş orijinal dosyaları yokluk kaydıyla arşiv manifestine yazar.
3. Arşivi tekrar okuyup hash'lerini doğrulamadan hedef dosyalara dokunmaz.
4. Kurulum öncesinde var olan dosyaları ilk yedekten **birebir** (bayt ve izin) geri yükler.
5. Kurulumun eklediği dosyaları kaldırır. Kurulumdan sonra düzenlenmiş yeni dosyalar da önce arşivlenir.
6. Yalnızca kurulumun oluşturduğu ve hâlâ boş olan dizinleri temizler; kullanıcı içeriği olan dizinleri silmez.
7. Sonuç hash'lerini ve izinleri doğrular, durumu `uninstalled` olarak yazar.

Kurtarma arşivi konumu:

```text
<git-dizini>/orca-advanced-orchestration/<kurulum-kimliği>/recovery/<arşiv-kimliği>/
```

Arşivdeki `manifest.json` her dosyanın neden arşivlendiğini (`modified-after-install` veya `missing-before-uninstall`), hash'ini ve varsa arşiv içi yolunu belirtir. İlk yedek ve kurtarma arşivleri uninstall sonrasında silinmez; yollar komut çıktısında ve `status` içinde gösterilir.

Tekrar `uninstall` güvenli bir no-op'tur. Yeni bir kurulum yeni bir kurulum kimliği ve yeni bir yedek oluşturur; eski yedekler korunur.

### Kesinti, kilit ve güvenlik

Kayıt durumları: `installing`, `installed`, `uninstalling`, `uninstalled`, `recovery_required`.

- İşlem yarıda kesilirse sonraki `install`/`uninstall` önce günlüğü uzlaştırır; yeni işlemi aynı çağrıda açmaz. Kurulum kesintisinde yedekten geri döner ve komutu tekrar çalıştırmanızı ister; uninstall kesintisi kaldığı yerden tamamlanır.
- Beklenen orijinal/kurulu içerikle eşleşmeyen dosyalar geri alma öncesinde kurtarma arşivine alınır.
- `recovery_required` durumunda araç otomatik devam etmez; günlükteki yolu ve dosyaları inceleyip gerekli düzeltmeyi siz yapmalısınız.
- Aynı checkout'ta eşzamanlı işlem kilit ile engellenir. Eski kilit yalnızca sahibinin artık çalışmadığı doğrulanabiliyorsa kurtarılır; süreç canlılığı belirsizse kilit kırılmaz.
- Manifest, kayıt ve hedef yolları checkout dışına çıkacak şekilde (`..`, mutlak yol, sürücü sözdizimi) veya symlink/junction üzerinden yazacak şekilde reddedilir.

`--dry-run` hiçbir dosya, yedek, kilit veya günlük oluşturmaz; `status` her zaman salt okunurdur.

### Manuel kurulum (alternatif)

Otomatik aracı kullanmak istemiyorsanız patch'i elle uygulayabilirsiniz:

```sh
cd orca-dev
git rev-parse HEAD
git switch -c feature/automatic-orchestration
git apply --check ../orca-advanced-orchestration/patches/automatic-orchestration.patch
git apply ../orca-advanced-orchestration/patches/automatic-orchestration.patch
```

`git rev-parse HEAD` çıktısı yukarıdaki taban commit ile aynı olmalıdır. Bu yöntem yedek, günlük, durum takibi veya otomatik geri yükleme sağlamaz; geri almak için kendi Git dalınızı kullanın. Başka Orca sürümlerine uygulanabilirlik doğrulanmadı.

## Geliştirme sürümünü çalıştırma

Bu komutlar değişiklik paketinde değil, **patch uygulanmış Orca kaynak klasöründe** çalıştırılır. Node.js 24, Orca'nın `package.json` dosyasında sabitlenen pnpm sürümü ve platforma uygun native derleme araçları gerekir. Testler için Bun sürümü `config/.bun-version` dosyasındadır. Tam kurulum ayrıntıları hedef Orca checkout'undaki `.github/CONTRIBUTING.md` dosyasındadır.

```sh
pnpm install --frozen-lockfile
pnpm dev --worktree-profile
```

Kurulu üretim uygulamasını değiştirmek yerine geliştirme profilini kullanın. Bu depo bir kurulum paketi veya yeni Orca sürümü yayımlamaz.

## Akış oluşturma

Geliştirme uygulaması açıkken, koordinatörün Orca tarafından yönetilen terminalinden aşağıdaki komutları çalıştırın. `<run_id>` yerine ilk komutun döndürdüğü kimliği yazın:

```sh
node config/scripts/orca-dev.mjs orchestration run-create --objective "Implement, test, and review a change" --mode automatic --max-parallel 2 --json
node config/scripts/orca-dev.mjs orchestration workflow-apply --run "<run_id>" --workflow-file ../orca-advanced-orchestration/examples/workflow.json --expected-version 0 --json
node config/scripts/orca-dev.mjs orchestration run-start --id "<run_id>" --json
```

Örnekteki görev talimatlarını kendi işinize göre düzenleyin. Codex ve Claude, Orca içinde kurulu ve etkin olmalıdır. `workspaceFrom`, uygulama adımının çalışma alanını sonraki işçilere aktarır. Akış dosyası yolunu terminalin çalışma klasörüne göre gerekirse değiştirin.

Koordinatör akışı başlattıktan sonra turunu bitirir; sıradaki işi başlatmak için sorgulama döngüsü çalıştırmaz. İnceleme, soru, başarısızlık veya son rapor gerektiğinde yeniden devreye girer.

## Kontroller

```sh
node config/scripts/orca-dev.mjs orchestration run-show --id "<run_id>" --json
node config/scripts/orca-dev.mjs orchestration task-list --run "<run_id>" --json
node config/scripts/orca-dev.mjs orchestration run-pause --id "<run_id>" --json
node config/scripts/orca-dev.mjs orchestration run-resume --id "<run_id>" --json
node config/scripts/orca-dev.mjs orchestration run-cancel --id "<run_id>" --json
```

Duraklatma yeni başlangıçları engeller; çalışan işçiler devam eder. İptal kontrollü durdurma ister; doğrulanmamış durma, tamamlanmış iptal olarak gösterilmez. Normal görev geçişlerini elle ilerletmek gerekmez.

## Doğrulama durumu

İlgili **7 Orca test dosyasındaki 48 test geçti**; iki dosyada `max-lines` lint hatası kaldı. Installer için **46 Python testi geçti**: temiz/kesintili kurulum, durum, kaldırma, kurtarma arşivi, CRLF, izinler, yedek doğrulama, kilit yarışı, path traversal, symlink/junction, linked worktree, PowerShell menüsü ve gerçek 77 dosyalık patch'in taban ağacına uygulanması.

Tam CI, uygulama paketlemesi ve canlı çok ajanlı uçtan uca çalışma doğrulanmadı. Testler kontrollü işçi host'ları kullanır; gerçek üretim token ölçümü değildir. Gerçek patch fixture testi yerel `orca-source/` checkout'una ihtiyaç duyar ve o yoksa atlanır.

Yeniden çalıştırma:

```sh
python scripts/verify_bundle.py
python -m unittest discover -s tests -v
```

Ayrıntılı sonuçlar: [VALIDATION.md](../docs/VALIDATION.md).

## Lisans ve kaynak

Çalışma, Orca v1.4.246 çekirdeğine dayanır. Paket içindeki Orca kaynakları ve uyarlamaları [MIT lisansı](../LICENSE) kapsamındadır; upstream telif bildirimi korunmuştur. Bu depo resmi Orca projesiyle bağlılık veya onay iddiası taşımaz.
