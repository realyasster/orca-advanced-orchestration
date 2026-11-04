# Orca Advanced Orchestration

Orca çekirdeğine eklenen olay tabanlı görev yürütücüsü. Akışı bir kez tarif edersiniz; bağımlılıklar tamamlandıkça sıradaki ajanı Orca başlatır. Orkestratör beklemek ve normal görev geçişlerini yönetmek için model çağrısı yapmak zorunda kalmaz.

Bu proje [stablyai/orca](https://github.com/stablyai/orca) v1.4.248 üzerine geliştirilmiş bağımsız bir kaynak deposudur. **Plugin veya resmi Orca sürümü değildir.**

## Neler içeriyor?

- Sıralı ve paralel görevler; birleşen bağımlılıklar.
- Varsayılan iki eşzamanlı işçi ajan.
- Sürümlü akış düzenleme ve kalıcı yürütme olayları.
- Tekrarlanan tamamlanma bildirimlerine ve belirsiz başlatmalara karşı korumalar.
- Çalışma alanı kullanımı ve önceki görev çıktılarının aktarılması.
- İnceleme karar kapıları ve en fazla iki düzeltme turu.
- Duraklatma, sürdürme ve kontrollü iptal.
- CLI, RPC, veritabanı ve orchestration becerisi güncellemeleri.

Örnek: **Codex uygulasın → test ve Claude incelemesi paralel çalışsın → karar gerekiyorsa orkestratör uyansın → sonunda sonuç raporlansın.**

İşçi ajanların token tüketimi devam eder. Hedef, bekleme ve öngörülebilir geçişlerdeki gereksiz orkestratör çağrılarını azaltmaktır.

## Kurulum ve kullanım

Node.js 24, depoda sabitlenen pnpm ve Bun sürümleri ile platforma uygun native derleme araçları gerekir.

```sh
git clone https://github.com/realyasster/orca-advanced-orchestration.git
cd orca-advanced-orchestration
pnpm install --frozen-lockfile
pnpm dev --worktree-profile
```

Kurulu üretim uygulaması yerine geliştirme sürümünü kullanın. CLI işlemleri için bu checkout içinde `node config/scripts/orca-dev.mjs` çalıştırın.

Ayrıntılı komutlar ve akış oluşturma adımları [ana README'de](README.md#create-an-automatic-workflow); örnek tanım [workflow.json](examples/automatic-orchestration/workflow.json) dosyasındadır.

## Doğrulama durumu

Yayımlama hazırlığında ilgili **7 test dosyasındaki 48 test geçti**. Değişen kodun lint kontrolünde iki dosyada `max-lines` hatası kaldı. Tam uygulama derlemesi, tam CI ve canlı çok ajanlı uçtan uca çalışma bu yayımlama sırasında doğrulanmadı. Ayrıntılar [ana README'de](README.md#development-status).

Hazır kurulum paketi sunulmuyor; depoyu yayımlamak kurulu Orca uygulamasını güncellemez. Gözetimsiz kullanım öncesinde kendi akışınızı, özellikle düzeltme sonrası doğrulama adımlarını sınayın.

## Lisans

Orca'nın [MIT lisansı](LICENSE) ve upstream telif bildirimleri korunmuştur. Orijinal README [README.upstream.md](README.upstream.md) dosyasındadır.
