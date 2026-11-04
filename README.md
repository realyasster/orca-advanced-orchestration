# Orca Advanced Orchestration

Orca'da Codex ve Claude gibi ajanların görevlerini otomatik sıraya koyar. İş akışını bir kez tanımlarsınız; bir görev bitince sıradaki başlar, bağımsız görevler paralel çalışır.

Örnek: **Kod yaz → Test ve incelemeyi paralel çalıştır → Gerekirse düzelt → Sonucu raporla.**

## Ne sağlar?

- Ajanları tek tek başlatma ve sürekli durum kontrolü ihtiyacını azaltır.
- Görev bağımlılıklarını, çalışma alanı paylaşımını ve inceleme kararlarını yönetir.
- Akışı duraklatma, sürdürme ve iptal etme desteği sunar.
- Ajan panosunun soluna, her çalışma alanına özel kalıcı bir **Todo** sütunu ekler; bu maddeler ajan başlatmaz ve ajan durumlarından ayrı tutulur.
- Kurulum sırasında **Orchestrator** ve **Todo** bileşenleri ayrı ayrı seçilebilir; tek paket içinden yalnızca seçilen dosya grubu kurulur.
- Rutin geçişlerdeki gereksiz koordinatör çağrılarını azaltmayı hedefler; ajanlar token tüketmeye devam eder.

## Kurulum

Bu depo, **Orca v1.4.246 kaynak koduna uygulanan bir değişiklik paketidir**. Kurulum aracı kaynak dosyaları yedekler ve değişiklikleri uygular; ardından Orca'yı derlemeniz gerekir. Bağımsız uygulama veya plugin değildir.

Hızlı başlangıç (Windows PowerShell):

```powershell
irm https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/b9f7e62f3ea89ba51e4e102817c16920b473a7fe/install.ps1 | iex
```

Kurulum menüsünde **Orchestrator** ve **Todo** bileşenlerini ayrı ayrı seçebilirsiniz.

**[Kurulum ve kullanım rehberi](docs/USAGE.md)** · [Örnek iş akışı](examples/workflow.json)

[English](README.en.md) · [Teknik tasarım](docs/DESIGN.md) · [Test sonuçları ve bilinen sınırlamalar](docs/VALIDATION.md) · [MIT lisansı](LICENSE)
