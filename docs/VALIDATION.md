# Doğrulama kayıtları

## Kaynak referansları

- Orca tabanı: `55ccff19ad4cd8ba28b6f3d2be798c1e626a2c2c` (v1.4.246).
- Uygulama referansı: yerel kaynak deposundaki `efab515b6c4e882a3f887266507614b1d29a89e4` commit'i. Bu commit'in tam kaynak geçmişi bu değişiklik paketinde yayımlanmaz.
- Makineyle okunabilir yollar ve SHA-256 değerleri: [`bundle-manifest.json`](../bundle-manifest.json).

## Çalıştırılan odaklı Orca testleri

**7 dosya, 48 test: geçti.** Testler değişikliklerin bulunduğu tam Orca checkout'unda çalıştırıldı. Paket klasörü tek başına Node/Orca projesi değildir.

Patch uygulanmış checkout içinde yeniden çalıştırmak için:

```sh
pnpm test src/main/runtime/orchestration/automatic-run/automatic-run-executor.test.ts src/main/runtime/orchestration/automatic-run/automatic-run-event-failure.test.ts src/main/runtime/orchestration/automatic-run/automatic-run-task-brief.test.ts src/main/runtime/orchestration/db/automatic-runs/workflow-apply.test.ts src/main/runtime/orchestration/db/schema/migrate-v47.test.ts src/main/runtime/rpc/methods/orchestration/automatic/automatic-run-host.test.ts src/cli/handlers/orchestration-run-cli.test.ts --maxWorkers=2
```

Yayımlama hazırlığında aynı dosyalar `pnpm exec vitest run --config config/vitest.config.ts ... --maxWorkers=2` ile mevcut geliştirme ortamında doğrulandı.

Kapsanan senaryolar arasında sıralama, paralel birleşme, kapasite sınırı, yinelenen tamamlanma, bağımsız kolun ilerlemesi, inceleme kapıları, kalıcı uyanış kayıtları, kesinti sonrası devam, çalışma alanı çakışmaları, pause/cancel, akış sürümü ve normal zincirde ara koordinatör bildirimi oluşmaması bulunur.

## Installer testleri

**2 test dosyası, 46 test: geçti.** Testler yalnızca Python standart kütüphanesi ve Git kullanır; geçici Git checkout'ları ve sentetik bir değişiklik paketi oluşturur. Gerçek kullanıcı checkout'unda veya kurulu Orca uygulamasında install/uninstall denenmedi.

```sh
python scripts/verify_bundle.py
python -m unittest discover -s tests -v
```

Kapsam:

- Temiz install → status → uninstall: orijinal baytlar ve normal izinler birebir geri gelir; eklenen dosyalar ve boş kurulum dizinleri kaldırılır; ilgisiz dosyalar, Git `HEAD` ve index korunur.
- CRLF dosyasının install sırasında değişmesi ve uninstall sonrası orijinal CRLF baytlarına dönmesi.
- Patch ile uyumlu yerel düzenlemelerin korunması; çakışan patch'in hedefi değiştirmemesi.
- Aynı paketin tekrar kurulumunun idempotent olması ve ilk yedeği ezmemesi; farklı paket sürümünün kurulu yedeği değiştirmemesi.
- Install sonrası düzenlenen orijinal/yeni dosyaların ve silinen orijinal dosyaların kurtarma arşivine alınması; arşiv manifestindeki neden ve hash'lerin doğrulanması.
- Eksik/bozuk yedek, bozuk paket, yanlış taban commit, geçersiz kayıt, checkout dışına çıkan path ve başka checkout'a ait kayıtların hedef değiştirmeden reddedilmesi.
- Yazma hatasında otomatik geri alma; geri alma tamamlanamazsa `recovery_required` ve dürüst hata; kesintiye uğramış install/uninstall günlüğünün sonraki çağrıda uzlaştırılması; kesinti sonrası düzenlenmiş içeriğin arşivlenmesi.
- Canlı kilit, ölü kilit kurtarma, bayat kilit devralma yarışı, eşzamanlılık reddi.
- Symlink ve Windows junction üzerinden yazmanın reddedilmesi; linked worktree için ayrı per-worktree Git veri dizininin kullanılması.
- Dry-run ve status komutlarının bütün checkout ağacında (`.git` dahil) hiçbir içerik değiştirmemesi.
- `install.ps1 -Action verify` PowerShell smoke testi; PowerShell yoksa test atlanır.
- Gerçek `patches/automatic-orchestration.patch` dosyasının taban commit'teki 77 dosyalık geçici ağaca uygulanması ve 77 snapshot hash'iyle eşleşmesi.
- `verify_bundle.py` çıktısının geriye uyumlu kalması (79 dosya) ve README yerel bağlantılarının çözülmesi.

Ek olarak, `orca-source` deposundan `--shared` ile oluşturulan geçici, sparse bir v1.4.246 checkout'unda gerçek paketle uçtan uca CLI denemesi yapıldı: `install` 77 dosyayı yazdı, `status` 77/77 eşleşme gösterdi, `uninstall` 50 dosyayı geri yükleyip 27 dosyayı kaldırdı ve hedef checkout `git status` temiz döndü. Bu deneme yerel `orca-source` çalışma ağacını değiştirmedi; test fixture dışında gerçek kullanıcı checkout'u kullanılmadı.

Testler bu çalışma ortamında Windows üzerinde çalıştırıldı. macOS/Linux'ta süreç ve izin davranışları ayrıca çalıştırılmadı; kod platforma duyarlı izin/executable-bit dallarını içerir ancak bu dallar burada yalnızca koşullu olarak atlandı.

## Paket kontrolleri

- Manifest hash'leri snapshot ve patch dosyalarıyla karşılaştırılır.
- Patch, taban commit'teki etkilenen dosyalardan oluşturulmuş geçici bir ağaçta uygulanır ve sonuç snapshot'larla karşılaştırılır.
- README yerel dosya bağlantıları kontrol edilir.
- Örnek iş akışı uygulamanın gerçek şeması ve bağımlılık doğrulamasıyla kontrol edilmiştir.

## Bilinen lint sonuçları

Değişen Orca kodu üzerinde `oxlint` çalıştırıldı. İki `eslint(max-lines)` hatası kaldı:

- `src/cli/specs/orchestration.ts`
- `src/main/runtime/runtime-agent-orchestration-projection.ts`

Bu yayımlama için uygulama kodu yeniden düzenlenmedi; mevcut sonuç açıkça kaydedildi.

## Doğrulanmayanlar

Tam CI, bütün uygulama derlemesi/paketlemesi, canlı çok ajanlı uçtan uca senaryo, gerçek üretim token tasarrufu ve diğer Orca sürümlerine uygulanabilirlik bu kayıtların kapsamı dışındadır. Kontrollü işçi host'larıyla geçen testler bu alanlarda üretim doğrulaması anlamına gelmez. Installer, gerçek kullanıcı checkout'unda veya kurulu uygulamada denenmedi; macOS/Linux çalıştırması ve gerçek bir Orca derlemesi de doğrulanmadı.
