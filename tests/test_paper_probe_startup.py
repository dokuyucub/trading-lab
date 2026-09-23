"""Workflow giris noktasinin GERCEKTEN baslayabildigini kanitlar.

Fikir Codex'e ait (PR #16) ve dogru fikirdi: importlari INCELEMEK
yetmez, komutu CALISTIRMAK gerekir. Ilk gercek kosuda dusen sey tam
da buydu - butun testler yesilken workflow'un actigi komut
"ModuleNotFoundError: No module named 'pandas'" ile duruyordu.

Iki bilincli tercih var:

1. `unittest`, pytest degil. Bu dosya CI'da GELISTIRME PAKETLERI
   KURULMADAN once kosuyor; pytest'e bagli olsaydi kosamazdi.

2. Hicbir sey kurulmadan kosuyor - requirements.lock bile. Prob
   bagimliliksiz calisacak sekilde tasarlandi; test de o iddiayi
   oldugu gibi sinar. Kurulumdan sonra kosan bir test, iddianin
   yarisini olcerdi.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path


class PaperProbeStartupTest(unittest.TestCase):
    def test_module_reaches_configuration_check_without_credentials(self) -> None:
        """Anahtarsiz calistir: ag'a cikmadan kendi kontrolune ulasmali.

        Basarili sonuc "prob calisiyor" demek degil; "prob BASLAYABILIYOR"
        demek. Gercek baglanti ayri bir sey ve elle tetikleniyor.
        """
        repo = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-m", "tlab.paper_probe"],
            cwd=repo,
            env={
                **os.environ,
                "PYTHONPATH": str(repo / "src"),
                "ALPACA_PAPER_API_KEY": "",
                "ALPACA_PAPER_SECRET_KEY": "",
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "FAIL configuration: paper key and secret are required\n")
        self.assertEqual(result.stderr, "")
