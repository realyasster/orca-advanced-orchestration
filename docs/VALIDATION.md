# Doğrulama kayıtları

## Kaynak referansları

- Orca tabanı: `55ccff19ad4cd8ba28b6f3d2be798c1e626a2c2c` (v1.4.246).
- Uygulama referansı: yerel kaynak deposundaki `efab515b6c4e882a3f887266507614b1d29a89e4` commit'i. Bu commit'in tam kaynak geçmişi bu değişiklik paketinde yayımlanmaz.
- Makineyle okunabilir yollar ve SHA-256 değerleri: [`bundle-manifest.json`](../bundle-manifest.json).

## Çalıştırılan odaklı testler

**7 dosya, 48 test: geçti.** Testler değişikliklerin bulunduğu tam Orca checkout'unda çalıştırıldı. Paket klasörü tek başına Node/Orca projesi değildir.

Patch uygulanmış checkout içinde yeniden çalıştırmak için:

```sh
pnpm test src/main/runtime/orchestration/automatic-run/automatic-run-executor.test.ts src/main/runtime/orchestration/automatic-run/automatic-run-event-failure.test.ts src/main/runtime/orchestration/automatic-run/automatic-run-task-brief.test.ts src/main/runtime/orchestration/db/automatic-runs/workflow-apply.test.ts src/main/runtime/orchestration/db/schema/migrate-v47.test.ts src/main/runtime/rpc/methods/orchestration/automatic/automatic-run-host.test.ts src/cli/handlers/orchestration-run-cli.test.ts --maxWorkers=2
```

Yayımlama hazırlığında aynı dosyalar `pnpm exec vitest run --config config/vitest.config.ts ... --maxWorkers=2` ile mevcut geliştirme ortamında doğrulandı.

Kapsanan senaryolar arasında sıralama, paralel birleşme, kapasite sınırı, yinelenen tamamlanma, bağımsız kolun ilerlemesi, inceleme kapıları, kalıcı uyanış kayıtları, kesinti sonrası devam, çalışma alanı çakışmaları, pause/cancel, akış sürümü ve normal zincirde ara koordinatör bildirimi oluşmaması bulunur.

## Bilinen lint sonuçları

Değişen kod üzerinde `oxlint` çalıştırıldı. İki `eslint(max-lines)` hatası kaldı:

- `src/cli/specs/orchestration.ts`
- `src/main/runtime/runtime-agent-orchestration-projection.ts`

Bu yayımlama için uygulama kodu yeniden düzenlenmedi; mevcut sonuç açıkça kaydedildi.

## Paket kontrolleri

- Manifest hash'leri snapshot ve patch dosyalarıyla karşılaştırılır.
- Patch, taban commit'teki etkilenen dosyalardan oluşturulmuş geçici bir ağaçta uygulanır ve sonuç snapshot'larla karşılaştırılır.
- README yerel dosya bağlantıları kontrol edilir.
- Örnek iş akışı uygulamanın gerçek şeması ve bağımlılık doğrulamasıyla kontrol edilmiştir.

## Doğrulanmayanlar

Tam CI, bütün uygulama derlemesi/paketlemesi, canlı çok ajanlı uçtan uca senaryo, gerçek üretim token tasarrufu ve diğer Orca sürümlerine uygulanabilirlik bu kayıtların kapsamı dışındadır. Kontrollü işçi host'larıyla geçen testler bu alanlarda üretim doğrulaması anlamına gelmez.
