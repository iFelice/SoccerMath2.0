"""Test offline della sonda allenatori (``audit/sonda_allenatori.py``).

Nessuna rete e nessuna chiave: le risposte delle API sono finte (fixture) e il
tempo e' finto (finestra mobile con orologio e ``sleep`` iniettati). Cosa
verificano, in parole povere:

* il limite di chiamate e' rispettato: con un tetto di 10 al minuto, l'undicesima
  chiamata ASPETTA invece di partire;
* le risposte si leggono senza inventare niente: allenatore assente, contratto
  assente, date nel formato ``AAAA-MM`` delle API (nessun giorno aggiunto);
* il confronto con i casi pubblici distingue i quattro esiti dichiarati
  ("aggiornato", "non aggiornato", "squadra non nel run", "api senza
  allenatore") e capisce che "Blessin" e "Alexander Blessin" sono la stessa
  persona;
* copertura e formato delle date sono conteggi, non stime;
* il giro completo in modalita' ``--fixture`` scrive l'istantanea (una voce per
  squadra con l'istante della lettura) e il referto, che mette la REGOLA prima
  dei numeri e dichiara l'esito;
* **nessun dato finto passa per uno snapshot reale**: i file di un run
  ``--fixture`` portano il prefisso ``fixture_`` e, senza cartelle esplicite,
  stanno in ``audit/output/`` (cartella non versionata): un run ``--fixture``
  non crea NESSUN file in ``audit/data/allenatori/``;
* un run di RETE in cui tutte le chiamate falliscono esce con errore (2) e non
  scrive ne' lo snapshot con la data ne' il referto;
* la chiave non finisce MAI nei file: lo script rifiuta di scrivere un file che
  la contenga, e il nome della variabile non compare nel referto.

Il file dei casi pubblici del repository fa parte del test: almeno 3 casi, con
fonte e data, su almeno 3 leghe (sennò la verifica delle API non direbbe nulla).
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
for _p in (str(HERE), str(REPO_ROOT), str(REPO_ROOT / "SoccerMath")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sonda_allenatori as sa  # noqa: E402

FIXTURE = HERE / "fixtures" / "allenatori_fixture.json"
CASI = HERE / "data" / "allenatori" / "casi_pubblici_2026_27.json"


def _cinque_leghe(allenatore="Uno", senza_per_lega=0):
    """Tutte e 5 le leghe lette: 4 squadre ciascuna, con allenatore salvo N."""
    quadro = {}
    for lega in sa.LEGHE:
        voci = [{"nome": f"{lega} {i}", "allenatore": allenatore} for i in range(4)]
        for voce in voci[:senza_per_lega]:
            voce["allenatore"] = None
        quadro[lega] = voci
    return quadro


class _Risposta:
    """Risposta finta: stato, header e payload."""

    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"raise_for_status con {self.status_code}")

    def json(self):
        return self._payload


class _SessioneScript:
    """Risponde con una lista di risposte in ordine; registra gli istanti."""

    def __init__(self, risposte, orologio):
        self.risposte = list(risposte)
        self.orologio = orologio
        self.istanti = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.istanti.append(self.orologio[0])
        if not self.risposte:
            return _Risposta(200, {"teams": [], "coach": None})
        return self.risposte.pop(0)


def _finestra_con_orologio():
    orologio = [0.0]
    attese = []

    def dormi(secondi):
        attese.append(secondi)
        orologio[0] += secondi

    finestra = sa.FinestraChiamate(10, orologio=lambda: orologio[0], dormi=dormi)
    return finestra, orologio, attese


class TestFinestraChiamate(unittest.TestCase):
    """Il tetto di chiamate al minuto: si aspetta, non si sfora."""

    def test_decima_chiamata_passa_undicesima_aspetta(self):
        orologio = [0.0]
        attese = []

        def dormi(secondi):
            attese.append(secondi)
            orologio[0] += secondi

        finestra = sa.FinestraChiamate(10, orologio=lambda: orologio[0], dormi=dormi)
        for _ in range(10):
            finestra.attendi()
        self.assertEqual([], attese, "le prime 10 chiamate non aspettano")
        finestra.attendi()  # l'undicesima trova la finestra piena
        self.assertEqual(1, len(attese))
        self.assertGreaterEqual(attese[0], 60.0)
        self.assertEqual(11, finestra.chiamate, "le chiamate fatte sono undici")
        self.assertEqual(1, finestra.attese)
        self.assertEqual(1, len(finestra._istanti),
                         "nella finestra resta solo l'ultima chiamata")

    def test_finestra_scorrevole_libera_il_posto(self):
        orologio = [0.0]
        passi = []

        def dormi(secondi):
            passi.append(secondi)
            orologio[0] += secondi

        finestra = sa.FinestraChiamate(2, orologio=lambda: orologio[0], dormi=dormi)
        finestra.attendi()
        finestra.attendi()
        orologio[0] += 61.0  # passato un minuto: il posto e' libero
        finestra.attendi()
        self.assertEqual([], passi)
        self.assertEqual(3, finestra.chiamate)
        self.assertEqual(0, finestra.attese)

    def test_tetto_minimo_almeno_uno(self):
        finestra = sa.FinestraChiamate(0)
        self.assertEqual(1, finestra.max_chiamate,
                         "con 0 la finestra non si libererebbe mai")


class TestLimiteEDurata(unittest.TestCase):
    """Orologio finto: il tetto di 10 richieste in 60 s e la durata prevista."""

    @staticmethod
    def _istanti_ammessi(n):
        orologio = [0.0]
        istanti = []

        def dormi(secondi):
            orologio[0] += secondi

        finestra = sa.FinestraChiamate(10, orologio=lambda: orologio[0], dormi=dormi)
        for _ in range(n):
            finestra.attendi()
            istanti.append(orologio[0])
        return istanti, orologio[0]

    def test_cento_chiamate_richiedono_almeno_nove_minuti(self):
        istanti, fine = self._istanti_ammessi(100)
        self.assertGreaterEqual(fine, 540.0, "100 chiamate a 10/min: almeno 9 minuti")
        self.assertGreaterEqual(istanti[-1], 540.0)

    def test_mai_piu_di_dieci_in_una_finestra_di_60_secondi(self):
        istanti, _ = self._istanti_ammessi(100)
        for t in istanti:
            dentro = [u for u in istanti if t - 60.0 <= u <= t]
            self.assertLessEqual(len(dentro), 10,
                                 f"in [{t-60}, {t}] ci sono {len(dentro)} richieste")

    def test_durata_minima_formula(self):
        self.assertEqual(540.0, sa.durata_minima_secondi(100, 10))
        self.assertEqual(372.0, sa.durata_minima_secondi(72, 10))   # 62 * 6 s
        self.assertEqual(0.0, sa.durata_minima_secondi(10, 10))
        self.assertEqual(0.0, sa.durata_minima_secondi(0, 10))
        self.assertEqual("9 min 0 s", sa.formato_durata(540))

    def test_lista_squadre_conta_nella_finestra(self):
        """L'elenco (1 chiamata) piu' 12 squadre = 13 richieste: l'undicesima aspetta."""
        orologio = [0.0]
        attese = []

        def dormi(secondi):
            attese.append(secondi)
            orologio[0] += secondi

        finestra = sa.FinestraChiamate(10, orologio=lambda: orologio[0], dormi=dormi)
        elenco = {"teams": [{"id": i, "name": f"S{i}"} for i in range(12)]}
        sessione = _SessioneScript(
            [_Risposta(200, elenco)] +
            [_Risposta(200, {"coach": {"name": "Uno"}}) for _ in range(12)],
            orologio)
        voci = sa.scarica_lega("SA", None, "chiave-finta", finestra, session=sessione)
        self.assertEqual(12, len(voci))
        self.assertEqual(13, finestra.chiamate)
        self.assertGreaterEqual(len(attese), 1, "la tredicesima richiesta deve aspettare")

    def test_un_429_produce_attesa_dall_header_e_nuovo_tentativo(self):
        finestra, orologio, attese = _finestra_con_orologio()
        sessione = _SessioneScript([
            _Risposta(429, headers={"X-RequestCounter-Reset": "7"}),
            _Risposta(200, {"coach": {"name": "Tizio"}}),
        ], orologio)
        payload = sa.chiama("https://x/teams/1", "chiave", finestra, session=sessione)
        self.assertEqual({"coach": {"name": "Tizio"}}, payload)
        self.assertEqual(2, finestra.chiamate, "il 429 conta come richiesta")
        self.assertEqual(1, finestra.riprovate)
        self.assertEqual(1, finestra.attese_429)
        self.assertIn(7.0, attese, "attesa del tempo indicato dall'header")

    def test_429_senza_header_attende_sessanta_secondi(self):
        finestra, orologio, attese = _finestra_con_orologio()
        sessione = _SessioneScript([_Risposta(429), _Risposta(200, {"ok": 1})], orologio)
        sa.chiama("https://x/teams/1", "chiave", finestra, session=sessione)
        self.assertIn(60.0, attese)

    def test_al_piu_tre_nuovi_tentativi_per_chiamata(self):
        finestra, orologio, _ = _finestra_con_orologio()
        sessione = _SessioneScript([_Risposta(429) for _ in range(10)], orologio)
        with self.assertRaises(RuntimeError) as contesto:
            sa.chiama("https://x/teams/1", "chiave", finestra, session=sessione)
        self.assertIn("dopo 3 nuovi tentativi", str(contesto.exception))
        self.assertEqual(4, finestra.chiamate, "1 richiesta + 3 nuovi tentativi")
        self.assertEqual(3, finestra.riprovate)

    def test_il_429_ripetuto_resta_nel_limite_di_finestra(self):
        """Anche i tentativi ripetuti dopo un 429 non superano 10 in 60 s."""
        orologio = [0.0]
        istanti = []

        class Sessione:
            def get(self, url, headers=None, params=None, timeout=None):
                istanti.append(orologio[0])
                if len(istanti) % 3 == 0:
                    return _Risposta(429, headers={"X-RequestCounter-Reset": "1"})
                return _Risposta(200, {"coach": None})

        def dormi(secondi):
            orologio[0] += secondi

        finestra = sa.FinestraChiamate(10, orologio=lambda: orologio[0], dormi=dormi)
        for _ in range(12):
            sa.chiama("https://x/teams/1", "chiave", finestra, session=Sessione())
        for t in istanti:
            self.assertLessEqual(len([u for u in istanti if t - 60.0 <= u <= t]), 10)

    def test_header_di_quota_esaurita_aspetta_il_reset(self):
        finestra, orologio, attese = _finestra_con_orologio()
        sessione = _SessioneScript([
            _Risposta(200, {"coach": None},
                      headers={"X-Requests-Available-Minute": "0",
                               "X-RequestCounter-Reset": "30"}),
            _Risposta(200, {"coach": None}),
        ], orologio)
        sa.chiama("https://x/teams/1", "chiave", finestra, session=sessione)
        self.assertEqual(1, finestra.attese_header)
        self.assertIn(30.0, attese)

    def test_chiave_non_valida_non_si_ripete(self):
        finestra, orologio, attese = _finestra_con_orologio()
        sessione = _SessioneScript([_Risposta(403), _Risposta(200, {})], orologio)
        with self.assertRaises(RuntimeError):
            sa.chiama("https://x/teams/1", "chiave", finestra, session=sessione)
        self.assertEqual(1, finestra.chiamate, "con 403 nessun tentativo in piu'")


class TestEsitoNonValutabile(unittest.TestCase):
    """La regola si valuta solo con le 5 leghe lette per intero."""

    def test_come_il_13_ottobre_leghe_mancanti_nessuna_percentuale(self):
        quadro = {"La Liga": _cinque_leghe()["La Liga"],
                  "Ligue 1": _cinque_leghe()["Ligue 1"]}
        esito = sa.giudizio(sa.copertura(quadro),
                            [{"esito": "aggiornato"}] * 3)
        self.assertFalse(esito["valutabile"])
        self.assertFalse(esito["affidabile"])
        self.assertEqual(
            ["non valutabile: leghe mancanti Serie A, Premier League, Bundesliga"],
            esito["motivi"])
        for motivo in esito["motivi"]:
            self.assertNotIn("%", motivo, "nessuna percentuale confrontata con la soglia")

    def test_le_cinque_leghe_devono_esserci_tutte(self):
        quadro = _cinque_leghe()
        del quadro["Bundesliga"]
        esito = sa.giudizio(sa.copertura(quadro), [{"esito": "aggiornato"}] * 3)
        self.assertFalse(esito["valutabile"])
        self.assertIn("Bundesliga", esito["motivi"][0])

    def test_squadra_non_nel_run_non_conta(self):
        """3 aggiornati + 2 «squadra non nel run»: ok. Le due non pesano."""
        casi = [{"esito": "aggiornato"}] * 3 + [{"esito": "squadra non nel run"}] * 2
        esito = sa.giudizio(sa.copertura(_cinque_leghe()), casi)
        self.assertTrue(esito["valutabile"])
        self.assertTrue(esito["casi_ok"])
        self.assertTrue(esito["affidabile"])

    def test_squadra_non_nel_run_non_fa_contare_un_non_aggiornato(self):
        casi = [{"esito": "aggiornato"}] * 2 + [{"esito": "squadra non nel run"}] * 4
        esito = sa.giudizio(sa.copertura(_cinque_leghe()), casi)
        self.assertFalse(esito["affidabile"], "due casi valutabili sono meno di tre")
        self.assertIn("casi valutabili 2 (servono almeno 3)", esito["motivi"])
        self.assertNotIn("non aggiornati", " ".join(esito["motivi"]))

    def test_un_caso_non_aggiornato_blocca_la_scheda(self):
        casi = [{"esito": "aggiornato"}] * 3 + [{"esito": "non aggiornato"}]
        esito = sa.giudizio(sa.copertura(_cinque_leghe()), casi)
        self.assertFalse(esito["affidabile"])
        self.assertIn("1 casi su 4 non aggiornati", esito["motivi"])

    def test_solo_squadre_assenti_non_e_un_esito(self):
        casi = [{"esito": "squadra non nel run"}] * 6
        esito = sa.giudizio(sa.copertura(_cinque_leghe()), casi)
        self.assertFalse(esito["affidabile"])
        self.assertIn("nessun caso verificabile", esito["motivi"])


class TestEtaDeiCasi(unittest.TestCase):
    """Ogni caso riporta i giorni fra la data del cambio e il run."""

    def test_eta_in_giorni(self):
        casi = [{"lega": "La Liga", "squadra": "Osasuna",
                 "allenatore_uscente": "Luis Miguel Ramis",
                 "allenatore_atteso": "Jagoba Arrasate", "data_cambio": "2026-10-12"},
                {"lega": "Ligue 1", "squadra": "Lens",
                 "allenatore_uscente": "Dino Toppmöller",
                 "allenatore_atteso": "Yannick Cahuzac", "data_cambio": "2026-09-15"}]
        voci = {"La Liga": [{"nome": "CA Osasuna", "allenatore": "Luis Miguel Ramis"}],
                "Ligue 1": [{"nome": "RC Lens", "allenatore": "Yannick Cahuzac"}]}
        esiti = sa.confronta_casi(casi, voci, "2026-10-13T15:49:50Z")
        self.assertEqual(1, esiti[0]["eta_giorni"], "1 giorno: Osasuna")
        self.assertEqual(28, esiti[1]["eta_giorni"], "28 giorni: Lens")

    def test_eta_non_inventata(self):
        self.assertIsNone(sa.giorni_tra(None, "2026-10-13T15:49:50Z"))
        self.assertIsNone(sa.giorni_tra("non-una-data", "2026-10-13T15:49:50Z"))


class TestLetturaRisposte(unittest.TestCase):
    """Le risposte delle API: nessun numero e nessun nome inventato."""

    def test_elenco_squadre(self):
        squadre = sa.allenatore_da_teams({"teams": [
            {"id": 1, "name": "A", "shortName": "a", "tla": "AA"},
            "spazzatura",
            {"id": 2, "name": "B"},
            {"name": "senza id"},
        ]}, "2026-10-13T09:00:00Z")
        self.assertEqual(2, len(squadre))
        self.assertEqual(1, squadre[0]["id"])
        self.assertEqual("B", squadre[1]["nome"])
        self.assertEqual("2026-10-13T09:00:00Z", squadre[0]["rilevato_il"])
        self.assertEqual([], sa.allenatore_da_teams(None, "2026-10-13T09:00:00Z"))

    def test_allenatore_e_contratto(self):
        voce = sa.allenatore_da_squadra(
            {"coach": {"id": 7, "name": "Mario Rossi",
                       "contract": {"start": "2026-07-01", "until": "2028-06"}}},
            "2026-10-13T09:00:00Z")
        self.assertEqual(7, voce["allenatore_id"])
        self.assertEqual("Mario Rossi", voce["allenatore"])
        self.assertEqual("2026-07-01", voce["contratto_dal"])
        self.assertEqual("2028-06", voce["contratto_fino"])
        self.assertEqual(["inizio: giorno", "fine: mese"], voce["forme_date"])

    def test_allenatore_assente_o_contratto_assente(self):
        for payload in ({}, {"coach": None}, {"coach": {}}, None, {"coach": "x"}):
            with self.subTest(payload=payload):
                voce = sa.allenatore_da_squadra(payload, "2026-10-13T09:00:00Z")
                self.assertIsNone(voce["allenatore"])
                self.assertIsNone(voce["contratto_dal"])
                self.assertIsNone(voce["contratto_fino"])
                self.assertEqual([], voce["forme_date"])

    def test_formato_date_senza_inventare_giorni(self):
        self.assertEqual(("2026-07", "mese"), sa.data_leggibile("2026-07"))
        self.assertEqual(("2026-07-01", "giorno"), sa.data_leggibile(" 2026-07-01 "))
        self.assertEqual(("2026", "anno"), sa.data_leggibile("2026"))
        self.assertEqual((None, None), sa.data_leggibile(None))
        self.assertEqual((None, None), sa.data_leggibile("   "))
        self.assertEqual(("prossima estate", "altro"), sa.data_leggibile("prossima estate"))


class TestNomiEPersone(unittest.TestCase):
    """Confronto dei nomi: accenti e ordine non contano, le invenzioni no."""

    def test_normalizzazione(self):
        self.assertEqual("dino toppmoller", sa.normalizza_nome("Dino Toppmöller"))
        self.assertEqual("yannick cahuzac", sa.normalizza_nome("Yannick  CAHUZAC"))
        self.assertEqual("", sa.normalizza_nome(None))
        self.assertEqual("alberto gilardino", sa.normalizza_nome("Alberto Gilardino."))
        self.assertEqual("jean luc picard", sa.normalizza_nome("Jean-Luc  Picard"))

    def test_stessa_persona(self):
        self.assertTrue(sa.stessa_persona("Alexander Blessin", "Blessin"))
        self.assertTrue(sa.stessa_persona("Jagoba Arrasate", "jagoba arrasate"))
        self.assertTrue(sa.stessa_persona("Yannick Cahuzac", "Yannick  CAHUZAC"))
        self.assertTrue(sa.stessa_persona("Dino Toppmöller", "Toppmoller"))
        self.assertFalse(sa.stessa_persona("Fabio Grosso", "Paolo Vanoli"))
        self.assertFalse(sa.stessa_persona("", "Vanoli"))
        self.assertFalse(sa.stessa_persona("Vanoli", "Paolo Vanoli Rossi"),
                         "il cognome conta: 'Rossi' non e' 'Vanoli'")

    def test_stessa_squadra(self):
        self.assertTrue(sa.stessa_squadra("Bologna FC 1909", "Bologna"))
        self.assertTrue(sa.stessa_squadra("ACF Fiorentina", "Fiorentina"))
        self.assertTrue(sa.stessa_squadra("RC Lens", "Lens"))
        self.assertFalse(sa.stessa_squadra("AC Milan", "Inter"))


class TestConfrontoCasi(unittest.TestCase):
    """Il confronto con i casi pubblici: quattro esiti, nessuno per esclusione."""

    @staticmethod
    def _voci():
        return {
            "Serie A": [
                {"id": 1, "nome": "Parma", "allenatore": "Alberto Gilardino"},
                {"id": 2, "nome": "Fiorentina", "allenatore": "Fabio Grosso"},
                {"id": 3, "nome": "Senza Mister", "allenatore": None},
            ],
        }

    def test_i_quattro_esiti(self):
        casi = [
            {"lega": "Serie A", "squadra": "Parma",
             "allenatore_atteso": "Alberto Gilardino", "allenatore_uscente": "Carlos Cuesta"},
            {"lega": "Serie A", "squadra": "Fiorentina",
             "allenatore_atteso": "Paolo Vanoli", "allenatore_uscente": "Fabio Grosso"},
            {"lega": "Serie A", "squadra": "Senza Mister",
             "allenatore_atteso": "Pinco Pallino"},
            {"lega": "Serie A", "squadra": "Bologna",
             "allenatore_atteso": "Raffaele Palladino"},
        ]
        esiti = {c["squadra"]: c for c in
                 sa.confronta_casi(casi, self._voci(), "2026-10-13T09:00:00Z")}
        self.assertEqual("aggiornato", esiti["Parma"]["esito"])
        self.assertEqual("non aggiornato", esiti["Fiorentina"]["esito"])
        self.assertEqual("api senza allenatore", esiti["Senza Mister"]["esito"])
        self.assertEqual("squadra non nel run", esiti["Bologna"]["esito"])
        self.assertEqual("Fabio Grosso", esiti["Fiorentina"]["allenatore_api"])
        self.assertIn("uscente", esiti["Fiorentina"]["dettaglio"])
        self.assertIn("Vanoli", esiti["Fiorentina"]["dettaglio"])
        for caso in esiti.values():
            with self.subTest(squadra=caso["squadra"]):
                self.assertEqual("2026-10-13T09:00:00Z", caso["rilevato_il"])

    def test_nome_di_battesimo_mancante_nelle_api(self):
        casi = [{"lega": "Bundesliga", "squadra": "Borussia Mönchengladbach",
                 "allenatore_atteso": "Blessin", "allenatore_uscente": "Polanski"}]
        voci = {"Bundesliga": [{"id": 9, "nome": "Borussia Mönchengladbach",
                                "allenatore": "Alexander Blessin"}]}
        self.assertEqual("aggiornato",
                         sa.confronta_casi(casi, voci, "2026-10-13T09:00:00Z")[0]["esito"])

    def test_casi_dal_file_del_repository(self):
        """Il file dei casi pubblici e' leggibile e ogni caso ha fonte e data."""
        casi = sa.carica_casi(str(CASI))
        self.assertGreaterEqual(len(casi), 3, "servono almeno 3 casi pubblici")
        for caso in casi:
            with self.subTest(caso=caso.get("squadra")):
                self.assertTrue(caso.get("fonte", "").startswith("http"))
                self.assertRegex(caso.get("data_cambio", ""), r"^\d{4}-\d{2}-\d{2}$")
                self.assertTrue(caso.get("allenatore_atteso"))
                self.assertTrue(caso.get("allenatore_uscente"))
                self.assertIn(caso["lega"], tuple(sa.LEGHE))
        self.assertGreaterEqual(len({c["lega"] for c in casi}), 3,
                                "i casi coprono almeno tre leghe")

    def test_senza_casi_il_giudizio_non_e_affidabile(self):
        cop = sa.copertura(_cinque_leghe())
        esito = sa.giudizio(cop, [])
        self.assertFalse(esito["casi_ok"])
        self.assertFalse(esito["affidabile"])
        self.assertIn("nessun caso verificabile", esito["motivi"])


class TestCoperturaEFormato(unittest.TestCase):
    def test_copertura_per_lega_e_totale(self):
        cop = sa.copertura({
            "Serie A": [{"nome": "A", "allenatore": "Uno"},
                        {"nome": "B", "allenatore": None}],
            "Bundesliga": [{"nome": "C", "allenatore": "Due"}],
        })
        self.assertEqual(3, cop["squadre"])
        self.assertEqual(2, cop["con_allenatore"])
        self.assertAlmostEqual(2 / 3, cop["frazione"], places=6)
        self.assertEqual(cop["frazione"], cop["percentuale"])
        self.assertEqual(sa.SOGLIA_COPERTURA, cop["soglia"])
        self.assertEqual(["B"], cop["per_lega"]["Serie A"]["senza"])
        self.assertEqual(["Serie A: B"], cop["senza_allenatore"])
        self.assertEqual(0.0, sa.copertura({})["frazione"])
        self.assertEqual(0.0, sa.copertura([])["frazione"])

    def test_giudizio_applica_la_soglia(self):
        # 19 squadre su 20 con allenatore = 95%: soglia raggiunta
        tutte = {l: [{"nome": f"{l}{i}", "allenatore": "Uno"} for i in range(4)]
                 for l in sa.LEGHE}
        sopra = copy.deepcopy(tutte)
        sopra["Serie A"][0]["allenatore"] = None           # 19/20 = 95%
        sotto = copy.deepcopy(tutte)
        sotto["Serie A"][0]["allenatore"] = None
        sotto["Serie A"][1]["allenatore"] = None           # 18/20 = 90%
        casi_ok = [{"esito": "aggiornato"}] * 3
        esito = sa.giudizio(sa.copertura(sotto), casi_ok)
        self.assertTrue(esito["valutabile"])
        self.assertFalse(esito["copertura_ok"])
        self.assertFalse(esito["affidabile"])
        self.assertIn("copertura 90.0% < 95%", esito["motivi"])
        self.assertTrue(sa.giudizio(sa.copertura(sopra), casi_ok)["affidabile"])

    def test_forme_delle_date(self):
        forme = sa.forme_date({"Serie A": [
            {"forme_date": ["inizio: mese", "fine: mese"]},
            {"forme_date": ["inizio: giorno"]},
            {"forme_date": []},
        ]})
        self.assertEqual({"fine: mese": 1, "inizio: giorno": 1, "inizio: mese": 1}, forme)


class TestFileSicuri(unittest.TestCase):
    """I file salvati non contengono mai la chiave, e non si sovrascrivono."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sonda_all_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scrivi_json_rifiuta_la_chiave(self):
        with self.assertRaises(RuntimeError):
            sa.scrivi_json(str(self.tmp / "x.json"), {"nota": "chiave finta"},
                           chiavi_da_escludere=("chiave finta",))
        self.assertFalse((self.tmp / "x.json").exists(), "il file non si scrive proprio")
        percorso = sa.scrivi_json(str(self.tmp / "ok.json"), {"nota": "niente"},
                                  chiavi_da_escludere=("chiave finta",))
        self.assertTrue(Path(percorso).exists())

    def test_snapshot_del_giorno_non_sovrascrive(self):
        primo = sa.scrivi_snapshot(str(self.tmp), "2026-10-13", {"a": 1},
                                   "2026-10-13T09:00:00Z")
        secondo = sa.scrivi_snapshot(str(self.tmp), "2026-10-13", {"a": 2},
                                     "2026-10-13T18:00:00Z")
        self.assertTrue(primo.endswith("2026-10-13.json"))
        self.assertTrue(secondo.endswith("2026-10-13_02.json"))
        self.assertEqual(1, json.loads(Path(primo).read_text(encoding="utf-8"))["a"])
        self.assertEqual(2, json.loads(Path(secondo).read_text(encoding="utf-8"))["a"])


class TestGiroCompletoConFixture(unittest.TestCase):
    """Il giro intero in modalita' fixture: file del giorno + referto."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="sonda_all_e2e_"))
        cls.rc = sa.main(["--fixture", str(FIXTURE),
                          "--leagues", "Serie A", "Bundesliga",
                          "--out-dir", str(cls.tmp / "data"),
                          "--results-dir", str(cls.tmp / "results"),
                          "--casi", str(CASI), "--stagione", ""])
        cls.file = next((cls.tmp / "data").glob("*.json"))
        cls.snapshot = json.loads(cls.file.read_text(encoding="utf-8"))
        cls.referto = (cls.tmp / "results" / "fixture_sonda_allenatori.md").read_text(
            encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_codice_di_uscita_e_chiamate(self):
        self.assertEqual(0, self.rc)
        self.assertEqual(0, self.snapshot["chiamate"], "con la fixture nessuna chiamata")
        self.assertEqual("fixture", self.snapshot["modalita"])

    def test_i_file_della_fixture_portano_il_prefisso(self):
        """Un run con risposte finte non usa MAI il nome dello snapshot reale."""
        self.assertTrue(self.file.name.startswith(sa.PREFISSO_FIXTURE),
                        f"file senza prefisso fixture_: {self.file.name}")
        for percorso in (self.tmp / "data").glob("*.json"):
            with self.subTest(file=percorso.name):
                self.assertTrue(percorso.name.startswith(sa.PREFISSO_FIXTURE))
        self.assertFalse((self.tmp / "data" / f"{sa.PREFISSO_FIXTURE[:-1]}.json").exists())
        self.assertIn(sa.PREFISSO_FIXTURE, self.referto,
                      "il referto di prova deve dire che i file sono fixture_")

    def test_una_voce_per_squadra_con_istante_della_lettura(self):
        for lega, voci in self.snapshot["squadre_per_lega"].items():
            for voce in voci:
                with self.subTest(squadra=voce.get("nome")):
                    self.assertRegex(voce["rilevato_il"],
                                     r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
                    self.assertIn("id", voce)
                    self.assertIn("allenatore", voce)
                    self.assertIn("contratto_dal", voce)
                    self.assertIn("contratto_fino", voce)
        squadre = [v for voci in self.snapshot["squadre_per_lega"].values() for v in voci]
        self.assertEqual(6, len(squadre))
        self.assertEqual(["Senza Mister"],
                         [v["nome"] for v in squadre if not v["allenatore"]])

    def test_copertura_nel_file(self):
        cop = self.snapshot["copertura"]
        self.assertEqual(6, cop["squadre"])
        self.assertEqual(5, cop["con_allenatore"])
        self.assertAlmostEqual(5 / 6, cop["frazione"], places=4)
        self.assertEqual(sa.SOGLIA_COPERTURA, cop["soglia"])

    def test_regola_prima_dei_numeri_e_esito_dichiarato(self):
        pos_regola = self.referto.index("Regola dichiarata")
        pos_copertura = self.referto.index("## Copertura")
        pos_casi = self.referto.index("## Casi pubblici")
        self.assertLess(pos_regola, pos_copertura)
        self.assertLess(pos_regola, pos_casi)
        self.assertIn("95%", self.referto)
        # il giro della fixture ha solo 2 leghe: la regola NON si valuta
        self.assertIn("Esito di questo run: **NON VALUTABILE**", self.referto)
        self.assertIn("non valutabile: leghe mancanti Premier League, La Liga, Ligue 1",
                      self.referto)
        self.assertNotIn("NON AFFIDABILE", self.referto)
        self.assertIn("Età (giorni)", self.referto)
        self.assertIn("non aggiornato", self.referto)
        self.assertIn("aggiornato", self.referto)
        self.assertIn("Run di PROVA", self.referto,
                      "un run con risposte finte deve dichiararlo in testa")
        self.assertIn("audit/output/", self.referto,
                      "il referto di prova deve dichiarare dove scrive")

    def test_nessuna_chiave_nel_file_e_nel_referto(self):
        for testo in (self.file.read_text(encoding="utf-8"), self.referto):
            self.assertNotIn("FOOTBALL_DATA_API_KEY", testo)
            self.assertNotIn("apiKey", testo)

    def test_senza_chiave_non_si_chiama_nulla(self):
        with mock.patch.object(sa, "leggi_chiave", return_value=""):
            rc = sa.main(["--leagues", "Serie A",
                          "--out-dir", str(self.tmp / "data2"),
                          "--results-dir", str(self.tmp / "results2")])
        self.assertEqual(3, rc, "senza chiave la sonda esce con 3 e non chiama")
        self.assertFalse((self.tmp / "data2").exists())
        self.assertFalse((self.tmp / "results2").exists())

    def test_leggi_chiave_dai_due_nomi_di_variabile(self):
        self.assertEqual("abc", sa.leggi_chiave({"FOOTBALL_DATA_API_KEY": "abc"}))
        self.assertEqual("def", sa.leggi_chiave({"API_KEY_DATA": " def "}))
        self.assertEqual("abc", sa.leggi_chiave({"FOOTBALL_DATA_API_KEY": "abc",
                                                 "API_KEY_DATA": "def"}))


class TestLaFixtureNonScriveNelloSnapshotReale(unittest.TestCase):
    """Il run `--fixture` non tocca MAI `audit/data/allenatori/`.

    E' la prova chiesta: senza `--out-dir` (e senza `--results-dir`) un giro con
    risposte finte deve finire in `audit/output/`, la cartella NON versionata,
    con il prefisso `fixture_`: nella cartella degli snapshot reali non deve
    comparire nessun file nuovo, e in particolare nessun `<giorno>.json`.
    """

    CARTELLA = REPO_ROOT / "audit" / "data" / "allenatori"
    OUTPUT = REPO_ROOT / "audit" / "output" / "sonda_allenatori"

    def test_un_run_fixture_non_crea_file_nello_snapshot_del_giorno(self):
        prima = sorted(f.name for f in self.CARTELLA.iterdir())
        oggi = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        creati = []
        try:
            rc = sa.main(["--fixture", str(FIXTURE), "--leagues", "Serie A",
                          "--casi", str(CASI), "--stagione", ""])
            self.assertEqual(0, rc)
            dopo = sorted(f.name for f in self.CARTELLA.iterdir())
            self.assertEqual(prima, dopo,
                             "la modalita' fixture ha scritto nella cartella degli "
                             "snapshot reali")
            for nome in dopo:
                if not nome.endswith(".json") or nome.startswith("casi_"):
                    continue
                dati = json.loads((self.CARTELLA / nome).read_text(encoding="utf-8"))
                self.assertNotEqual("fixture", dati.get("modalita"),
                                    f"{nome}: uno snapshot reale viene da una fixture")
            prova = sorted(self.OUTPUT.glob(f"{sa.PREFISSO_FIXTURE}*"))
            creati = list(prova)
            self.assertTrue(prova, "la fixture deve scrivere in audit/output/")
            for percorso in prova:
                with self.subTest(file=percorso.name):
                    self.assertTrue(percorso.name.startswith(sa.PREFISSO_FIXTURE))
                    self.assertFalse(percorso.name.endswith(f"{oggi}.json")
                                     and not percorso.name.startswith(sa.PREFISSO_FIXTURE))
            self.assertTrue((self.OUTPUT / "fixture_sonda_allenatori.md").exists())
        finally:
            for percorso in creati:
                percorso.unlink(missing_ok=True)


class TestRefertoNonEseguito(unittest.TestCase):
    """Il referto «sonda non eseguita»: regola, casi con fonte, «da misurare»."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="sonda_all_non_"))
        cartella = REPO_ROOT / "audit" / "data" / "allenatori"
        cls.prima = sorted(f.name for f in cartella.iterdir())
        cls.rc = sa.main(["--referto-non-eseguito", "--casi", str(CASI),
                          "--results-dir", str(cls.tmp)])
        cls.dopo = sorted(f.name for f in cartella.iterdir())
        cls.referto = (cls.tmp / "sonda_allenatori.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_testa_regola_prima_dei_numeri_e_nessun_esito(self):
        self.assertEqual(0, self.rc)
        self.assertIn("Sonda non eseguita: nessuna chiamata reale a "
                      "football-data.org", self.referto[:400])
        self.assertIn("Regola dichiarata", self.referto)
        # La regola viene PRIMA della tabella dei casi.
        self.assertLess(self.referto.index("Regola dichiarata"),
                        self.referto.index("| da misurare |"))
        # Nessun numero di questo referto e' un risultato.
        for vietato in ("NON AFFIDABILE", "Copertura (squadre", "Esito di questo run",
                        "non aggiornato", "non e' affidabile: motivi"):
            with self.subTest(vietato=vietato):
                self.assertNotIn(vietato, self.referto)

    def test_colonna_da_misurare_e_fonti(self):
        dati = json.loads(CASI.read_text(encoding="utf-8"))
        for caso in dati["casi"]:
            with self.subTest(squadra=caso["squadra"]):
                self.assertIn(caso["squadra"], self.referto)
                self.assertIn(caso["fonte"], self.referto)
        self.assertEqual(len(dati["casi"]), self.referto.count("| da misurare |"))
        self.assertIn("audit/data/allenatori/<giorno>.json", self.referto)

    def test_non_scrive_snapshot_del_giorno(self):
        self.assertEqual([], list(self.tmp.glob("*.json")))
        # nessun file nuovo nella cartella degli snapshot (il confronto e' fra
        # l'elenco prima e dopo: lo snapshot reale del giorno puo' gia' esserci)
        self.assertEqual(self.prima, self.dopo)


class TestReteSenzaChiamateRiuscite(unittest.TestCase):
    """Run di rete con tutte le chiamate fallite: errore, e NESSUN file.

    E' la regola dello snapshot con la data: si scrive solo se almeno una lega
    e' arrivata in fondo. Un file con la data scritto da un run fallito
    sembrerebbe una misura, e non lo e'.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sonda_all_fail_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_nessun_file_e_codice_di_errore(self):
        with mock.patch.object(sa, "leggi_chiave", return_value="chiave-finta"), \
             mock.patch.object(sa, "scarica_lega",
                               side_effect=RuntimeError("rete giu'")):
            rc = sa.main(["--out-dir", str(self.tmp / "data"),
                          "--results-dir", str(self.tmp / "results"),
                          "--casi", str(CASI), "--keep-going"])
        self.assertEqual(2, rc, "senza chiamate riuscite la sonda deve uscire con 2")
        self.assertEqual([], list((self.tmp / "data").glob("*.json")))
        self.assertFalse((self.tmp / "results").exists(),
                         "nessun referto: non c'e' nessuna misura da scrivere")


class TestSoloLeTreChiamateAttese(unittest.TestCase):
    """La rete e' finta ma il giro e' quello vero: 1 chiamata per lega + 1 per squadra."""

    def test_scarica_lega_usa_le_due_rotte(self):
        chiamate = []

        class Risposta:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        class Sessione:
            def get(self, url, headers=None, params=None, timeout=None):
                chiamate.append((url, dict(headers or {}), dict(params or {})))
                if url.endswith("/teams"):
                    return Risposta({"teams": [{"id": 11, "name": "A"},
                                               {"id": 12, "name": "B"}]})
                return Risposta({"coach": {"id": 5, "name": "Tizio",
                                           "contract": {"start": "2026-07",
                                                        "until": "2028-06"}}})

        finestra = sa.FinestraChiamate(10, orologio=lambda: 0.0, dormi=lambda s: None)
        voci = sa.scarica_lega("SA", 2026, "chiave-finta", finestra, session=Sessione())
        self.assertEqual(3, len(chiamate))
        self.assertEqual(f"{sa.API_BASE}/competitions/SA/teams", chiamate[0][0])
        self.assertEqual(f"{sa.API_BASE}/teams/11", chiamate[1][0])
        self.assertEqual({"season": 2026}, chiamate[0][2])
        for url, headers, _ in chiamate:
            self.assertEqual("chiave-finta", headers["X-Auth-Token"])
            self.assertNotIn("chiave-finta", url, "la chiave non sta nell'URL")
        self.assertEqual(2, len(voci))
        self.assertEqual("Tizio", voci[0]["allenatore"])

    def test_errore_di_chiave_non_stampa_la_chiave(self):
        class Risposta:
            status_code = 403

            def raise_for_status(self):  # pragma: no cover - non deve arrivare qui
                raise AssertionError("con 403 non si prosegue")

        class Sessione:
            def get(self, url, headers=None, params=None, timeout=None):
                return Risposta()

        with self.assertRaises(RuntimeError) as errore:
            sa.http_get(f"{sa.API_BASE}/competitions/SA/teams", "chiave-segreta",
                        session=Sessione())
        self.assertNotIn("chiave-segreta", str(errore.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
