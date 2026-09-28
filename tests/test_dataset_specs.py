"""Depodaki veri kumesi tanimlarinin kendi aralarindaki kurallar."""

from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import combinations
from pathlib import Path

import pytest

from test_dataset import FakeBars, FakeCalendar, minute_bars, session, weekdays
from tlab.config import load_config
from tlab.data.dataset import DatasetSpec, build_dataset, manifest_sha256, verify_baseline
from tlab.strategies.orb import ORBParams

SPEC_DIR = Path(__file__).resolve().parents[1] / "config" / "datasets"
SPECS = sorted(SPEC_DIR.glob("*.yaml"))

MAIN_SPEC = SPEC_DIR / "orb-baseline-2026q3-u11.yaml"
PILOT_SPECS = (SPEC_DIR / "pilot-2026-06-u12.yaml", SPEC_DIR / "pilot-2026-05-u12.yaml")

PILOT_SYMBOLS = (
    "SPY",
    "QQQ",
    "IWM",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMD",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "JPM",
)
"""Iki pilotun GERCEKTEN olctugu 12 sembol. Tarihsel kayit: evren
degisse bile bu liste degismez."""

REMOVED_FROM_MAIN = frozenset({"JPM"})
"""Pilotlardan sonra ana tanimdan cikarilan semboller ve yalnizca bunlar.
Gerekce veri kalitesi (#17); performans asla."""

PREVIOUS_MAIN = {
    "status": "draft",
    "timeframe": "1Min",
    "feed": "iex",
    "adjustment": "raw",
    "start": "2026-06-22",
    "end": "2026-09-18",
    "exchange_timezone": "America/New_York",
    "holdout_fraction": 0.2,
    "split_unit": "session",
    "settle_minutes": 20,
    "retention_days": 90,
    "quality": {
        "open_window_minutes": 15,
        "max_missing_open_window": 0,
        "close_window_minutes": 10,
        "max_missing_fraction": 0.1,
        "max_ineligible_sessions": 0,
    },
}
"""Kaldirilan `orb-baseline-2026q3` tanimin kimlik ve semboller disindaki
alanlari (e99a9bc). TARIHSEL kayit: `status` o gunku `draft` degeridir.
Yeni kimlik YALNIZCA sembol kumesini, onay commit'i YALNIZCA `status`'u
degistirdi; tarih, feed, bolme veya kalite esigi bu vesileyle sessizce
kaymasin."""


def test_there_are_dataset_specs() -> None:
    assert SPECS, "config/datasets/ bos"


@pytest.mark.parametrize("path", SPECS, ids=lambda item: item.stem)
def test_every_spec_is_valid_and_named_after_its_file(path: Path) -> None:
    """Dosya adi ile dataset_id ayni olmali; aksi halde hangi tanimin
    hangi veriyi urettigi karisir."""
    spec = DatasetSpec.from_yaml(path)
    assert spec.dataset_id == path.stem


def test_no_two_datasets_share_a_single_day() -> None:
    """Iki veri kumesinin tarih araligi ORTUSMEMELI.

    Ortusme olsaydi, bir kume uzerinde yapilan deneme digerinin
    holdout gunlerini gorebilirdi. Ornek: pilotun tarihleri ana
    kumenin son haftasina denk gelseydi, pilot bir "erisim denemesi"
    kiliginda ana kumenin holdout'una bakis olurdu.
    """
    specs = [DatasetSpec.from_yaml(path) for path in SPECS]
    for left, right in combinations(specs, 2):
        overlap = left.start <= right.end and right.start <= left.end
        assert not overlap, (
            f"{left.dataset_id} ({left.start}..{left.end}) ile "
            f"{right.dataset_id} ({right.start}..{right.end}) ortusuyor"
        )


def test_the_main_dataset_covers_the_trading_universe() -> None:
    """Ana olcum, sistemin gercekte islem yaptigi evren uzerinde."""
    universe = set(load_config(Path(__file__).resolve().parents[1]).symbols)
    main = DatasetSpec.from_yaml(MAIN_SPEC)
    assert set(main.symbols) == universe


def test_there_is_exactly_one_main_dataset() -> None:
    """Aktif ana tanim tek. Eski kimlik kaldirilir (metni Git gecmisinde);
    ayni tarihlerle iki tanim, ortusmezlik testine istisna isterdi."""
    mains = [path.stem for path in SPECS if not path.stem.startswith("pilot-")]
    assert mains == [MAIN_SPEC.stem]


@pytest.mark.parametrize("path", PILOT_SPECS, ids=lambda item: item.stem)
def test_the_pilots_keep_the_symbols_they_actually_measured(path: Path) -> None:
    """Pilotlar tarihsel kayittir: 12 sembolle olculduler (#17).

    Evren daraldiginda pilot tanimlarini "guncellemek", olculmus bir
    sonucu olculmemis bir tanimla eslestirirdi. Esikler bu 12 sembolun
    tamamiyla olculdu; JPM'nin bosluk orani da ancak boyle goruldu.
    """
    pilot = DatasetSpec.from_yaml(path)
    assert pilot.symbols == PILOT_SYMBOLS
    assert pilot.status == "pilot"


def test_the_main_dataset_drops_only_the_documented_symbols() -> None:
    """Ana tanim = pilotta olculen semboller - veri kalitesiyle cikarilanlar.

    Pilotta olculmemis bir sembol ana olcume giremez; cikarilan her
    sembol burada gerekcesiyle yazili olmali.
    """
    main = DatasetSpec.from_yaml(MAIN_SPEC)
    assert set(main.symbols) <= set(PILOT_SYMBOLS)
    assert set(PILOT_SYMBOLS) - set(main.symbols) == REMOVED_FROM_MAIN


def test_the_new_main_id_changes_nothing_but_the_symbols() -> None:
    """Kimlik degisimi yalnizca sembol kumesini, onay yalnizca durumu
    degistirdi (#17). Tarih, feed, bolme ve kalite esikleri sabit."""
    main = DatasetSpec.from_yaml(MAIN_SPEC)
    unchanged = {key: value for key, value in PREVIOUS_MAIN.items() if key != "status"}
    assert main.model_dump(mode="json", exclude={"dataset_id", "symbols", "status"}) == unchanged


@pytest.mark.parametrize("path", SPECS, ids=lambda item: item.stem)
def test_every_spec_states_its_quality_policy_explicitly(path: Path) -> None:
    """Politika varsayilandan sessizce gelmesin; dosyada yazili olsun."""
    raw = path.read_text(encoding="utf-8")
    assert "\nquality:\n" in raw


def test_the_main_dataset_is_approved_only_by_its_own_decision() -> None:
    """Ana tanim AYRI ve incelenen bir commit ile approved oldu (#17).

    Bu test o commit'te BILINCLI olarak guncellendi (onceki hali: draft).
    Pilotlar pilot kalir: P&L uretemezler.
    """
    main = DatasetSpec.from_yaml(MAIN_SPEC)
    assert main.status == "approved"
    for path in PILOT_SPECS:
        assert DatasetSpec.from_yaml(path).status == "pilot"


def test_the_approved_spec_passes_the_policy_gate_with_the_repo_config(tmp_path: Path) -> None:
    """On ucus: gercek ana tanimin politikasi ve depodaki gercek ayarlar,
    olcumun P&L'den onceki politika kapisindan geciyor.

    Onaydan sonra biri config'i (orn. gun sonu tamponunu) degistirirse
    gercek kosu "politika tutarsiz" diye durur; bu test onu ONCEDEN
    yakalar. Veri sentetik ve kisa; tanimin tarihleri degil POLITIKASI
    ve sembolleri kullaniliyor.
    """
    main = DatasetSpec.from_yaml(MAIN_SPEC)
    days = weekdays(date(2026, 3, 2), 10)
    sessions = [session(day) for day in days]
    bars = {
        symbol: [bar for item in sessions for bar in minute_bars(symbol, item)]
        for symbol in main.symbols
    }
    out = tmp_path / "ds"
    build_dataset(
        main.model_copy(update={"start": days[0], "end": days[-1]}),
        bars_source=FakeBars(bars),
        calendar_source=FakeCalendar(sessions),
        out_dir=out,
        downloaded_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        producer={"run_id": "test", "commit": "0" * 40},
    )
    verified = verify_baseline(out, manifest_sha256(out))
    config = load_config(Path(__file__).resolve().parents[1])
    measurable = verified.measurable_sessions(
        opening_range_minutes=ORBParams().opening_range_minutes,
        flatten_before_close_minutes=config.session.flatten_before_close_minutes,
    )
    assert len(measurable) == len(verified.sessions)


def test_the_extra_pilot_changes_only_the_window() -> None:
    """Ek pilot ilk pilotla AYNI olcumu genis pencerede tekrarlar (#17).

    Sembol, feed, duzeltme, zaman dilimi ve kalite politikasi degisirse
    iki sonuc karsilastirilamaz - ve "politika gevsetilmez" karari
    sessizce delinmis olur. Yalnizca kimlik ve tarihler farkli olabilir.
    """
    first = DatasetSpec.from_yaml(SPEC_DIR / "pilot-2026-06-u12.yaml")
    extra = DatasetSpec.from_yaml(SPEC_DIR / "pilot-2026-05-u12.yaml")
    ignored = {"dataset_id", "start", "end"}
    assert first.model_dump(exclude=ignored) == extra.model_dump(exclude=ignored)
    assert extra.status == "pilot"
    assert extra.end < first.start, "ek pilot ilk pilottan once bitmeli"
