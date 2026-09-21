# tlab calisma imaji.
# Sistem 7/24 calismak uzere tasarlandi; kisisel bilgisayar uyudugunda
# bot durur, bu yuzden hedef kucuk bir sunucuda konteyner olarak kosmasi.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Bagimliliklar once kopyalanir: kaynak degistiginde katman onbellegi korunur.
COPY pyproject.toml README.md requirements.lock ./
COPY src ./src

# Calisma zamani kilidinden kuruluyor (gelistirme araclari yok).
# CI gelistirme kilidini, uretim calisma zamani kilidini kullanir;
# ikisi ayni cozumlemeden uretildigi icin ortak paketlerin surumleri
# ayni. Sabitlenmemis bir imaj, testten gecen surumlerden farkli
# surumlerle calisabilirdi.
RUN pip install --no-cache-dir -r requirements.lock \
    && pip install --no-cache-dir --no-deps -e .

COPY config ./config

# Journal ve onbellek konteyner disinda kalmali; aksi halde her yeniden
# baslatmada sistemin hafizasi silinir.
VOLUME ["/app/data"]

ENTRYPOINT ["tlab"]
CMD ["doctor"]
