# Orca Advanced Orchestration

Orca'da Codex ve Claude gibi ajanların görevlerini otomatik sıraya koyar. Bir görev bitince sıradaki başlar; bağımsız görevler paralel çalışır.

**Orca v1.4.246 kaynak koduna uygulanan bir yama paketidir.** Bağımsız uygulama veya plugin değildir; kurulumdan sonra derleme gerekir.

## Kurulum

Windows PowerShell'de tek komut:

```powershell
irm https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/v1.1.0/install.ps1 | iex
```

Menüden **Kur (bileşen seçimiyle)** seçin; **Orchestrator** ve **Todo** bileşenlerini ayrı ayrı işaretleyebilirsiniz. Betik paketi GitHub Releases'ten indirir, bütünlüğünü doğrular, önbelleğe alır ve Orca kaynağına uygular.

Gereksinimler: **Python 3.9+**, **Git** ve **Orca v1.4.246** kaynak checkout'u. Checkout otomatik bulunur; yoksa **Kur** işlemi desteklenen sürümü `%USERPROFILE%\orca-dev` konumuna soru sormadan klonlar. Farklı bir checkout için `-Source` verin.

Kurulumdan sonra:

```powershell
cd <orca-kaynak>
pnpm install --frozen-lockfile
pnpm build
```

> Kaynağın değiştirilmiş olması ile uygulamanın kullanıma hazır olması ayrı durumlardır. Derleme tamamlanmadan yeni davranış çalışmaz.

## Menü

```text
Kur (bileşen seçimiyle) · Güncelle · Kaldır · Durum ve sürümler
Doğrula · İşlem provası · Orca kaynak yolunu değiştir · Dil değiştir (Türkçe/English) · Çıkış
```

İlk menü açılışında dil sorulur (`Dil / Language [1] Turkce [2] English`); seçim `config.json` içinde saklanır. Menüdeki **Dil değiştir** maddesiyle veya tek çalıştırmalık `-Lang tr|en` ile değiştirilebilir.

Kaynak yolu kalıcı olarak kaydedilir; geçici olarak erişilemeyen kayıtlı yol silinmez, o çalıştırmada yok sayılır. Güncelleme aynı sürümdeyse no-op çalışır; hata veya kesintide önceki kurulu sürüm geri getirilir.

## Komut satırı

```powershell
.\install.ps1 -Action install -Source C:\orca-dev
.\install.ps1 -Action update -Source C:\orca-dev
.\install.ps1 -Action status -Source C:\orca-dev
.\install.ps1 -Action verify
.\install.ps1 -Action uninstall -Source C:\orca-dev
.\install.ps1 -Action install -Source C:\orca-dev -Pack todo
```

`-Pack` tek veya virgüllü birden çok bileşen seçer; verilmezse tüm pack'ler kurulur. `-DryRun` işlem provası yapar, `-Version` sürüm seçer, `-Lang tr|en` arayüz dilini seçer, `-NoPause` otomasyon için beklemesiz çalışır.

## Ne yapar?

- Bağımlılıkları ve paralel görevleri yönetir.
- İnceleme kararlarını, düzeltme turlarını ve sonuç raporunu yönetir.
- Duraklatma, sürdürme ve kontrollü iptal sunar.
- Ajan panosunun soluna, her çalışma alanına özel kalıcı bir **Todo** sütunu ekler; Todo maddeleri ajan başlatmaz.
- Kurulum öncesi yedek alır; kaldırmada özgün dosyaları geri yükler.

## Belgeler

**[Kurulum ve kullanım rehberi](docs/USAGE.md)** · [Örnek iş akışı](examples/workflow.json)

[English](README.en.md) · [Teknik tasarım](docs/DESIGN.md) · [Doğrulama](docs/VALIDATION.md) · [MIT lisansı](LICENSE)
