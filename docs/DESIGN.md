# Yürütme tasarımı

## Sorumluluklar

Mevcut Run → Task → Dispatch → Worker yaşam döngüsü korunur. Otomatik mod, mevcut elle yönetilen Run'lara ek ve isteğe bağlıdır.

- Orkestratör: planlama, yorumlama, sorular ve istisna kararları.
- Runtime yürütücüsü: bağımlılık, kapasite ve çalışma alanı kontrolü; işçi başlatma.
- Veritabanı: akış sürümleri, yürütme olayları, sonuçlar ve karar kapıları.
- Mevcut worker yaşam döngüsü: başlatma, sonuç alma, kontrollü durdurma ve kaynak sahipliği.

## Olay akışı

1. Koordinatör otomatik Run ve görev grafiğini oluşturur, başlatır, turunu bitirir.
2. Runtime hazır görevleri kapasite sınırına kadar başlatır.
3. İşçi sonucu etkin Dispatch kimliğiyle doğrulanır ve kaydedilir.
4. Kalıcı olaylar işlenir; bağımlılığı açılan görevler değerlendirilir.
5. Normal başarı koordinatör uyanışı gerektirmez; karar olayları ve final raporu koordinatöre gider.

Sorgu döngüsü veya sürekli açık koordinatör modeli kullanılmaz. Başlatılan işlerin kendisi, kapasite sınırına dahildir. Aynı çalışma alanındaki yazma ve doğrulama işleri çakıştırılmaz.

## Sonuçlar ve kararlar

İşçi teslimi özet, kanıt ve sonraki görev için aktarım bilgisi taşır. İnceleme `approved` veya `changes_requested` sonucu verebilir. İnceleme için karar kapısı oluşturulur; düzeltmeler ayrı görevlerdir ve tur sayısı ikiyle sınırlıdır.

Bağımsız kollar sorunlu bir kolu beklemek zorunda değildir. Belirsiz başlatma, sessizlik veya idle durumu başarı kanıtı sayılmaz. Aynı olayın yeniden işlenmesi ikinci işçi başlatmamalıdır. Yeniden açılışta kalıcı olaylar ve yarım başlatmalar uzlaştırılır.

## Kullanıcı kontrolleri

`workflow-apply` beklenen sürümle atomik güncelleme yapar. Başlamış görevler değiştirilemez veya kaldırılamaz. Pause yeni başlangıçları engeller; resume hazır görevleri yeniden değerlendirir. Cancel mevcut kontrollü durdurma yolunu kullanır; doğrulanmamış durma iptal tamamlandı şeklinde raporlanmaz.

## Sınırlar

Bu paket yerel çekirdek entegrasyonudur. Otomatik merge, yayımlama veya ayrı bir görsel akış editörü eklemez. Tam kod, inceleme ve test akışının gözetimsiz kullanımından önce hedef projede doğrulanması gerekir; özellikle düzeltme sonrasında hangi doğrulamaların tekrarlandığı kontrol edilmelidir.

Uygulama kaynakları [`changes/src/main/runtime/orchestration/automatic-run/`](../changes/src/main/runtime/orchestration/automatic-run/) ve [`changes/src/shared/orchestration-workflow.ts`](../changes/src/shared/orchestration-workflow.ts) altındadır. Satır bazında değişiklikler patch'tedir.
