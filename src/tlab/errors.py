"""Sistem genelinde kullanilan hata tipleri.

Her hata tek bir katmana ait. Bir katmanin hatasi ust katmana ancak
kendi tipine sarilarak cikar; boylece "nerede kirildi" sorusu
stack trace okumadan cevaplanabilir.
"""


class TradingLabError(Exception):
    """Tum tlab hatalarinin ortak atasi."""


class ConfigError(TradingLabError):
    """Yapilandirma eksik, gecersiz veya celiskili."""


class DataError(TradingLabError):
    """Piyasa verisi alinamadi veya beklenen sekilde degil."""


class BrokerError(TradingLabError):
    """Broker ile iletisimde hata (baglanti, yetki, emir reddi)."""


class JournalError(TradingLabError):
    """Journal veritabani islemi basarisiz."""
