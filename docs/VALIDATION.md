# Doğrulama kayıtları

## Kaynak referansları

- Orca tabanı: `965978bc78bf03a6a43187c1ed28fcffe0e01bb5` (v1.4.248).
- Uygulama referansı: yerel kaynak deposundaki `967737fa6e809b6245e947fb6bcd18a3e8ca5f9c` commit'i. Bu commit'in tam kaynak geçmişi bu değişiklik paketinde yayımlanmaz.
- Paket sürümü: `bundle-manifest.json` içindeki `package.version` (`1.2.0`).
- Makineyle okunabilir yollar ve SHA-256 değerleri: [`bundle-manifest.json`](../bundle-manifest.json).

## Çalıştırılan odaklı Orca testleri

**20 dosya, 229 test: geçti.** Testler değişikliklerin bulunduğu tam Orca v1.4.248 checkout'unda Windows, Node 26.7.0 ve pnpm 12.16.1 ile çalıştırıldı. `pnpm typecheck` 16.379 + 4.044 + 19.954 + 38 + 11.954 dosyada hata vermedi. Paket klasörü tek başına Node/Orca projesi değildir.

Todo ve orkestrasyon testleri kalıcılık, filtreleme, kart/form davranışı, ana pencere/popout senkronu, yetenek desteği, otomatik yürütme, workflow uygulama ve CLI davranışını kapsar.

Patch uygulanmış checkout içinde yeniden çalıştırmak için:

```sh
pnpm exec vitest run --config config/vitest.config.ts \
  src/cli/handlers/orchestration-run-cli.test.ts \
  src/main/ipc/dashboard-popout.test.ts \
  src/main/persistence/tracking-repos/persistence-worktree-meta-and-folder-workspaces.test.ts \
  src/main/runtime/orchestration/automatic-run/automatic-run-event-failure.test.ts \
  src/main/runtime/orchestration/automatic-run/automatic-run-executor.test.ts \
  src/main/runtime/orchestration/automatic-run/automatic-run-task-brief.test.ts \
  src/main/runtime/orchestration/db/automatic-runs/workflow-apply.test.ts \
  src/main/runtime/orchestration/db/schema/migrate-v47.test.ts \
  src/main/runtime/rpc/methods/orchestration-structured-worker-start-failure.test.ts \
  src/main/runtime/rpc/methods/orchestration/automatic/automatic-run-host.test.ts \
  src/main/runtime/rpc/methods/orchestration/runs/run-receipt.test.ts \
  src/main/runtime/rpc/orchestration-session-caller.test.ts \
  src/renderer/src/components/dashboard-popout/AgentKanbanBoard.test.tsx \
  src/renderer/src/components/dashboard-popout/AgentKanbanBoard.todo.test.tsx \
  src/renderer/src/components/dashboard-popout/workspace-todo-filtering.test.ts \
  src/renderer/src/components/dashboard/build-dashboard-snapshot.todos.test.ts \
  src/renderer/src/components/dashboard/useDashboardPopoutBridge.test.tsx \
  src/renderer/src/store/slices/worktrees/metadata/workspace-todo-actions.test.ts \
  src/shared/folder-workspace-worktree.test.ts \
  src/shared/workspace-todo.test.ts \
  --maxWorkers=2
```

## Installer testleri

**5 test dosyası, 87 test: geçti.** Testler yalnızca Python standart kütüphanesi ve Git kullanır; geçici Git checkout'ları ve sentetik paketler oluşturur. Windows PowerShell 5.1 üzerinde çalıştırıldı.

```sh
python scripts/verify_bundle.py
python -m unittest discover -s tests -v
```

### Kurulum, durum ve kaldırma

- Temiz install → status → uninstall: orijinal baytlar ve izinler birebir geri gelir; eklenen dosyalar ve boş kurulum dizinleri kaldırılır; ilgisiz dosyalar, Git `HEAD` ve index korunur.
- CRLF dosyasının install sırasında değişmesi ve uninstall sonrası orijinal CRLF baytlarına dönmesi.
- Patch ile uyumlu yerel düzenlemelerin korunması; çakışan patch'in hedefi değiştirmemesi.
- Aynı paketin tekrar kurulumunun idempotent olması ve ilk yedeği ezmemesi; farklı paket sürümünün kurulu yedeği değiştirmemesi.
- Install sonrası düzenlenen orijinal/yeni dosyaların ve silinen orijinal dosyaların kurtarma arşivine alınması.
- Eksik/bozuk yedek, bozuk paket, yanlış taban commit, geçersiz kayıt, checkout dışına çıkan path ve başka checkout'a ait kayıtların hedef değiştirmeden reddedilmesi.
- Yazma hatasında otomatik geri alma; geri alma tamamlanamazsa `recovery_required` ve dürüst hata; kesintiye uğramış install/uninstall günlüğünün sonraki çağrıda uzlaştırılması.
- Canlı kilit, ölü kilit kurtarma, bayat kilit devralma yarışı, eşzamanlılık reddi.
- Symlink ve Windows junction üzerinden yazmanın reddedilmesi; linked worktree için ayrı per-worktree Git veri dizininin kullanılması.
- Dry-run ve status komutlarının checkout ağacında hiçbir içerik değiştirmemesi.
- `install.ps1 -Action verify` PowerShell smoke testi.
- Gerçek `patches/automatic-orchestration.patch` dosyasının taban commit'teki 133 dosyalık geçici ağaca uygulanması ve snapshot hash'leriyle eşleşmesi.
- `verify_bundle.py` çıktısının geriye uyumlu kalması (135 dosya) ve README yerel bağlantılarının çözülmesi.
- Todo-only ve Orchestrator-only pack kurulumları; pack bağımlılık çözümlemesi, döngü reddi, filtrelenmiş patch'in bağımsız uygulanması ve `--pack` seçimi.
- Todo-only kurulumdan sonra `--pack` verilmeden yapılan yeniden kurulumun `already-installed` dönmesi (dry-run dahil).
- Güncellemenin kurulu pack seçimini koruması.
- Manifestte `package` bölümü yoksa paket yüklemenin sessiz fallback yapmadan reddedilmesi.

### Güncelleme motoru

- Temiz güncelleme: dosya değişimi, yeni dosya ekleme ve yönetimden çıkarma; sonrasında uninstall'ın taban ağacı birebir geri getirmesi.
- İlk kurulum öncesi özgün yedek dizininin güncelleme sonrasında korunması.
- Aynı paket sürümünde no-op; durum dosyasının değişmemesi.
- Aynı sürüm farklı içerikle gelirse reddetme.
- Kurulum sonrası yerel değişiklikte hedefe dokunmadan reddetme.
- Farklı upstream tabanında otomatik reset/checkout yapmadan açık hata.
- Dry-run'ın hiçbir dosya/günlük değiştirmemesi.
- Hedef yazma hatasında önceki kurulu sürümün baytlarına geri dönme; kayıt sürümünün eski sürümde kalması.
- Kesintiye uğramış güncellemenin `updating` günlüğünden kurtarılması; kesinti sonrası düzenlenmiş içeriğin arşivlenmesi ve önceki kurulu sürümün geri gelmesi.
- Önceden yönetilmeyen bir upstream dosyasının yeni pakette yönetilmesi durumunda özgün olarak yedeklenmesi ve uninstall'da geri gelmesi.
- Etkin kurulum yokken güncellemenin reddedilmesi.
- Yönetimden çıkarılan dosyaların özgün girdilerinin kümülatif yedeğin `retiredEntries` bölümünde tutulması.
- Yönetimden çıkarılan dosyaların boş bıraktığı kurulum-oluşturulmuş dizinlerin güncelleme sırasında temizlenmesi.
- Başarılı güncellemede `updates/<id>` günlüğünün, geri alma/kesinti kurtarmasında ayrıca `backup-<id>` dizininin temizlenmesi.
- Kesintiye uğramış `installing`/`updating`/`uninstalling` kayıtlarının `verify` çıktısında problem olarak raporlanması.
- Kümülatif yedek yazımı yarıda kalırsa oluşturduğu dizini kendisinin temizlemesi.

### Release paketi

- Sürümlenmiş ZIP ve `.sha256` üretimi; checksum dosyasının ZIP hash'iyle eşleşmesi.
- Arşivin yalnızca çalışma zamanı dosyalarını içermesi; `tests/`, `orca-source/`, `docs/`, `.git/`, README ve workflow dosyalarının dışarıda kalması.
- Arşivden çıkarılan paketin `load_bundle` ve `verify_bundle.py` ile doğrulanması.
- `scripts/orca_install` altındaki tüm `.py` dosyalarının (alt paketler dahil) ZIP'te bulunması ve çıkarılan paketten `orca_install.cli`/`orca_install.updater` import edilmesi.
- İki ayrı üretimin bayt düzeyinde deterministik olması.

### PowerShell giriş betiği

- Repo dışından `-RepoRoot` ile yerel paket üzerinden install → status → uninstall.
- İkinci çağrıda `-Source` verilmeden kayıtlı kaynak yolunun kullanılması.
- Repo dışına kopyalanmış `install.ps1` ile önbellekteki sürüm üzerinden çevrimdışı install, no-op update ve uninstall.
- Yerel pakette aynı sürüm farklı içerikli güncellemenin ağ araması yapmadan Python `_check_package` kontrolüne ulaşması.
- SemVer ön-sürüm sıralaması (`1.0.0-rc1 < 1.0.0`, `rc.2 < rc.10`, `alpha < alpha.1`).
- `py` adayı stderr yazıp başarısız olduğunda Python çözümlemenin sonraki adaya geçmesi.
- `[scriptblock]::Create(...)` ile çalıştırmada betiğin çağıran shell'i kapatmaması ve sonraki komutun çalışması.
- Yerel HTTP sunucusundan gerçek `irm ... | iex` çalıştırmasının menüyü açması, `0` ile temiz çıkması ve çağıran shell'de sonraki komutun çalışması.
- `SystemDrive` bulunmayan Linux ortamında (WSL Ubuntu, PowerShell 7.4.6) `-Action verify` Windows sürücü adayları üretmeden geçti; keşif yolları `dev/orca` gibi eğik çizgili biçimde üretiliyor.

Canlı `https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/v1.1.1/install.ps1` URL'sinden `irm ... | iex` çalıştırıldı: menü açıldı ve `0` ile temiz çıktı. GitHub Releases'ten `1.1.1` arşivi indirildi; checksum ve **135 dosya** hash'i geçti, paket önbelleğe alındı. Aynı hat yerel HTTP sunucusundan da çalıştırıldı.

## Paket kontrolleri

- Manifest hash'leri snapshot ve patch dosyalarıyla karşılaştırılır.
- Patch, taban commit'teki etkilenen dosyalardan oluşturulmuş geçici bir ağaçta uygulanır ve sonuç snapshot'larla karşılaştırılır.
- README yerel dosya bağlantıları kontrol edilir.
- Örnek iş akışı uygulamanın gerçek şeması ve bağımlılık doğrulamasıyla kontrol edilmiştir.
- Release ZIP'inin içeriği ve checksum'u test edilir.

## Bilinen lint sonuçları

Değişen Orca kodu üzerinde `oxlint` çalıştırıldı. İki `eslint(max-lines)` hatası kaldı:

- `src/cli/specs/orchestration.ts`
- `src/main/runtime/runtime-agent-orchestration-projection.ts`

Bu yayımlama için uygulama kodu yeniden düzenlenmedi; mevcut sonuç açıkça kaydedildi.

## Doğrulanmayanlar

Tam CI, bütün uygulama derlemesi/paketlemesi, canlı çok ajanlı uçtan uca senaryo, gerçek üretim token tasarrufu ve diğer Orca sürümlerine uygulanabilirlik bu kayıtların kapsamı dışındadır.

- Installer gerçek kullanıcı checkout'unda veya kurulu uygulamada denenmedi; testler geçici Git depoları kullanır.
- Gerçek bir Orca derlemesi (`pnpm install`, `pnpm build`) bu doğrulamada çalıştırılmadı.
- macOS/Linux PowerShell davranışı ve izin dalları Windows kadar kapsamlı doğrulanmadı.
