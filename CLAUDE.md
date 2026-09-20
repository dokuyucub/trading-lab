# CLAUDE.md

Bu projede birden fazla geliştirici çalışıyor. Ortak kurallar, değişmezler ve
dal/PR akışı **`AGENTS.md`** içinde — kod yazmadan önce onu oku.

Kısa özet:

- Kendi dalında çalış, başkasının dalına push etme, `main`'e PR ile gir.
- Push etmeden önce `make check` (ruff + mypy + pytest).
- Mimari değişmezler `tests/test_architecture.py` tarafından denetleniyor;
  biri kırmızıya dönerse sebebini test mesajı söyler.
- Mimari: `README.md`. Git geri alma rehberi: `CONTRIBUTING.md`.
