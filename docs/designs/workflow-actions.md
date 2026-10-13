# Workflow action sürümleri

Tarih: 2026-10-09. Koordinasyon: #17 (Claude ön raporu 6068215456, Codex
kararı 6071471758).

## Kural

- Beklenen sürümler `tests/test_architecture.py` içinde **açıkça sabit**:
  `ACTION_VERSIONS` (checkout, setup-python) ve `UPLOAD_VERSION`
  (upload-artifact). Bir action'ın bütün kullanımları tek sürümde olmalı.
- Kullandığımız girdiler de testte sabit (`ACTION_INPUTS`,
  `UPLOAD_INPUTS`). Yükseltmenin uyum iddiası **yalnızca bu girdilerle**
  sınırlıdır. Yeni bir girdi bilinçli bir incelemeyle eklenir.
- Yükseltme şunları ister:
  - testteki satırın bilinçli değişikliği;
  - etiketin kaynak incelemesi (`action.yml`, `package.json`, README /
    CHANGELOG);
  - PR'ın kendi hosted kanıtı: quality koşusu ve sentetik gidiş-dönüş.
- Gerçek veri workflow'ları bir yükseltmenin ilk entegrasyon testi olarak
  kullanılmaz.

## Sürüm: checkout v7, setup-python v7 (2026-10-09)

Kaynak: salt okunur klonlar. Etiket commit'leri uzak depoda
(`git ls-remote`) yeniden denetlendi.

| Action | Önceki | Şimdiki | Çalışma ortamı | Runner en az |
|---|---|---|---|---|
| `actions/checkout` | v4 `11d5960a326750d5838078e36cf38b85af677262` | v7 `3d3c42e5aac5ba805825da76410c181273ba90b1` (7.0.1) | node20 → node24 | v2.327.1 |
| `actions/setup-python` | v5 `a26af69be951a213d495a4c3e4e4022e16d87065` | v7 `5fda3b95a4ea91299a34e894583c3862153e4b97` (7.0.0) | node20 → node24 | v2.327.1 |

Hosted runner #44 koşusunda `2.337.0` idi; şart karşılanıyor.

**checkout** (etiketteki README ve CHANGELOG):

- **v5:** node24.
- **v6:** `persist-credentials` kimlik bilgisini `.git/config` yerine
  `$RUNNER_TEMP` altında ayrı bir dosyada tutar. Bizde etkisi yok: bütün
  checkout'lar `persist-credentials: false` (test).
- **v7:** ESM. `pull_request_target` ve `workflow_run` altında fork PR
  checkout'u varsayılan olarak reddedilir. Yeni girdi
  `allow-unsafe-pr-checkout`; bizde hiç kullanılmaz ve bu iki tetikleyici
  hiç yoktur (test).
- **Resmî sürüm notu (Codex okudu, 6071471758):** v7.0.1 —
  <https://github.com/actions/checkout/releases/tag/v7.0.1>: unsafe PR
  kontrolünün varsayılan girdi yolu düzeltmesi, dal adı boşluk ve
  `--unset` kaçış düzeltmeleri.

**setup-python** (etiketteki README):

- **v6:** node20 → node24.
- **v7:** ESM; `pip-install` girdisi kaldırıldı (kullanmıyoruz).
- **Resmî sürüm notu (Codex okudu, 6071471758):** v7.0.0 —
  <https://github.com/actions/setup-python/releases/tag/v7.0.0>: ESM,
  `pip-install`'ın kaldırılması, sürüm manifestinin doğrulanıp yeniden
  denenmesi ve annotation düzeltmeleri.

**Kullandığımız girdiler:**

- checkout: yalnızca `persist-credentials: false` (10 kullanım).
- setup-python: `python-version: "3.12"` (8 kullanım) ve `cache: pip`
  (2 kullanım, `ci.yml`).

**Kapsam sınırı:** "girdi, çıktı ya da davranış değişikliği yok" ifadesi
bütün yükseltmeye genellenmez (Codex 6071471758). İddia yalnızca
yukarıdaki girdilerin uyumudur. Releases API'ye bu oturumdan
erişilemedi; resmî notları Codex okudu.

**Hosted kanıt:** PR'ın kendi koşuları.

- `quality`: checkout, setup-python ve `cache: pip`.
- Gidiş-dönüş: iki checkout. Workflow değiştiği için PR'la tetiklenir.

Gerçek veri, SDK ve paper workflow'ları koşturulmadı.

## Token izinleri (2026-10-09)

Bütün workflow'larda üst düzey `permissions: contents: read`. Her
checkout'ta `persist-credentials: false`. Job düzeyi izin üst düzeyi
genişletmez. Tek gözden geçirilmiş istisna gidiş-dönüşün `verify`
job'undaki `actions: read`; o da yalnızca okuma. Hepsi testle sabit
(`test_every_workflow_token_is_read_only_and_never_persisted`).

Hosted log'un gösterdiği (#46, 2026-10-09; kapsam Codex P3 6139296022 ile
daraltıldı):

- **`persist-credentials: false` yalnızca checkout'un kalıcı kimlik
  yapılandırmasıyla ilgilidir.** Adım bitince token git config'te kalmaz;
  adım içinde geçici bir dosyaya yazılıp silinir ("Removing credentials
  config"). Bir action'ın token'ı açıkça girdi almasını dışlamaz:
  setup-python varsayılan `token` girdisiyle alır (log: `token: ***`).
  Kurulum, lint ve test `run` adımları onu ne ortamdan ne git'ten alır.
- **Eski durum.** v4 ve varsayılan `persist-credentials: true` ile token
  iş sonuna kadar `.git/config`'te kalıyordu; kilitsiz kurulum yapan
  kanaryada da (2026-10-12, run 38266898479).
- **Depo varsayılanı, tarihli gözlem.** main `2ae8a8d` quality job'u
  (2026-10-09, run 37862751688) ve kanarya (2026-10-12): `Contents`,
  `Metadata`, `Packages` read. Değişiklik bir sızıntı düzeltmesi değil,
  sertleştirmedir: izin artık depo ayarına bağlı değil ve `Packages`
  düştü.

## upload-artifact

Sürüm ve kaynak kanıtı: `docs/designs/artifact-roundtrip.md` ("Sürüm: v7").
