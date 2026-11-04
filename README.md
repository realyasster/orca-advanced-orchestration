# Orca Advanced Orchestration

Orca'da Codex ve Claude gibi ajanların görevlerini otomatik sıraya koyar. Bir görev bitince sıradaki başlar; bağımsız görevler paralel çalışır.

**Orca v1.4.246 kaynak koduna uygulanan bir yama paketidir.** Bağımsız uygulama veya plugin değildir; kurulumdan sonra derleme gerekir.

## Kurulum

Windows PowerShell'de tek komut:

```powershell
irm https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/main/install.ps1 | iex
```

Menüden **Kur** seçin. Betik paketi GitHub Releases'ten indirir, bütünlüğünü doğrular, önbelleğe alır ve Orca kaynağına uygular.

Gereksinimler: **Python 3.9+**, **Git** ve **Orca v1.4.246** kaynak checkout'u. Checkout yoksa menü desteklenen sürümü klonlamayı önerir.

Kurulumdan sonra:

```powershell
cd <orca-kaynak>
pnpm install --frozen-lockfile
pnpm build
```

> Kaynağın değiştirilmiş olması ile uygulamanın kullanıma hazır olması ayrı durumlardır. Derleme tamamlanmadan yeni davranış çalışmaz.

## Menü

```text
Kur · Güncelle · Kaldır · Durum ve sürümler
Doğrula · İşlem provası · Orca kaynak yolunu değiştir · Çıkış
```

Kaynak yolu kalıcı olarak kaydedilir. Güncelleme aynı sürümdeyse no-op çalışır; hata veya kesintide önceki kurulu sürüm geri getirilir.

## Komut satırı

```powershell
.\install.ps1 -Action install -Source C:\orca-dev
.\install.ps1 -Action update -Source C:\orca-dev
.\install.ps1 -Action status -Source C:\orca-dev
.\install.ps1 -Action verify
.\install.ps1 -Action uninstall -Source C:\orca-dev
```

`-DryRun` işlem provası yapar, `-Version` sürüm seçer, `-NoPause` otomasyon için beklemesiz çalışır.

## Ne yapar?

- Bağımlılıkları ve paralel görevleri yönetir.
- İnceleme kararlarını, düzeltme turlarını ve sonuç raporunu yönetir.
- Duraklatma, sürdürme ve kontrollü iptal sunar.
- Kurulum öncesi yedek alır; kaldırmada özgün dosyaları geri yükler.

## Belgeler

**[Kurulum ve kullanım rehberi](docs/USAGE.md)** · [Örnek iş akışı](examples/workflow.json)

[English](README.en.md) · [Teknik tasarım](docs/DESIGN.md) · [Doğrulama](docs/VALIDATION.md) · [MIT lisansı](LICENSE)
