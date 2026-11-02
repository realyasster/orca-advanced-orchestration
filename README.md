# Orca Advanced Orchestration

Orca için geliştirdiğimiz **olay tabanlı otomatik görev yürütme sisteminin değişiklik paketi**.

[English](README.en.md) · [Tasarım](docs/DESIGN.md) · [Doğrulama](docs/VALIDATION.md) · [MIT lisansı](LICENSE)

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
| [`patches/automatic-orchestration.patch`](patches/automatic-orchestration.patch) | Upstream tabana uygulanacak gerçek değişiklikler |
| [`changes/`](changes/) | Değişen veya eklenen 77 dosyanın uygulama sonrası halleri; özgün yollar korunur |
| [`examples/workflow.json`](examples/workflow.json) | Uygulama → paralel test ve inceleme örneği |
| [`bundle-manifest.json`](bundle-manifest.json) | Taban commit, kaynak commit, dosya listesi ve SHA-256 değerleri |
| [`scripts/verify_bundle.py`](scripts/verify_bundle.py) | Paket bütünlüğü kontrolü |

`changes/` içindeki mevcut upstream dosyaları entegrasyonun okunabilmesi için tam halleriyle bulunur. Hangi satırların değiştiğini patch gösterir. Paketi uygulamak için patch yolunu kullanın; snapshot'ları ayrıca kopyalamanız gerekmez.

## Orca'ya uygulama

Hedef taban: [stablyai/orca](https://github.com/stablyai/orca), **v1.4.246**, commit `55ccff19ad4cd8ba28b6f3d2be798c1e626a2c2c`.

Önce bu değişiklik paketini indirin:

```sh
git clone https://github.com/realyasster/orca-advanced-orchestration.git
```

Paketin kendi klasöründe bütünlüğü doğrulayın:

```sh
python scripts/verify_bundle.py
```

Sonra ayrı bir klasörde Orca kaynak kodunu hazırlayın:

```sh
git clone --branch v1.4.246 --depth 1 https://github.com/stablyai/orca.git orca-dev
cd orca-dev
git rev-parse HEAD
git switch -c feature/automatic-orchestration
git apply --check ../orca-advanced-orchestration/patches/automatic-orchestration.patch
git apply ../orca-advanced-orchestration/patches/automatic-orchestration.patch
```

`git rev-parse HEAD` çıktısı yukarıdaki taban commit ile aynı olmalıdır. Komutlar iki klonun aynı üst klasörde olduğunu varsayar. Mevcut checkout kullanıyorsanız temiz bir geliştirme dalı oluşturun ve patch yolunu uyarlayın. Başka Orca sürümlerine uygulanabilirlik doğrulanmadı.

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

İlgili **7 test dosyasındaki 48 test geçti**. İki dosyada `max-lines` lint hatası kaldı. Tam CI, uygulama paketlemesi ve canlı çok ajanlı uçtan uca çalışma doğrulanmadı. Testler kontrollü işçi host'ları kullanır; gerçek üretim token ölçümü değildir.

Ayrıntılı sonuçlar ve yeniden çalıştırma komutu: [VALIDATION.md](docs/VALIDATION.md).

## Lisans ve kaynak

Çalışma, Orca v1.4.246 çekirdeğine dayanır. Paket içindeki Orca kaynakları ve uyarlamaları [MIT lisansı](LICENSE) kapsamındadır; upstream telif bildirimi korunmuştur. Bu depo resmi Orca projesiyle bağlılık veya onay iddiası taşımaz.
