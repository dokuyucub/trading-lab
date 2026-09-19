"""Yapilandirma yukleme ve dogrulama testleri."""

from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from tlab.config import Secrets, load_config, load_secrets
from tlab.core.types import Timeframe
from tlab.errors import ConfigError


def test_loads_valid_config(project_root: Path) -> None:
    config = load_config(project_root)
    assert config.symbols == ("SPY", "AAPL")
    assert config.data.feed == "iex"
    assert config.data.default_timeframe is Timeframe.M1
    assert config.session.regular_open == time(9, 30)
    assert config.risk.max_risk_per_trade_pct == pytest.approx(0.5)


def test_relative_paths_resolve_against_project_root(project_root: Path) -> None:
    config = load_config(project_root)
    assert config.journal_path == project_root / "data" / "journal.db"
    assert config.cache_dir == project_root / "data" / "bars"


def test_symbols_are_normalized_and_deduplicated(project_root: Path) -> None:
    (project_root / "config" / "universe.yaml").write_text(
        "symbols:\n  - spy\n  - ' AAPL '\n  - SPY\n", encoding="utf-8"
    )
    assert load_config(project_root).symbols == ("SPY", "AAPL")


def test_missing_config_file_gives_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="bulunamadi"):
        load_config(tmp_path)


def test_unknown_key_is_rejected(project_root: Path) -> None:
    """Yazim hatasiyla girilmis bir satir sessizce yok sayilmamali.

    Aksi halde risk limiti sandigin degerde olmaz ve bunu ancak
    zarar ettikten sonra fark edersin.
    """
    base = project_root / "config" / "base.yaml"
    base.write_text(base.read_text() + "  max_riskk_per_trade_pct: 99\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(project_root)


def test_invalid_feed_is_rejected(project_root: Path) -> None:
    base = project_root / "config" / "base.yaml"
    base.write_text(base.read_text().replace("feed: iex", "feed: nasdaq"), encoding="utf-8")
    with pytest.raises(ConfigError, match="feed"):
        load_config(project_root)


def test_per_trade_risk_cannot_exceed_daily_loss_limit(project_root: Path) -> None:
    """Tek islemin gunu bitirebildigi bir yapilandirma tutarsizdir."""
    base = project_root / "config" / "base.yaml"
    base.write_text(
        base.read_text().replace("max_risk_per_trade_pct: 0.5", "max_risk_per_trade_pct: 5.0"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="gunluk zarar"):
        load_config(project_root)


def test_session_open_must_precede_close(project_root: Path) -> None:
    base = project_root / "config" / "base.yaml"
    base.write_text(
        base.read_text().replace('regular_open: "09:30"', 'regular_open: "17:00"'),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(project_root)


def test_unknown_timezone_is_rejected(project_root: Path) -> None:
    base = project_root / "config" / "base.yaml"
    base.write_text(base.read_text().replace("America/New_York", "Mars/Olympus"), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(project_root)


# --------------------------------------------------------------------------
# Anahtarlar
# --------------------------------------------------------------------------


def test_secrets_read_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "ALPACA_API_KEY=PKTEST123\nALPACA_SECRET_KEY=secret456\nALPACA_PAPER=true\n",
        encoding="utf-8",
    )
    secrets = load_secrets(tmp_path)
    assert secrets.alpaca_api_key == "PKTEST123"
    assert secrets.alpaca_paper is True
    assert secrets.is_configured


def test_missing_secrets_raise_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(ConfigError, match=r"\.env"):
        load_secrets(tmp_path).require()


def test_masked_output_never_leaks_the_key() -> None:
    """Loglara ve hata ciktilarina anahtar duz metin olarak dusmemeli."""
    secret_value = "sk-super-secret-value-9999"  # noqa: S105 - testin konusu bu
    secrets = Secrets(_env_file=None, alpaca_api_key="PKABCDEFGH", alpaca_secret_key=secret_value)
    rendered = str(secrets.masked())
    assert secret_value not in rendered
    assert "PKABCDEFGH" not in rendered
    assert "PKAB" in rendered


def test_paper_mode_defaults_to_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Varsayilan guvenli taraf olmali: kaza ile canli para kullanilmasin.

    `_env_file=None` bilincli: test, calistirildigi makinedeki gercek
    .env dosyasindan etkilenmemeli.
    """
    monkeypatch.delenv("ALPACA_PAPER", raising=False)
    assert Secrets(_env_file=None).alpaca_paper is True
