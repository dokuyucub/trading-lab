# Çalışma Düzeni

Bu dosya projenin git kullanımını tanımlar. Amacı tek bir soruyu her zaman
cevaplayabilmek:

> **"Bu kod geçen hafta çalışıyordu, şimdi çalışmıyor. Ne değişti ve nasıl geri
> dönerim?"**

Para söz konusu olan bir sistemde bu sorunun cevabı dakikalar içinde
bulunabilmeli. Aşağıdaki düzen tam olarak bunun için var.

---

## 1. Dal (branch) modeli

| Dal | Kural |
|---|---|
| `main` | Her zaman çalışır durumda. CI yeşil olmadan buraya hiçbir şey girmez. |
| `feat/...`, `fix/...` | Tüm geliştirme burada yapılır, PR ile `main`'e birleşir. |

`main`'e doğrudan push yapılmaz. Sebep: `main` her an canlıya alınabilecek
sürümü temsil eder; doğrudan push, test edilmemiş kodun canlıya gidebilmesi
demektir.

**GitHub'da bir kez ayarlanması gereken koruma** (Settings → Branches → Add rule,
`main` için):
- Require a pull request before merging
- Require status checks to pass → `quality`
- Include administrators (kendini de kurala dahil et; asıl koruma budur)

## 2. Commit biçimi

[Conventional Commits](https://www.conventionalcommits.org/) kullanıyoruz:

```
<tip>(<kapsam>): <özet>

<neden böyle yapıldığı — ne yapıldığı diff'te zaten görünür>
```

| Tip | Anlamı |
|---|---|
| `feat` | Yeni yetenek |
| `fix` | Hata düzeltmesi |
| `refactor` | Davranış değişmeden yapı değişikliği |
| `test` | Yalnızca test |
| `docs` | Yalnızca belge |
| `chore` / `build` / `ci` | Araç, paketleme, boru hattı |

Bu biçim sadece düzen için değil: sürüm numarasının nasıl artacağını
(`feat` → minor, `fix` → patch) ve değişiklik günlüğünün ne içereceğini
belirler.

**Her commit tek bir işi yapar ve tek başına çalışır durumda bırakır.** Bu
kritik: `git bisect` (aşağıda) ancak commit'ler atomikse işe yarar. On dosyayı
değiştiren tek bir "her şeyi ekledim" commit'i, hatayı bulmanı imkânsızlaştırır.

## 3. Sürüm etiketleri

Kilometre taşı sayılan her sürüm [SemVer](https://semver.org/lang/tr/) ile
etiketlenir:

```bash
git tag -a v0.1.0 -m "Faz 0: salt okunur iskelet"
git push origin v0.1.0
```

- **MAJOR** — geriye dönük uyumsuz değişiklik (ör. journal şeması kırılması)
- **MINOR** — yeni yetenek (ör. yeni strateji)
- **PATCH** — hata düzeltmesi

Etiket, geri dönülebilecek sabit bir noktadır. Faz bittiğinde etiketlenir.

---

## 4. Geri alma rehberi (runbook)

### 4.1 Hangi sürümler var?

```bash
git tag -l -n1                 # etiketler ve açıklamaları
git log --oneline --graph -20  # son commit'ler
```

### 4.2 Eski bir sürüme bakmak (değiştirmeden)

```bash
git switch --detach v0.1.0     # o sürümün haline geç
tlab doctor                    # orada çalışıyor mu, dene
git switch -                   # geldiğin yere dön
```

Bu işlem hiçbir şeyi bozmaz — sadece çalışma dizinini o ana taşır.

### 4.3 İki sürüm arasında ne değişti?

```bash
git diff v0.1.0..v0.2.0                 # tüm fark
git diff v0.1.0..v0.2.0 -- src/tlab/risk/   # sadece risk katmanı
git log v0.1.0..v0.2.0 --oneline        # aradaki commit'ler
```

### 4.4 "Eskiden çalışıyordu" — kıran commit'i bulmak

Profesyonel cevap `git bisect`. İkili arama yapar: 200 commit'lik bir aralıkta
kıran commit'i ~8 denemede bulur.

```bash
git bisect start
git bisect bad                 # şu an bozuk
git bisect good v0.1.0         # burada çalışıyordu
# git her adımda bir commit'e geçer, sen test edip söylersin:
pytest && git bisect good      # veya: git bisect bad
# ...
git bisect reset               # bittiğinde normale dön
```

Testin otomatikse tamamını git'e yaptırabilirsin:

```bash
git bisect start HEAD v0.1.0
git bisect run pytest -q
```

Bu yüzden testler ve atomik commit'ler lüks değil, altyapı: `bisect` ancak
bunlar varsa çalışır.

### 4.5 Bir değişikliği geri almak

**Kural: yayınlanmış geçmiş yeniden yazılmaz.** `git reset --hard` ile
push edilmiş commit'leri silmek, aynı depoda çalışan herkesin (ve canlı
sunucunun) geçmişini bozar.

Doğru yol, değişikliği tersine çeviren **yeni** bir commit üretmektir:

```bash
git revert <commit-sha>                  # tek commit'i geri al
git revert <ilk-sha>..<son-sha>          # bir aralığı geri al
git revert -m 1 <merge-sha>              # bir birleştirmeyi geri al
```

Geçmiş korunur, geri alma da kayıt altına girer.

Sadece tek bir dosyayı eski haline döndürmek için:

```bash
git restore --source=v0.1.0 -- src/tlab/risk/gate.py
```

### 4.6 Acil durum: çalışan eski sürümü ayağa kaldırmak

Canlıda bir şey kırıldıysa, önce hizmeti eski sürüme döndür, sonra sakin kafayla
hatayı ara:

```bash
git switch --detach v0.1.0
docker compose -f docker/docker-compose.yml up -d --build
```

Düzeltme hazır olduğunda `main`'e dön ve yeni sürümü etiketle.

### 4.7 Hangi kod bu sonucu üretti?

Bu projeye özel bir kolaylık: journal'daki her koşu kaydı, o anda çalışan kodun
git commit'ini (`git_sha`), veri feed'ini ve tam yapılandırmasını saklar.

```sql
SELECT run_id, started_at, git_sha, data_feed, params_version FROM runs;
```

Şüpheli bir işlem gördüğünde, onu üreten kodun tam haline `git switch --detach
<git_sha>` ile dönebilirsin. "Bu kararı hangi mantık verdi" sorusu böylece
tahmine değil kayda dayanır.

---

## 5. Push etmeden önce

```bash
make check    # ruff + mypy + pytest
```

CI zaten çalıştıracak, ama kırık commit'in geçmişe girmesini engellemek senin
elinde. Temiz bir geçmiş, `bisect`'in işe yaraması demektir.

`make hooks` ile bu kapılar git kancası olarak da kurulabilir — o zaman
`git commit` kendiliğinden denetler.

## 6. Sürüm çıkarma

```bash
# 1. CHANGELOG'da [Yayınlanmamış] bölümünü sürüm başlığına çevir
# 2. main güncel ve yeşil olsun
git switch main && git pull
make check

# 3. Etiketle ve gönder
git tag -a v0.3.0 -m "Faz 2: backtest motoru"
git push origin v0.3.0
```

Etiket, geri dönülebilecek sabit bir noktadır. Faz bittiğinde etiketlenir.

## 7. Ekip çalışması ve devir

Birden fazla geliştirici (insan ya da ajan) varsa **`AGENTS.md`** geçerlidir:
dal modeli, değişmezler, inceleme kuralları ve koordinasyon kanalları orada.
Claude için giriş noktası `CLAUDE.md`, yarım kalan işlerin devir notları
`docs/handoffs/` altında.

Sıra: görev → kendi dalın → test → PR → bağımsız inceleme → birleştirme.
