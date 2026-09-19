# tlab calisma imaji.
# Sistem 7/24 calismak uzere tasarlandi; kisisel bilgisayar uyudugunda
# bot durur, bu yuzden hedef kucuk bir sunucuda konteyner olarak kosmasi.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Bagimliliklar once kopyalanir: kaynak degistiginde katman onbellegi korunur.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY config ./config

# Journal ve onbellek konteyner disinda kalmali; aksi halde her yeniden
# baslatmada sistemin hafizasi silinir.
VOLUME ["/app/data"]

ENTRYPOINT ["tlab"]
CMD ["doctor"]
