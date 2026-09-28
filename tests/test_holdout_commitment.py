"""Holdout taahhudu: rapor semasi v2 (#17, S1).

Taahhut, ileride acilan holdout'un BU kosunun ayirdigi veri olup
olmadigini sinamaya yarayan tek hash'tir. Burada uc sey sabitleniyor:

  * Ayni icerik -> ayni hash (girdi sirasi ve anahtar sirasi onemsiz).
  * Holdout'a dair herhangi bir sey degisince -> farkli hash; baseline
    icerigi degisince -> AYNI hash (taahhut holdout'a baglidir).
  * Tutarsiz manifest reddedilir ve fonksiyon hicbir dosya acmaz.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fs_audit import filesystem_access, touched_under
from test_dataset import build
from tlab.backtest.baseline import REPORT_SCHEMA_VERSION, report_bytes, run_baseline
from tlab.config import load_config
from tlab.data.dataset import (
    HOLDOUT_COMMITMENT_VERSION,
    DatasetIntegrityError,
    canonical_json,
    holdout_commitment,
    manifest_sha256,
    verify_baseline,
)

SYMBOLS = ("SPY", "QQQ")
Manifest = dict[str, Any]


@pytest.fixture
def built(tmp_path: Path) -> tuple[Path, Manifest]:
    return build(tmp_path, symbols=SYMBOLS)


@pytest.fixture
def manifest(built: tuple[Path, Manifest]) -> Manifest:
    return copy.deepcopy(built[1])


def digest(manifest: Manifest) -> str:
    return holdout_commitment(manifest)["sha256"]


def holdout_entries(manifest: Manifest) -> list[dict[str, Any]]:
    return [item for item in manifest["files"] if item["split"] == "holdout"]


def respec(manifest: Manifest, **changes: Any) -> None:
    """Spec'i degistirir ve hash'ini TUTARLI bicimde yeniden hesaplar."""
    manifest["spec"].update(changes)
    manifest["spec_sha256"] = hashlib.sha256(canonical_json(manifest["spec"])).hexdigest()


# --------------------------------------------------------------------------
# Bicim ve kararlilik
# --------------------------------------------------------------------------


def test_the_commitment_is_a_versioned_sha256(manifest: Manifest) -> None:
    result = holdout_commitment(manifest)
    assert set(result) == {"version", "sha256"}
    assert result["version"] == HOLDOUT_COMMITMENT_VERSION
    assert len(result["sha256"]) == 64
    assert set(result["sha256"]) <= set("0123456789abcdef")


def test_order_does_not_change_the_commitment(manifest: Manifest) -> None:
    """Ayni icerik, farkli sira: ayni hash. JSON'a donus de degistirmez."""
    before = digest(manifest)
    manifest["files"] = [dict(reversed(list(item.items()))) for item in reversed(manifest["files"])]
    manifest["split"]["holdout"].reverse()
    manifest["sessions"]["complete"].reverse()
    assert digest(manifest) == before
    assert digest(json.loads(canonical_json(manifest))) == before


def test_baseline_content_does_not_enter_the_commitment(manifest: Manifest) -> None:
    """Taahhut holdout'a baglidir; baseline icerigi degisse de ayni kalir."""
    before = digest(manifest)
    for item in manifest["files"]:
        if item["split"] == "baseline":
            item["content_sha256"] = "a" * 64
            item["bars"] += 1
    assert digest(manifest) == before


# --------------------------------------------------------------------------
# Holdout'a dair her degisiklik hash'i degistirir
# --------------------------------------------------------------------------


def _content(manifest: Manifest) -> None:
    holdout_entries(manifest)[0]["content_sha256"] = "b" * 64


def _bars(manifest: Manifest) -> None:
    holdout_entries(manifest)[0]["bars"] += 1


def _path(manifest: Manifest) -> None:
    holdout_entries(manifest)[0]["path"] = "holdout/renamed.parquet"


def _spec(manifest: Manifest) -> None:
    respec(manifest, settle_minutes=manifest["spec"]["settle_minutes"] + 1)


def _dataset_id(manifest: Manifest) -> None:
    respec(manifest, dataset_id="other-set")
    manifest["dataset_id"] = "other-set"


def _holdout_day(manifest: Manifest) -> None:
    """Bir holdout gunu, tamamlanmis baska bir gunle degistirilir."""
    new_day = "2026-03-31"
    manifest["sessions"]["complete"].append(new_day)
    manifest["split"]["holdout"][-1] = new_day


def _split(manifest: Manifest) -> None:
    """Bolme siniri kayar: son baseline gunu holdout'a gecer."""
    moved = manifest["split"]["baseline"].pop()
    manifest["split"]["holdout"].insert(0, moved)


def _symbol(manifest: Manifest) -> None:
    manifest["symbols"] = ["SPY", "IWM"]
    for item in manifest["files"]:
        if item["symbol"] == "QQQ":
            item["symbol"] = "IWM"


@pytest.mark.parametrize(
    "change",
    [_content, _bars, _path, _spec, _dataset_id, _holdout_day, _split, _symbol],
    ids=lambda item: item.__name__.strip("_"),
)
def test_any_holdout_change_changes_the_commitment(
    manifest: Manifest, change: Callable[[Manifest], None]
) -> None:
    before = digest(manifest)
    change(manifest)
    assert digest(manifest) != before


# --------------------------------------------------------------------------
# Tutarsiz manifest reddedilir
# --------------------------------------------------------------------------


def _duplicate_symbol(manifest: Manifest) -> None:
    extra = dict(holdout_entries(manifest)[0], path="holdout/extra.parquet")
    manifest["files"].append(extra)


def _duplicate_path(manifest: Manifest) -> None:
    manifest["files"].append(dict(holdout_entries(manifest)[0]))


def _missing_symbol(manifest: Manifest) -> None:
    manifest["files"].remove(holdout_entries(manifest)[0])


def _unknown_symbol(manifest: Manifest) -> None:
    holdout_entries(manifest)[0]["symbol"] = "TSLA"


def _holdout_split_baseline_path(manifest: Manifest) -> None:
    holdout_entries(manifest)[0]["path"] = "baseline/elsewhere.parquet"


def _baseline_split_holdout_path(manifest: Manifest) -> None:
    for item in manifest["files"]:
        if item["split"] == "baseline":
            item["path"] = "holdout/hidden.parquet"
            return


def _unknown_split(manifest: Manifest) -> None:
    holdout_entries(manifest)[0]["split"] = "extra"


def _unsafe_path(manifest: Manifest) -> None:
    holdout_entries(manifest)[0]["path"] = "holdout/../../etc/passwd"


def _uppercase_digest(manifest: Manifest) -> None:
    holdout_entries(manifest)[0]["content_sha256"] = "A" * 64


def _short_digest(manifest: Manifest) -> None:
    holdout_entries(manifest)[0]["content_sha256"] = "a" * 63


def _negative_bars(manifest: Manifest) -> None:
    holdout_entries(manifest)[0]["bars"] = -1


def _bool_bars(manifest: Manifest) -> None:
    holdout_entries(manifest)[0]["bars"] = True


def _text_bars(manifest: Manifest) -> None:
    holdout_entries(manifest)[0]["bars"] = "390"


def _duplicate_day(manifest: Manifest) -> None:
    manifest["split"]["holdout"].append(manifest["split"]["holdout"][0])


def _non_canonical_day(manifest: Manifest) -> None:
    day = date.fromisoformat(manifest["split"]["holdout"][0])
    manifest["split"]["holdout"][0] = f"{day.year}-{day.month}-{day.day}"


def _incomplete_day(manifest: Manifest) -> None:
    manifest["split"]["holdout"].append("2026-03-31")


def _overlapping_day(manifest: Manifest) -> None:
    manifest["split"]["holdout"].append(manifest["split"]["baseline"][0])


def _empty_holdout(manifest: Manifest) -> None:
    manifest["split"]["holdout"] = []


def _stale_spec_hash(manifest: Manifest) -> None:
    manifest["spec"]["settle_minutes"] += 1


def _dataset_id_mismatch(manifest: Manifest) -> None:
    manifest["dataset_id"] = "other-set"


def _duplicate_symbols(manifest: Manifest) -> None:
    manifest["symbols"] = ["SPY", "SPY"]


def _schema(manifest: Manifest) -> None:
    manifest["schema_version"] = 99


@pytest.mark.parametrize(
    "corrupt",
    [
        _duplicate_symbol,
        _duplicate_path,
        _missing_symbol,
        _unknown_symbol,
        _holdout_split_baseline_path,
        _baseline_split_holdout_path,
        _unknown_split,
        _unsafe_path,
        _uppercase_digest,
        _short_digest,
        _negative_bars,
        _bool_bars,
        _text_bars,
        _duplicate_day,
        _non_canonical_day,
        _incomplete_day,
        _overlapping_day,
        _empty_holdout,
        _stale_spec_hash,
        _dataset_id_mismatch,
        _duplicate_symbols,
        _schema,
    ],
    ids=lambda item: item.__name__.strip("_"),
)
def test_an_inconsistent_manifest_is_refused(
    manifest: Manifest, corrupt: Callable[[Manifest], None]
) -> None:
    """Yanlis bir taahhut, taahhut olmamasindan kotudur."""
    holdout_commitment(manifest)  # bozulmadan once gecerli
    corrupt(manifest)
    with pytest.raises(DatasetIntegrityError, match="holdout taahhudu"):
        holdout_commitment(manifest)


# --------------------------------------------------------------------------
# Dosya acmaz; rapora yalnizca surum + hash gider
# --------------------------------------------------------------------------


def test_the_commitment_needs_no_holdout_file(built: tuple[Path, Manifest]) -> None:
    """Holdout dizini SILINMIS olsa da ayni taahhut: dosyadan okunmuyor."""
    dataset, manifest = built
    expected = holdout_commitment(manifest)

    shutil.rmtree(dataset / "holdout")
    verified = verify_baseline(dataset, manifest_sha256(dataset))
    with filesystem_access() as seen:
        assert holdout_commitment(verified.manifest) == expected
    assert not touched_under(seen, dataset), "taahhut veri kumesinde dosya acti"


def test_corrupted_holdout_files_do_not_change_the_commitment(
    built: tuple[Path, Manifest],
) -> None:
    """Taahhut manifest beyanina baglidir; diskteki holdout baytlari okunmaz.

    Holdout acilirken barlardan hash'lerin YENIDEN hesaplanmasi gerekir -
    bu fonksiyon o dogrulamanin yerine gecmez (tasarim belgesi).
    """
    dataset, manifest = built
    expected = holdout_commitment(manifest)
    for item in holdout_entries(manifest):
        (dataset / item["path"]).write_bytes(b"bozuk")
    verified = verify_baseline(dataset, manifest_sha256(dataset))
    assert holdout_commitment(verified.manifest) == expected


def test_the_report_carries_only_version_and_hash(tmp_path: Path) -> None:
    """Rapor v2: holdout icin sayi + taahhut. Yol, dosya ya da icerik hash'i yok."""
    dataset, manifest = build(tmp_path, symbols=SYMBOLS)
    verified = verify_baseline(dataset, manifest_sha256(dataset))
    config = load_config(Path(__file__).resolve().parents[1])
    report = run_baseline(verified, config, code_commit="c0ffee")

    assert report["report_schema"] == REPORT_SCHEMA_VERSION == 2
    assert report["holdout"] == {
        "sessions": len(manifest["split"]["holdout"]),
        "opened": False,
        "commitment": holdout_commitment(manifest),
    }
    assert report["starting_equity_basis"] == "synthetic_assumption"

    text = report_bytes(report).decode()
    for item in holdout_entries(manifest):
        for leaked in (item["path"], item["sha256"], item["content_sha256"]):
            assert leaked not in text, f"rapor holdout girdisini iceriyor: {leaked}"
    for day in manifest["split"]["holdout"]:
        assert day not in text, f"rapor holdout gununu iceriyor: {day}"


def test_an_inconsistent_manifest_stops_the_report(tmp_path: Path) -> None:
    """Taahhut uretilemezse rapor uretilmez (taahhut olcumden once hesaplanir)."""
    dataset, _ = build(tmp_path, symbols=SYMBOLS)
    verified = verify_baseline(dataset, manifest_sha256(dataset))
    verified.manifest["split"]["holdout"] = []
    config = load_config(Path(__file__).resolve().parents[1])
    with pytest.raises(DatasetIntegrityError, match="holdout taahhudu"):
        run_baseline(verified, config, code_commit="c0ffee")
