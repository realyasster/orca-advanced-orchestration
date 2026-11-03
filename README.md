# Orca Advanced Orchestration

Orca'da Codex ve Claude gibi ajanların görevlerini otomatik sıraya koyar. İş akışını bir kez tanımlarsınız; bir görev bitince sıradaki başlar, bağımsız görevler paralel çalışır.

Örnek: **Kod yaz → Test ve incelemeyi paralel çalıştır → Gerekirse düzelt → Sonucu raporla.**

## Ne sağlar?

- Ajanları tek tek başlatma ve sürekli durum kontrolü ihtiyacını azaltır.
- Görev bağımlılıklarını, çalışma alanı paylaşımını ve inceleme kararlarını yönetir.
- Akışı duraklatma, sürdürme ve iptal etme desteği sunar.
- Rutin geçişlerdeki gereksiz koordinatör çağrılarını azaltmayı hedefler; ajanlar token tüketmeye devam eder.

## Kurulum

Bu depo, **Orca v1.4.246 kaynak koduna uygulanan bir değişiklik paketidir**. Kurulum aracı kaynak dosyaları yedekler ve değişiklikleri uygular; ardından Orca'yı derlemeniz gerekir. Bağımsız uygulama veya plugin değildir.

**[Kurulum ve kullanım rehberi](docs/USAGE.md)** · [Örnek iş akışı](examples/workflow.json)

[English](README.en.md) · [Teknik tasarım](docs/DESIGN.md) · [Test sonuçları ve bilinen sınırlamalar](docs/VALIDATION.md) · [MIT lisansı](LICENSE)
