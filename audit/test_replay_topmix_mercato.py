#!/usr/bin/env python3
"""test_replay_topmix_mercato.py — il replay di ``topmix_mercato_v3`` e' fedele.

Cosa viene provato (commessa "quote live nel Top Mix", punto 8 e 9):

* i NUMERI DI RIFERIMENTO del replay sono quelli scritti nel referto della
  PR #49 (``audit/results/onex2_market_test.md``): il test li rilegge dal
  markdown, quindi un referto aggiornato senza aggiornare il replay (o il
  contrario) fa fallire la suite invece di passare in silenzio;
* il de-vig di PRODUZIONE (``market_odds.devig_proporzionale``) e' la stessa
  formula usata dalla PR #49 (``backtest_experiment_all.devig_1x2``);
* ``riassunto``/``confronta`` contano bene su righe sintetiche note e
  SEGNALANO una differenza invece di nasconderla (una sola riga sbagliata su
  mille deve far fallire il confronto);
* ``scrivi_referto`` riporta le differenze quando ci sono e la parola PARITÀ
  quando non ce ne sono;
* la SELEZIONE di riga e' la funzione di produzione
  ``app.seleziona_riga_top_mix_mercato``, non una sua copia.

Il giro COMPLETO sul frame storico (85 s circa: Poisson di produzione
intercettato + Elo walker + quote dei CSV) non sta nella suite veloce: lo esegue
il check CI ``Audit`` con ``python audit/replay_topmix_mercato.py``, che esce
con codice 1 se i numeri non tornano. Qui ``TestGiroCompleto`` lo rifà solo se
la cache del frame esiste gia' (oppure con ``REPLAY_MERCATO_FULL=1``).
"""
from __future__ import annotations

import math
import os
import re
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_REPO_ROOT, "SoccerMath")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

import market_odds as MO  # noqa: E402
import replay_topmix_mercato as RTM  # noqa: E402
from backtest_experiment_all import devig_1x2  # noqa: E402

REFERTO_PR49 = os.path.join(_HERE, "results", "onex2_market_test.md")


def _riga(esito_reale, ammessa, esito, accordo=False, scelta_modello=True,
          consenso=None, esito_modello=None, vincente_modello=None):
    return {
        "league": "Serie A", "season": "2024/25", "date": "2025-05-01",
        "home": "A", "away": "B", "esito_reale": esito_reale,
        "ammessa": ammessa, "esito": esito,
        "prob_mercato": 0.6 if ammessa else None,
        "quota": 1.7 if ammessa else None,
        "prob_modello": 0.58,
        "accordo": accordo,
        "vincente": bool(ammessa and esito == esito_reale),
        "consenso_pr49": consenso if consenso is not None else accordo,
        "scelta_modello_ammessa": scelta_modello,
        "esito_modello": esito_modello if esito_modello is not None else esito,
        "vincente_modello": (vincente_modello if vincente_modello is not None
                             else bool(esito_modello == esito_reale)),
    }


class TestRiferimentiDellaPR49(unittest.TestCase):
    """I numeri attesi dal replay stanno nel referto della PR #49, non a memoria."""

    @classmethod
    def setUpClass(cls):
        with open(REFERTO_PR49, encoding="utf-8") as fh:
            cls.testo = fh.read()

    def _coppia(self, pattern, etichetta):
        m = re.search(pattern, self.testo)
        self.assertIsNotNone(m, f"riga '{etichetta}' non trovata in onex2_market_test.md")
        return int(m.group(1)), float(m.group(2))

    def test_scelte_di_mercato_del_referto(self):
        n, hit = self._coppia(
            r"\| pooled OOS \| Mercato B365 pre-chiusura \(prop\.\) \| (\d+) \| [\d,.]+% \| "
            r"([\d.]+) \[", "scelte del mercato")
        atteso = RTM.RIFERIMENTO_PR49["scelte_mercato"]
        self.assertEqual(atteso["n"], n)
        self.assertAlmostEqual(atteso["hit"], hit, places=4)

    def test_accordo_e_senza_accordo_del_referto(self):
        n_acc, hit_acc = self._coppia(
            r"\| Scelte del modello CON consenso di mercato \| (\d+) \| ([\d.]+) \[",
            "scelte del modello CON consenso")
        n_no, hit_no = self._coppia(
            r"\| Scelte del modello SENZA consenso di mercato \| (\d+) \| ([\d.]+) \[",
            "scelte del modello SENZA consenso")
        self.assertEqual((RTM.RIFERIMENTO_PR49["accordo"]["n"],
                          round(RTM.RIFERIMENTO_PR49["accordo"]["hit"], 4)),
                         (n_acc, round(hit_acc, 4)))
        self.assertEqual((RTM.RIFERIMENTO_PR49["senza_accordo"]["n"],
                          round(RTM.RIFERIMENTO_PR49["senza_accordo"]["hit"], 4)),
                         (n_no, round(hit_no, 4)))

    def test_le_tre_voci_sono_distinte_e_coerenti(self):
        """L'accordo e' un sottoinsieme delle scelte del mercato: n_acc <= n_mkt."""
        ref = RTM.RIFERIMENTO_PR49
        self.assertLess(ref["accordo"]["n"], ref["scelte_mercato"]["n"])
        self.assertLess(ref["senza_accordo"]["n"], ref["accordo"]["n"])
        self.assertGreater(ref["accordo"]["hit"], ref["senza_accordo"]["hit"],
                           "l'accordo deve valere di piu' della sua assenza: e' il motivo "
                           "per cui il modello serve a scartare")


class TestDevigUgualeAllaPR49(unittest.TestCase):
    """Il de-vig di produzione e' la formula della PR #49 (nessuna riscrittura)."""

    def test_identico_su_terne_qualunque(self):
        casi = [(1.62, 4.1, 6.0), (2.4, 3.2, 3.0), (1.05, 12.0, 41.0),
                (3.3, 3.3, 3.3), (1.5, 4.5, 7.0), (2.05, 3.6, 3.75)]
        for terna in casi:
            produzione = MO.devig_proporzionale(terna)
            pr49 = devig_1x2(*terna)          # la PR #49 ritorna la terna (p1, pX, p2)
            self.assertIsNotNone(produzione, terna)
            self.assertEqual(3, len(pr49))
            for i in range(3):
                self.assertAlmostEqual(pr49[i], produzione[i], places=12, msg=str(terna))
            self.assertAlmostEqual(1.0, sum(produzione), places=12)
            self.assertIsNone(devig_1x2(0.9, 4.0, 5.0)[0])

    def test_terne_non_valide_danno_none_come_la_pr49(self):
        for terna in ((0.9, 4.0, 5.0), (1.6, None, 6.0), (1.6, 4.0), (1.6, 4.0, float("nan"))):
            self.assertIsNone(MO.devig_proporzionale(terna), terna)


class TestRiassuntoSuRigheSintetiche(unittest.TestCase):
    """Conteggi e hit rate su un campione costruito a mano (esito noto)."""

    def setUp(self):
        # Campione costruito a mano, con i conti scritti qui a fianco:
        #   scelte del mercato        10 (7 vinte)   -> hit 0,70
        #   modello CON accordo        3 (3 vinte)   -> hit 1,00
        #   modello SENZA accordo      4 (2 vinte)   -> hit 0,50
        self.righe = []
        for i in range(3):      # scelte vinte CON accordo del modello
            self.righe.append(_riga("1", True, "1", accordo=True, consenso=True,
                                    esito_modello="1"))
        for i in range(4):      # scelte vinte SENZA accordo, modello fuori soglia
            self.righe.append(_riga("1", True, "1", accordo=False, consenso=False,
                                    scelta_modello=False, esito_modello="X"))
        for i in range(3):      # scelte perse, modello fuori soglia
            self.righe.append(_riga("2", True, "1", accordo=False, consenso=False,
                                    scelta_modello=False, esito_modello="X"))
        for i in range(2):      # modello ammesso SENZA consenso: azzeccato
            self.righe.append(_riga("X", False, None, scelta_modello=True,
                                    consenso=False, esito_modello="X"))
        for i in range(2):      # modello ammesso SENZA consenso: sbagliato
            self.righe.append(_riga("1", False, None, scelta_modello=True,
                                    consenso=False, esito_modello="X"))
        self.r = RTM.riassunto(__import__("pandas").DataFrame(self.righe))

    def test_scelte_di_mercato(self):
        g = self.r["scelte_mercato"]
        self.assertEqual(10, g["n"])
        self.assertEqual(7, g["vinte"])
        self.assertAlmostEqual(0.7, g["hit"])
        lo, hi = g["hit_ic"]
        self.assertLess(lo, 0.7)
        self.assertGreater(hi, 0.7)

    def test_gruppo_accordo(self):
        g = self.r["accordo"]
        self.assertEqual(3, g["n"])
        self.assertEqual(3, g["vinte"])
        self.assertAlmostEqual(1.0, g["hit"])

    def test_gruppo_senza_accordo(self):
        g = self.r["senza_accordo"]
        self.assertEqual(4, g["n"])
        self.assertEqual(2, g["vinte"])
        self.assertAlmostEqual(0.5, g["hit"])

    def test_campione_vuoto_non_divide_per_zero(self):
        import pandas as pd
        r = RTM.riassunto(pd.DataFrame([_riga("1", False, None, scelta_modello=False)]))
        self.assertEqual(0, r["scelte_mercato"]["n"])
        self.assertIsNone(r["scelte_mercato"]["hit"])
        self.assertEqual(0, r["accordo"]["n"])
        self.assertEqual([0.0, 1.0], r["scelte_mercato"]["hit_ic"])

    def test_wilson_contiene_il_punto_e_cresce_con_n(self):
        lo1, hi1 = RTM.wilson(7, 10)
        lo2, hi2 = RTM.wilson(700, 1000)
        self.assertLess(lo1, 0.7)
        self.assertGreater(hi1, 0.7)
        self.assertLess(hi2 - lo2, hi1 - lo1, "piu' dati -> intervallo piu' stretto")
        self.assertEqual((0.0, 1.0), RTM.wilson(0, 0))


class TestConfrontoSegnalaLeDifferenze(unittest.TestCase):
    """Una differenza DEVE uscire: il replay non aggiusta in silenzio."""

    def _riass(self, n_mkt=1302, hit_mkt=0.6751, n_acc=1144, hit_acc=0.6818,
               n_no=335, hit_no=0.4358):
        return {
            "righe_campione": 3504,
            "scelte_mercato": {"n": n_mkt, "vinte": round(hit_mkt * n_mkt), "hit": hit_mkt,
                               "hit_ic": [0.64, 0.70]},
            "accordo": {"n": n_acc, "vinte": round(hit_acc * n_acc), "hit": hit_acc,
                        "hit_ic": [0.65, 0.71]},
            "senza_accordo": {"n": n_no, "vinte": round(hit_no * n_no), "hit": hit_no,
                              "hit_ic": [0.38, 0.49]},
            "scelte_mercato_con_accordo": {"n": n_acc, "vinte": 1, "hit": 0.5},
            "scelte_mercato_senza_accordo": {"n": n_mkt - n_acc, "vinte": 1, "hit": 0.5},
        }

    def test_parita_esatta(self):
        righe, parita = RTM.confronta(self._riass(), 0, 0.0005)
        self.assertTrue(parita, righe)
        self.assertTrue(all(r["coincide"] for r in righe))
        self.assertTrue(all(r["delta_n"] == 0 for r in righe))

    def test_una_scelta_in_piu_rompe_la_parita(self):
        _righe, parita = RTM.confronta(self._riass(n_mkt=1303), 0, 0.0005)
        self.assertFalse(parita)

    def test_hit_rate_diverso_rompe_la_parita(self):
        _righe, parita = RTM.confronta(self._riass(hit_acc=0.69), 0, 0.0005)
        self.assertFalse(parita)

    def test_la_tolleranza_dichiarata_fa_passare_lo_scarto_entro_il_limite(self):
        _righe, parita = RTM.confronta(self._riass(n_mkt=1302, hit_mkt=0.6750), 0, 0.0005)
        self.assertTrue(parita)
        _righe, parita = RTM.confronta(self._riass(n_mkt=1305, hit_mkt=0.6751), 3, 0.0005)
        self.assertTrue(parita)
        _righe, parita = RTM.confronta(self._riass(n_mkt=1306, hit_mkt=0.6751), 3, 0.0005)
        self.assertFalse(parita)

    def test_il_referto_scrive_le_differenze_e_la_parita(self):
        payload = {"generato_il": "2026-10-09T10:00:00Z",
                   "git": {"commit": "abc1234", "branch": "x"},
                   "max_scarto_devig": 0.0, "tolleranza_n": 0, "tolleranza_hit": 0.0005,
                   "limiti": ["limite di prova"],
                   "riassunto": self._riass(), "confronto": None, "parita": True}
        righe, parita = RTM.confronta(payload["riassunto"], 0, 0.0005)
        payload["confronto"], payload["parita"] = righe, parita
        testo = RTM.scrivi_referto(payload)
        self.assertIn("PARITÀ", testo)
        self.assertIn("1302", testo)
        self.assertIn("0.6751", testo)
        # ora con una differenza: il referto deve dirlo, non tacerlo
        righe2, parita2 = RTM.confronta(self._riass(n_acc=1100, hit_acc=0.66), 0, 0.0005)
        payload2 = dict(payload, confronto=righe2, parita=parita2)
        testo2 = RTM.scrivi_referto(payload2)
        self.assertIn("DIFFERENZE PRESENTI", testo2)
        self.assertIn("NON sono state corrette", testo2)
        self.assertIn("| -44 |", testo2.replace(" |", " |"))

    def test_il_referto_dichiara_i_limiti(self):
        payload = {"generato_il": "x", "git": {"commit": "c", "branch": "b"},
                   "max_scarto_devig": 1.5e-17, "tolleranza_n": 0, "tolleranza_hit": 0.0005,
                   "riassunto": self._riass(), "confronto": None, "parita": True,
                   "limiti": ["Le quote sono quelle dei CSV storici"]}
        righe, parita = RTM.confronta(payload["riassunto"], 0, 0.0005)
        payload["confronto"], payload["parita"] = righe, parita
        payload["limiti"] = ["Le quote sono quelle dei CSV storici",
                             "Il replay usa intervalli Wilson, non bootstrap a blocchi",
                             "La colonna fonte vale pinnacle per costruzione"]
        testo = RTM.scrivi_referto(payload)
        self.assertIn("CSV storici", testo)
        self.assertIn("Wilson", testo)
        self.assertIn("pinnacle", testo)
        self.assertIn("## 3. Limiti dichiarati", testo)


class TestIlSelettoreEQuelloDiProduzione(unittest.TestCase):
    """Il replay deve chiamare la funzione dell'app, non una sua copia."""

    def test_applica_selettore_usa_la_funzione_di_app(self):
        import inspect
        src = inspect.getsource(RTM.applica_selettore)
        self.assertIn("prod_app.seleziona_riga_top_mix_mercato", src)
        self.assertIn("MO.devig_proporzionale", src)
        self.assertNotIn("def seleziona", src, "nessuna copia locale del selettore")

    def test_la_soglia_del_selettore_e_quella_della_pr49(self):
        import app
        self.assertEqual(0.55, MO.SOGLIA_TOPMIX_MERCATO)
        self.assertEqual(0.55, MO.SOGLIA_ACCORDO)
        # sotto soglia non entra, sulla soglia entra (>= e non >)
        self.assertIsNone(app.seleziona_riga_top_mix_mercato(
            {"1": 0.549, "X": 0.30, "2": 0.151}, {"1": 1.9, "X": 3.4, "2": 6.6},
            {"1": 0.60, "X": 0.25, "2": 0.15}, home="Inter", away="Roma"))
        riga = app.seleziona_riga_top_mix_mercato(
            {"1": 0.55, "X": 0.30, "2": 0.15}, {"1": 1.9, "X": 3.4, "2": 6.6},
            {"1": 0.60, "X": 0.25, "2": 0.15}, home="Inter", away="Roma")
        self.assertEqual("1", riga["esito"])

    def test_campionatura_solo_stagioni_di_valutazione(self):
        import pandas as pd
        df = pd.DataFrame([
            {"season": "2024/25", "has_model": True, "pre_ok": True},
            {"season": "2025/26", "has_model": True, "pre_ok": True},
            {"season": "2022/23", "has_model": True, "pre_ok": True},   # in-sample
            {"season": "2026/27", "has_model": True, "pre_ok": False},  # senza quote
            {"season": "2025/26", "has_model": False, "pre_ok": True},  # senza modello
        ])
        self.assertEqual([0, 1], list(RTM.campionatura(df).index))


class TestGiroCompleto(unittest.TestCase):
    """Giro completo sul frame storico: solo con la cache o con REPLAY_MERCATO_FULL=1.

    In CI lo esegue il check ``Audit`` invocando lo script, che esce con codice 1
    se i numeri della PR #49 non tornano.
    """

    @classmethod
    def setUpClass(cls):
        if not (os.path.exists(RTM.CACHE_PATH)
                or os.environ.get("REPLAY_MERCATO_FULL") == "1"):
            raise unittest.SkipTest(
                f"cache del frame assente ({RTM.CACHE_PATH}): il giro completo dura "
                f"~85 s, si esegue nel check CI Audit oppure con REPLAY_MERCATO_FULL=1")
        cls.frame = RTM.costruisci_frame(usare_cache=True)
        cls.campione = RTM.campionatura(cls.frame)
        cls.righe, cls.scarto = RTM.applica_selettore(cls.campione)
        cls.riass = RTM.riassunto(cls.righe)
        cls.confronto, cls.parita = RTM.confronta(cls.riass, 0, 0.0005)

    def test_campione_come_nella_pr49(self):
        self.assertEqual(3504, len(self.campione),
                         "il campione pooled OOS della PR #49 ha 3504 righe")

    def test_devig_di_produzione_identico_alle_colonne_della_pr49(self):
        self.assertLess(self.scarto, 1e-12,
                        "il de-vig di produzione deve coincidere con le colonne pre*")

    def test_parita_con_la_pr49(self):
        for riga in self.confronto:
            self.assertTrue(riga["coincide"], riga)
        self.assertTrue(self.parita, self.confronto)

    def test_le_scelte_hanno_esito_e_quota_coerenti(self):
        scelte = self.righe[self.righe["ammessa"]]
        self.assertGreater(len(scelte), 0)
        self.assertTrue(all(e in ("1", "X", "2") for e in scelte["esito"]))
        self.assertTrue(all(q > 1.0 for q in scelte["quota"]))
        self.assertTrue(all(0.55 <= p <= 1.0 for p in scelte["prob_mercato"]))
        # nessuna partita entra due volte
        chiavi = list(zip(scelte["home"], scelte["away"], scelte["date"]))
        self.assertEqual(len(chiavi), len(set(chiavi)))

    def test_ogni_riga_ha_un_esito_reale_confrontabile(self):
        self.assertTrue(all(e in ("1", "X", "2") for e in self.righe["esito_reale"]))
        self.assertFalse(self.righe["esito_reale"].isna().any())


if __name__ == "__main__":
    unittest.main()
