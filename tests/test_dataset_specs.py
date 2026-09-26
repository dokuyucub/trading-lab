"""Depodaki veri kumesi tanimlarinin kendi aralarindaki kurallar."""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pytest

from tlab.config import load_config
from tlab.data.dataset import DatasetSpec

SPEC_DIR = Path(__file__).resolve().parents[1] / "config" / "datasets"
SPECS = sorted(SPEC_DIR.glob("*.yaml"))


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
    main = DatasetSpec.from_yaml(SPEC_DIR / "orb-baseline-2026q3.yaml")
    assert set(main.symbols) == universe
