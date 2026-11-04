# Doğrulama kayıtları

## Kaynak referansları

- Orca tabanı: `55ccff19ad4cd8ba28b6f3d2be798c1e626a2c2c` (v1.4.246).
- Uygulama referansı: yerel kaynak deposundaki `efab515b6c4e882a3f887266507614b1d29a89e4` commit'i (otomatik orkestrasyon). Todo sütunu değişiklikleri bu commit sonrası yerel çalışma ağacında uygulandı; paket snapshot'ları bu birleşik çalışma ağacını yansıtır. Bu commit'lerin tam kaynak geçmişi bu değişiklik paketinde yayımlanmaz.
- Makineyle okunabilir yollar ve SHA-256 değerleri: [`bundle-manifest.json`](../bundle-manifest.json).

## Çalıştırılan odaklı Orca testleri

**14 dosya, 178 test: geçti.** Testler değişikliklerin bulunduğu tam Orca checkout'unda `NODE_ENV=test` ve `pnpm exec vitest run --config config/vitest.config.ts ... --maxWorkers=2` ile çalıştırıldı. Paket klasörü tek başına Node/Orca projesi değildir.

```sh
pnpm exec vitest run --config config/vitest.config.ts \
  src/shared/workspace-todo.test.ts src/shared/folder-workspace-worktree.test.ts \
  src/renderer/src/components/dashboard-popout/AgentKanbanBoard.todo.test.tsx \
  src/renderer/src/components/dashboard-popout/workspace-todo-filtering.test.ts \
  src/renderer/src/components/dashboard-popout/AgentKanbanBoard.test.tsx \
  src/renderer/src/components/dashboard/build-dashboard-snapshot.todos.test.ts \
  src/renderer/src/components/dashboard/build-dashboard-snapshot.test.ts \
  src/main/ipc/dashboard-popout.test.ts src/main/ipc/dashboard-payload-validation.test.ts \
  src/main/persistence/tracking-repos/persistence-worktree-meta-and-folder-workspaces.test.ts \
  src/renderer/src/components/dashboard/useDashboardPopoutBridge.test.tsx \
  src/renderer/src/components/dashboard/AgentDashboardDrawer.test.tsx \
  src/renderer/src/components/dashboard/AgentDashboardDrawer.focus.test.tsx \
  src/renderer/src/store/slices/worktrees/metadata/workspace-todo-actions.test.ts --maxWorkers=2
```

Todo kapsamı: ekleme, satır içi düzenleme, tamamlama, geri açma, silme ve geri alma; çalışma alanı izolasyonu; worktree ve klasör çalışma alanlarında yeniden başlatma kalıcılığı; ana pencere–popout sonuç aktarımı; boş liste, uzun metin, kayıt hatası, arama/filtre ve klavye davranışı; eski host desteğinin reddedilmesi.

Otomatik orkestrasyonun önceki 7 dosya/48 testlik kapsamı da aynı checkout'ta yeniden çalıştırıldı: **7 dosya, 48 test: geçti.** Toplam doğrulanan Orca kapsamı 21 dosya/226 testtir.

## Installer testleri

**2 test dosyası, 55 test: geçti.** Testler yalnızca Python standart kütüphanesi ve Git kullanır; geçici Git checkout'ları ve sentetik bir değişiklik paketi oluşturur. Gerçek paket ayrıca taban commit'teki geçici bir worktree üzerinde install → status → uninstall turuyla doğrulandı.

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
- Gerçek `patches/automatic-orchestration.patch` dosyasının taban commit'teki 133 dosyalık geçici ağaca uygulanması ve 133 snapshot hash'iyle eşleşmesi. Test, `ORCA_SOURCE_CHECKOUT` ile gerçek yerel checkout'a yönlendirildi.
- `verify_bundle.py` çıktısının geriye uyumlu kalması (135 dosya) ve README yerel bağlantılarının çözülmesi.
- `packs` tanımlarının tüm dosyaları tam bir kez kapsaması; bilinmeyen/eksik pack seçiminin reddedilmesi; seçilen pack ile install, status ve uninstall.
- PowerShell `-Pack` parametresiyle gerçek tabanda Todo-only ve Orchestrator-only kurulum turları; `-Action install` doğrudan çağrısında bileşen sorusunun atlanması.
- `install.ps1` UTF-8 BOM ile Windows PowerShell 5.1'de Türkçe menü/regex metinlerini doğru okur; paket deposu yokken yerel HTTP arşivinden commit çözümleme + manifest SHA-256 + `install.ps1` ve Python bootstrap script hash doğrulamalı indirme testi geçti. Kurcalanmış `scripts/orca_install/cli.py` içeren arşiv reddedildi.
- `--pack` verilmeden yapılan yeniden kurulum, mevcut pack seçimini koruyup `already-installed` döndürüyor (dry-run dahil); legacy `packs=[]` kaydı “all” sayılıyor.

Ek olarak, gerçek paket `orca-source` deposundan `55ccff19` tabanında oluşturulan geçici bir Git worktree üzerinde uçtan uca denendi. Etkilenen dosyalar kurulumdan önce taban blob baytlarına getirildi (README'deki LF kurulum koşulu). `install` **133 dosya (88 güncelleme, 45 ekleme)** yazdı; `status` **133/133 eşleşme, 0 değişmiş/eksik/beklenmeyen** gösterdi; `uninstall` **88 dosyayı geri yükleyip 45 dosyayı kaldırdı**; taban blob'larıyla karşılaştırmada geri yüklenen dosya farkı **0** çıktı. Yönetilen dosyaların bayt düzeyinde geri dönüşü ayrıca installer testleriyle doğrulanır. Geçici worktree ve meta verisi kaldırıldı; yerel `orca-source` çalışma ağacı ve `core.autocrlf=true` ayarı korundu.

Pack seçimi de aynı taban üzerinde ayrıca doğrulandı: `--pack todo` **52 dosya (37 güncelleme, 15 ekleme)** yazdı, `status` **52/52 eşleşme** gösterdi, `uninstall` **37 geri yükleme / 15 kaldırma** yaptı. `--pack orchestration` **81 dosya (51 güncelleme, 30 ekleme)** yazdı, `status` **81/81 eşleşme** gösterdi, `uninstall` **51 geri yükleme / 30 kaldırma** yaptı.

Testler bu çalışma ortamında Windows üzerinde çalıştırıldı. macOS/Linux'ta süreç ve izin davranışları ayrıca çalıştırılmadı; kod platforma duyarlı izin/executable-bit dallarını içerir ancak bu dallar burada yalnızca koşullu olarak atlandı.

## Paket kontrolleri

- Manifest hash'leri snapshot ve patch dosyalarıyla karşılaştırılır.
- Patch, taban commit'teki etkilenen dosyalardan oluşturulmuş geçici bir ağaçta uygulanır ve sonuç snapshot'larla karşılaştırılır.
- README yerel dosya bağlantıları kontrol edilir.
- Örnek iş akışı uygulamanın gerçek şeması ve bağımlılık doğrulamasıyla kontrol edilmiştir.

## Bilinen lint sonuçları

Değişen Orca kodu üzerinde `oxlint` ve `oxfmt --check` çalıştırıldı; değişen dosyalar temiz. Önceki otomatik orkestrasyon paketinden kalan iki `eslint(max-lines)` kaydı (`src/cli/specs/orchestration.ts`, `src/main/runtime/runtime-agent-orchestration-projection.ts`) bu değişikliklerle düzenlenmedi. `pnpm tc` beş typecheck projesinde de sıfır hata verdi.

## Doğrulanmayanlar

Tam CI, bütün uygulama derlemesi/paketlemesi, canlı çok ajanlı uçtan uca senaryo, gerçek üretim token tasarrufu ve diğer Orca sürümlerine uygulanabilirlik bu kayıtların kapsamı dışındadır. Kontrollü işçi host'larıyla geçen testler bu alanlarda üretim doğrulaması anlamına gelmez. Installer gerçek kullanıcı checkout'unda veya kurulu uygulamada denenmedi; macOS/Linux çalıştırması ve gerçek bir Orca derlemesi de doğrulanmadı. Tema ve dar pencere davranışı mevcut token/horizontal-scroll düzeniyle sınırlı olup Electron'da görsel ekran görüntüsüyle ayrıca doğrulanmadı.
