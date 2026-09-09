"""Test del gate shadow: veto |P-E| < 0.25 come penalita' continua (referto §11quater).

Modalita' OMBRA (piano §9 punto 4): il gate non scarta piu' la partita ma
scala la confidence col fattore continuo ``0.25/(0.25+d)``; l'ammissione ombra
e' il solo confronto ``conf_shadow >= min_conf``. NESSUN campo reale del
selettore o del registro cambia: ``seleziona_riga_top_mix`` e le soglie/pesi
restano quelli di 32e3eda (i test di parita' di
``test_topmix_selector_parity.py`` continuano a passare intatti).

Tre livelli:

* ``TestFormulaShadow`` (solo stdlib): la formula esatta su valori noti,
  monotonia, assenza di un secondo taglio secco, limiti;
* ``TestMirrorCasiNoti`` / ``TestCoerenzaColSelettore`` (solo stdlib, come la
  parita'): la funzione ombra ``app.riga_top_mix_shadow`` viene estratta da
  ``app.py`` come testo ed eseguita con gli stessi stub deterministici della
  parita', sugli stessi vettori dei fixture; il suo lato REALE deve coincidere
  con l'output di ``seleziona_riga_top_mix`` quando questa ammette la riga;
* ``TestSalvataggioBitIdentico`` (richiede l'ambiente completo: importa
  ``app.py``; skip se streamlit/numpy non ci sono): ``save_prediction_entry``
  con e senza i campi shadow produce record con i campi reali
  (market/prob/rank/...) bit-identici.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(HERE, "app.py")
sys.path.insert(0, HERE)

import prediction_registry as R  # noqa: E402
from test_topmix_selector_parity import (  # noqa: E402
    _blocco,
    _costante,
    _vettore_forzato,
)

SRC = open(APP_PATH, encoding="utf-8").read()
ELO_W = _costante(SRC, "ELO_ENSEMBLE_W")


def _codice_stub(best, h, a):
    """Stesso stub deterministico della parita': il mapping vero e' coperto da
    test_standardizza_mercato.py, qui conta solo che la chiamata avvenga."""
    return f"STD<{best}|{h}|{a}>"


def _carica_mirror():
    ns = {
        "ELO_ENSEMBLE_W": ELO_W,
        "codice_mercato_selezionato": _codice_stub,
        "gate_shadow_confidence": R.gate_shadow_confidence,
    }
    exec(_blocco(SRC, "riga_top_mix_shadow"), ns)
    return ns["riga_top_mix_shadow"]


def _carica_selettore():
    ns = {
        "ELO_ENSEMBLE_W": ELO_W,
        "codice_mercato_selezionato": _codice_stub,
    }
    exec(_blocco(SRC, "seleziona_riga_top_mix"), ns)
    return ns["seleziona_riga_top_mix"]


MIRROR = _carica_mirror()
SELEZIONA = _carica_selettore()


def _vettore_1x2(p1, pX=0.15, p2=0.15):
    """Vettore Poisson con la vittoria casa come argmax (u25/gg neutrali)."""
    return {"1": p1, "X": pX, "2": p2, "u25": 0.5, "gg": 0.5}


# ---------------------------------------------------------------------------
# 1. Formula pura (prediction_registry, nessuna dipendenza)
# ---------------------------------------------------------------------------
class TestFormulaShadow(unittest.TestCase):
    """conf_shadow = conf * 0.25/(0.25+d), con le proprieta' documentate."""

    def test_valori_noti_esatti(self):
        # d = 0 -> identica; d = 0.25 -> dimezzata; d = 0.5 -> un terzo.
        self.assertAlmostEqual(R.gate_shadow_confidence(0.60, 0.0), 0.60, places=12)
        self.assertAlmostEqual(R.gate_shadow_confidence(0.60, 0.25), 0.30, places=12)
        self.assertAlmostEqual(R.gate_shadow_confidence(0.60, 0.50),
                               0.60 * 0.25 / 0.75, places=12)
        self.assertAlmostEqual(R.gate_shadow_confidence(0.66, 0.10),
                               0.66 * 0.25 / 0.35, places=12)

    def test_percentuali_e_frazioni(self):
        # Convenzione del registro: confidence >1 = percentuale, <=1 = frazione.
        # Il disaccordo d e' sempre una frazione (0.10 = 10 punti percentuali).
        self.assertAlmostEqual(R.gate_shadow_confidence(66.0, 0.10),
                               R.gate_shadow_confidence(0.66, 0.10), places=12)
        self.assertAlmostEqual(R.gate_shadow_confidence(0.66, 0.10),
                               0.66 * 0.25 / 0.35, places=12)

    def test_monotona_decrescente_in_d(self):
        conf = 0.70
        ds = [0.0, 0.05, 0.10, 0.24, 0.25, 0.26, 0.40, 0.90]
        valori = [R.gate_shadow_confidence(conf, d) for d in ds]
        self.assertEqual(valori, sorted(valori, reverse=True))

    def test_mai_zero_ne_un_secondo_taglio(self):
        # Nessun taglio secco: per ogni d finito la confidence resta > 0 e la
        # funzione e' continua anche attraverso il punto di veto 0.25.
        self.assertGreater(R.gate_shadow_confidence(0.55, 0.90), 0.0)
        self.assertAlmostEqual(R.gate_shadow_confidence(0.60, 0.2499),
                               R.gate_shadow_confidence(0.60, 0.2501),
                               delta=0.001)

    def test_sotto_0_25_per_le_bloccate(self):
        # Conseguenza algebrica documentata nel referto: una riga che il veto
        # blocca (d >= 0.25) ha conf_shadow <= conf/2 <= 0.5 < 0.55, quindi
        # l'ammissione ombra e' sempre False li'. E' la proprieta' che rende il
        # segnale ombra significativo sulle righe GIOCATE (robuste vs fragili).
        for conf in (0.55, 0.60, 0.70, 0.80, 0.90, 0.999):
            for d in (0.25, 0.30, 0.40, 0.60):
                cs = R.gate_shadow_confidence(conf, d)
                self.assertLess(cs, R.GATE_SHADOW_MIN_CONF_1X2)
                self.assertLessEqual(cs, conf / 2.0 + 1e-12)

    def test_ingressi_sporchi_non_esplodono(self):
        self.assertIsNone(R.gate_shadow_confidence(None, 0.25))
        self.assertIsNone(R.gate_shadow_confidence("0.70", 0.25))
        self.assertIsNone(R.gate_shadow_confidence(True, 0.25))
        # disaccordo mancante/invalido -> nessun disaccordo (d = 0)
        self.assertAlmostEqual(R.gate_shadow_confidence(0.70, None), 0.70, places=12)
        self.assertAlmostEqual(R.gate_shadow_confidence(0.70, -0.1), 0.70, places=12)

    def test_min_conf_speculare_al_selettore(self):
        self.assertEqual(R.gate_shadow_min_conf("Vittoria Casa", True), 0.55)
        self.assertEqual(R.gate_shadow_min_conf("Pareggio", True), 0.55)
        for totale in R.MERCATI_SENZA_ELO:
            self.assertEqual(R.gate_shadow_min_conf(totale, True), 0.60)
        # 1X2 a Elo assente -> soglia dei totali, come nel selettore reale
        self.assertEqual(R.gate_shadow_min_conf("Vittoria Casa", False), 0.60)

    def test_campi_da_riga_valori_noti(self):
        # d = |0.70 - 0.60| = 0.10 -> 0.66*0.25/0.35 < 0.55: fragili.
        campi = R.gate_shadow_fields_from_row("Vittoria Casa", 0.66, 70.0, 60.0, True)
        self.assertIsNotNone(campi)
        self.assertAlmostEqual(campi[R.GATE_SHADOW_CONFIDENCE_FIELD],
                               0.66 * 0.25 / 0.35, places=12)
        self.assertFalse(campi[R.GATE_SHADOW_AMMESSA_FIELD])

    def test_campi_da_riga_consenso_ammessa(self):
        # d = 0.01 con conf alta -> sopra 0.55: robuste.
        campi = R.gate_shadow_fields_from_row("Vittoria Casa", 0.80, 80.0, 79.0, True)
        self.assertAlmostEqual(campi[R.GATE_SHADOW_CONFIDENCE_FIELD],
                               0.80 * 0.25 / 0.26, places=12)
        self.assertTrue(campi[R.GATE_SHADOW_AMMESSA_FIELD])

    def test_campi_da_riga_totali_e_elo_assente(self):
        # Totali: d = 0 per costruzione -> ammessa identica alla reale.
        t = R.gate_shadow_fields_from_row("Over 2.5", 0.62, 62.0, 62.0, True)
        self.assertAlmostEqual(t[R.GATE_SHADOW_CONFIDENCE_FIELD], 0.62, places=12)
        self.assertTrue(t[R.GATE_SHADOW_AMMESSA_FIELD])
        # 1X2 a Elo assente: conf = Poisson puro, soglia 0.60.
        e1 = R.gate_shadow_fields_from_row("Vittoria Casa", 0.61, 61.0, None, False)
        self.assertAlmostEqual(e1[R.GATE_SHADOW_CONFIDENCE_FIELD], 0.61, places=12)
        self.assertTrue(e1[R.GATE_SHADOW_AMMESSA_FIELD])

    def test_campi_mancanti_o_anomali_restituiscono_none(self):
        self.assertIsNone(R.gate_shadow_fields_from_row(None, 0.66, 70.0, 60.0, True))
        self.assertIsNone(R.gate_shadow_fields_from_row("Vittoria Casa", None, 70.0, 60.0, True))
        self.assertIsNone(R.gate_shadow_fields_from_row("Vittoria Casa", 0.66, None, 60.0, True))
        # flag dice Elo letto ma valore assente: riga anomala -> nessun campo
        self.assertIsNone(R.gate_shadow_fields_from_row("Vittoria Casa", 0.66, 70.0, None, True))


# ---------------------------------------------------------------------------
# 2. Mirror (riga_top_mix_shadow) sugli stessi casi noti della parita'
# ---------------------------------------------------------------------------
class TestMirrorCasiNoti(unittest.TestCase):
    """I casi limite di test_topmix_selector_parity, letti in chiave ombra."""

    def test_veto_esatto_0_25_la_penalita_dimezza(self):
        # Stessa costruzione di test_veto_a_discrepanza_esatta (delta = 0.25,
        # elo = m["1"] - 0.25): il selettore REALE scarta (0.25 non e' < 0.25);
        # l'ombra dimezza invece di azzerare.
        m = _vettore_1x2(0.70)
        elo = {"1": m["1"] - 0.25, "X": 0.15, "2": 0.15}
        self.assertIsNone(SELEZIONA(m, elo, True, "Casa", "Trasferta"))
        r = MIRROR(m, elo, True, "Casa", "Trasferta")
        self.assertIsNotNone(r)
        self.assertEqual(r["market"], "Vittoria Casa")
        self.assertAlmostEqual(r["prob"], 0.60, places=12)       # 0.6*0.70+0.4*0.45
        self.assertAlmostEqual(r["disaccordo"], 0.25, places=12)
        self.assertAlmostEqual(r["conf_shadow"], 0.30, places=9)  # dimezzata
        self.assertFalse(r["ammessa_shadow"])
        self.assertTrue(r["gate_avrebbe_scartato"])
        self.assertEqual(r["min_conf"], 0.55)

    def test_appena_sotto_il_veto_il_selettore_ammette_l_ombra_no(self):
        # delta = 0.2499999: oggi la riga si GIOCA; sotto il solo filtro ombra
        # (conf_shadow >= 0.55) no -> e' il segnale "fragile" del referto.
        m = _vettore_1x2(0.70)
        elo = {"1": 0.4500001, "X": 0.15, "2": 0.15}
        riga_reale = SELEZIONA(m, elo, True, "Casa", "Trasferta")
        self.assertIsNotNone(riga_reale, "il caso deve essere ammesso dal selettore reale")
        r = MIRROR(m, elo, True, "Casa", "Trasferta")
        self.assertAlmostEqual(r["prob"], riga_reale["prob"], places=12)
        self.assertLess(r["disaccordo"], 0.25)
        self.assertAlmostEqual(r["conf_shadow"], r["prob"] / 2.0, delta=0.0002)
        self.assertFalse(r["ammessa_shadow"])
        self.assertFalse(r["gate_avrebbe_scartato"])

    def test_consenso_pieno_ammessa_sia_reale_sia_ombra(self):
        m = _vettore_1x2(0.80)
        elo = {"1": 0.80, "X": 0.10, "2": 0.10}
        self.assertIsNotNone(SELEZIONA(m, elo, True, "Casa", "Trasferta"))
        r = MIRROR(m, elo, True, "Casa", "Trasferta")
        self.assertAlmostEqual(r["disaccordo"], 0.0, places=12)
        self.assertAlmostEqual(r["conf_shadow"], 0.80, places=12)
        self.assertTrue(r["ammessa_shadow"])

    def test_disaccordo_moderato_ad_alta_conf_resta_ammessa(self):
        # d = 0.02, conf = 0.942: il consenso quasi pieno passa anche l'ombra.
        m = _vettore_1x2(0.95)
        elo = {"1": 0.93, "X": 0.04, "2": 0.03}
        r = MIRROR(m, elo, True, "Casa", "Trasferta")
        self.assertAlmostEqual(r["conf_shadow"], 0.942 * 0.25 / 0.27, places=6)
        self.assertTrue(r["ammessa_shadow"])

    def test_totali_non_toccati_dalla_penalita(self):
        # Over 2.5 argmax; l'Elo non viene letto -> d = 0, ammessa invariata.
        m = {"1": 0.20, "X": 0.15, "2": 0.10, "u25": 0.38, "gg": 0.50}
        for elo in ({"1": 0.90, "X": 0.05, "2": 0.05}, {}, None):
            r = MIRROR(m, elo, True, "Casa", "Trasferta")
            self.assertEqual(r["market"], "Over 2.5")
            self.assertAlmostEqual(r["prob"], 0.62, places=12)
            self.assertAlmostEqual(r["disaccordo"], 0.0, places=12)
            self.assertAlmostEqual(r["conf_shadow"], 0.62, places=12)
            self.assertTrue(r["ammessa_shadow"])
            self.assertFalse(r["gate_avrebbe_scartato"])

    def test_facce_dell_elo_assente(self):
        # Stesse facce di ELO_MANCANTI della parita': l'ombra coincide con la
        # confidence reale (d = 0) e usa la soglia 0.60. L'eccezione di rete
        # non raggiunge MAI il selettore (la intercetta il chiamante e passa
        # elo_probs=None, elo_disponibile=False): e' quella la faccia qui.
        facce = [(None, True), ({}, True), ({"X": 0.5}, True), (None, False)]
        for assente, flag in facce:
            m = _vettore_1x2(0.61)
            r = MIRROR(m, assente, flag, "Casa", "Trasferta")
            self.assertAlmostEqual(r["prob"], 0.61, places=12)
            self.assertAlmostEqual(r["disaccordo"], 0.0, places=12)
            self.assertEqual(r["min_conf"], 0.60)
            self.assertTrue(r["ammessa_shadow"])
            m_low = _vettore_1x2(0.56)
            r_low = MIRROR(m_low, assente, flag, "Casa", "Trasferta")
            self.assertIsNone(SELEZIONA(m_low, assente, flag, "Casa", "Trasferta"))
            self.assertEqual(r_low["min_conf"], 0.60)
            self.assertFalse(r_low["ammessa_shadow"])

    def test_sotto_soglia_reale_l_ombra_non_inventa_ammissioni(self):
        # Poisson 0.60, Elo 0.40 -> conf 0.52 < 0.55: bocciata da entrambi.
        m = _vettore_1x2(0.60, pX=0.15, p2=0.25)
        elo = {"1": 0.40, "X": 0.15, "2": 0.45}
        r = MIRROR(m, elo, True, "Casa", "Trasferta")
        self.assertIsNotNone(r)          # il mirror NON scarta mai
        self.assertAlmostEqual(r["prob"], 0.52, places=12)
        self.assertLess(r["conf_shadow"], r["prob"])
        self.assertFalse(r["ammessa_shadow"])

    def test_la_mirror_non_scarta_mai_e_calcola_sempre_il_disaccordo(self):
        # Proprieta' chiave della modalita' ombra: nessuna riga sparisce.
        for modo, valore in (("1", 0.70), ("X", 0.60), ("2", 0.65),
                             ("Over", 0.62), ("Under", 0.61), ("GG", 0.63), ("NG", 0.60)):
            m = _vettore_forzato(modo, valore)
            r = MIRROR(m, dict(m) if modo in ("1", "X", "2") else None, True,
                       "Casa", "Trasferta")
            self.assertIsNotNone(r)
            self.assertIn("conf_shadow", r)
            self.assertIn("ammessa_shadow", r)
            self.assertIn("disaccordo", r)


# ---------------------------------------------------------------------------
# 3. Coerenza col selettore reale (griglia, come la parita')
# ---------------------------------------------------------------------------
class TestCoerenzaColSelettore(unittest.TestCase):
    """Il lato REALE della mirror deve coincidere con seleziona_riga_top_mix.

    E' il vincolo che impedisce alla copia speculare di divergere: stesso
    argmax, stesso blend, stessa soglia. Su ogni caso in cui il selettore
    ammette la riga, market/prob/poisson/elo/flag/min_conf coincidono e la
    confidence ombra calcolata dalla riga (valori arrotondati allo 0.1 pp)
    coincide con quella esatta a meno della tolleranza di arrotondamento.
    """

    def _casi(self):
        import random
        rng = random.Random(20260909)
        casi = []
        for i in range(600):
            modo = ("1", "X", "2", "Over", "Under", "GG", "NG")[i % 7]
            valore = (0.55, 0.5499, 0.60, 0.5999)[i % 4] if i % 4 == 0 else rng.uniform(0.51, 0.95)
            m = _vettore_forzato(modo, valore)
            s = rng.random()
            if modo in ("1", "X", "2"):
                if s < 0.4:
                    delta = rng.uniform(0.0, 0.24) * rng.choice([-1.0, 1.0])
                    elo = ({"1": min(0.99, max(0.01, m["1"] + delta)),
                            "X": min(0.99, max(0.01, m["X"] + delta)),
                            "2": min(0.99, max(0.01, m["2"] + delta))}, True)
                elif s < 0.6:
                    elo = ({"1": max(0.01, m["1"] - rng.uniform(0.25, 0.6)),
                            "X": min(0.99, m["X"] + 0.4),
                            "2": min(0.99, m["2"] + rng.uniform(0.25, 0.5))}, True)
                elif s < 0.8:
                    # Elo assente nelle sue facce: dict vuoto, dict senza la
                    # chiave del mercato scelto, predittore che SOLLEVA (che il
                    # chiamante converte in (None, False), come in produzione).
                    if s < 0.68:
                        elo = ({}, True)
                    elif s < 0.74:
                        elo = ({"1": m["1"], "X": m["X"]}, True)
                    else:
                        elo = (None, False)
                else:
                    elo = ({"1": m["1"], "X": m["X"]}, True)  # senza la chiave scelta
            else:
                elo = (None, True)          # totali: l'Elo non viene letto
            casi.append((m, elo))
        return casi

    def test_lato_reale_coincide_con_il_selettore(self):
        for m, (elo, flag) in self._casi():
            riga = SELEZIONA(m, elo, flag, "Casa", "Trasferta")
            r = MIRROR(m, elo, flag, "Casa", "Trasferta")
            self.assertIsNotNone(r)
            if riga is None:
                continue
            self.assertEqual(r["market"], riga["market"], (m, elo))
            self.assertEqual(r["mercato_standard"], riga["mercato_standard"])
            self.assertAlmostEqual(r["prob"], riga["prob"], places=12, msg=(m, elo))
            self.assertEqual(r["poisson"], riga["poisson"], (m, elo))
            self.assertEqual(r["elo"], riga["elo"], (m, elo))
            self.assertEqual(r["elo_disponibile"], riga["elo_disponibile"], (m, elo))
            self.assertEqual(r["min_conf"], 0.60 if r["market"] in R.MERCATI_SENZA_ELO
                             or not r["elo_disponibile"] else 0.55, (m, elo))
            # Ammessa dal selettore reale => il gate non l'avrebbe scartata.
            self.assertFalse(r["gate_avrebbe_scartato"], (m, elo))

    def test_conf_shadow_dalla_riga_coincide_con_quella_esatta(self):
        for m, (elo, flag) in self._casi():
            riga = SELEZIONA(m, elo, flag, "Casa", "Trasferta")
            if riga is None:
                continue
            r = MIRROR(m, elo, flag, "Casa", "Trasferta")
            campi = R.gate_shadow_fields_from_row(riga["market"], riga["prob"],
                                                  riga["poisson"], riga["elo"],
                                                  riga["elo_disponibile"])
            self.assertIsNotNone(campi)
            # Le componenti del registro sono arrotondate allo 0.1 pp: la
            # confidence ombra coincide con quella esatta entro ~0.005.
            self.assertAlmostEqual(campi[R.GATE_SHADOW_CONFIDENCE_FIELD],
                                   r["conf_shadow"], delta=0.005, msg=(m, elo))


# ---------------------------------------------------------------------------
# 4. Salvataggio bit-identico (serve l'ambiente completo: importa app.py)
# ---------------------------------------------------------------------------
try:  # noqa: E402
    from app import save_prediction_entry  # noqa: F401
    from prediction_registry import ORIGIN_TOP_MIX  # noqa: F401
    APP_IMPORTABILE = True
except Exception:   # streamlit/numpy assenti (sandbox ridotto)
    APP_IMPORTABILE = False

_CHIAVI_REALI = [
    "match_id", "home", "away", "campionato", "giornata", "data",
    "pronostico_sicuro", "mercato_standard", "top3", "prob_sicuro",
    "risultati_attesi", "risultato_reale", "esito", "tipo", "stagione",
    "salvato_il", "origin", "selector_version", "rank", "kickoff_utc",
    "data_snapshot_sha", "calculation_id", "poisson", "elo", "elo_disponibile",
    "model_version", "excluded_from_current_model_stats",
]


@unittest.skipUnless(APP_IMPORTABILE, "ambiente completo richiesto (streamlit/numpy)")
class TestSalvataggioBitIdentico(unittest.TestCase):
    """Il campo shadow e' puramente aggiuntivo: con e senza, il salvataggio
    reale (market/prob/rank/...) deve essere bit-identico."""

    def _chiama(self, con_shadow):
        return save_prediction_entry(
            777001, "Casa", "Trasferta", "Serie A", 12, "12/09/2026 18:00",
            "Vittoria Casa - Top Mix", [], 66.0, "", mercato_standard="1",
            origin=R.ORIGIN_TOP_MIX, rank=3, kickoff_utc="2026-09-12T18:00:00Z",
            prob_poisson=70.0, prob_elo=60.0, elo_disponibile=True,
            snapshot_sha="cafebabe",
            **({"gate_shadow_confidence": 0.4714285714, "gate_shadow_ammessa": False}
               if con_shadow else {}))

    def test_con_e_senza_campi_reali_bit_identici(self):
        from unittest.mock import patch
        with patch("app.save_predictions"), patch("app.load_predictions", return_value=[]):
            esito_con = self._chiama(True)
            entry_con = esito_con["record"]
            esito_senza = self._chiama(False)
            entry_senza = esito_senza["record"]
        self.assertEqual(esito_con["azione"], esito_senza["azione"])
        for chiave in _CHIAVI_REALI:
            self.assertEqual(entry_con[chiave], entry_senza[chiave], chiave)
        # Bit-identici sul sottoinsieme reale, ordine delle chiavi compreso.
        json_con = json.dumps({k: entry_con[k] for k in _CHIAVI_REALI})
        json_senza = json.dumps({k: entry_senza[k] for k in _CHIAVI_REALI})
        self.assertEqual(json_con, json_senza)
        # Il record con shadow ha ESATTAMENTE le due chiavi in piu'.
        self.assertEqual(sorted(set(entry_con) - set(entry_senza)),
                         sorted([R.GATE_SHADOW_CONFIDENCE_FIELD,
                                 R.GATE_SHADOW_AMMESSA_FIELD]))
        self.assertFalse(entry_con[R.GATE_SHADOW_AMMESSA_FIELD])
        self.assertAlmostEqual(entry_con[R.GATE_SHADOW_CONFIDENCE_FIELD],
                               0.66 * 0.25 / 0.35, places=9)

    def test_calcolo_fallito_record_identico_a_prima(self):
        from unittest.mock import patch
        with patch("app.save_predictions"), patch("app.load_predictions", return_value=[]):
            esito_ko = save_prediction_entry(
                777002, "Casa", "Trasferta", "Serie A", 12, "12/09/2026 18:00",
                "Over 2.5 - Top Mix", [], 62.0, "", mercato_standard="OVER_2.5",
                origin=R.ORIGIN_TOP_MIX, rank=7,
                gate_shadow_confidence=None, gate_shadow_ammessa=None)
            esito_base = save_prediction_entry(
                777002, "Casa", "Trasferta", "Serie A", 12, "12/09/2026 18:00",
                "Over 2.5 - Top Mix", [], 62.0, "", mercato_standard="OVER_2.5",
                origin=R.ORIGIN_TOP_MIX, rank=7)
        self.assertEqual(esito_ko["record"], esito_base["record"])
        for campo in (R.GATE_SHADOW_CONFIDENCE_FIELD, R.GATE_SHADOW_AMMESSA_FIELD):
            self.assertNotIn(campo, esito_ko["record"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
