"""Grading delle righe in attesa: selezione, fonti, e le due garanzie che contano.

Le proprieta' provate qui sono quelle che rendono la scrittura sicura sul Registro
vivo:

* si selezionano SOLO righe senza esito la cui partita e' finita da un pezzo (una
  partita di ieri sera non e' un buco, e' un risultato che deve ancora arrivare);
* una riga che ha gia' un esito non si tocca mai, e un risultato dichiarato diverso
  da quello vero ferma la riga invece di riscriverla;
* il risultato dell'API viene accettato solo se la partita e' quella giusta
  (id, stato FINISHED, squadre, giorno): un risultato sulla partita sbagliata e'
  peggio di un risultato mancante;
* le due fonti (API e archivio della stagione) devono COINCIDERE, altrimenti la
  riga si salta e si dichiara;
* la scrittura tocca esattamente due campi per riga e nessun altro: la verifica
  dopo la scrittura lo controlla riga per riga, campo per campo.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import registry_grading as RG  # noqa: E402
import registry_store as rs  # noqa: E402


def _riga(match_id, *, home="Milan", away="Cagliari", data="24/05/2026 20:45",
          salvato="23/05/2026 08:19", mercato="1", esito="⏳", campionato="Serie A",
          stagione="2025/2026", variante="legacy", risultato=None, origine="top_mix"):
    r = {"match_id": match_id, "home": home, "away": away, "campionato": campionato,
         "giornata": 38, "data": data, "pronostico_sicuro": f"{mercato} - Top Mix",
         "mercato_standard": mercato, "prob_sicuro": 64.5, "risultato_reale": risultato,
         "esito": esito, "origin": origine, "model_variant": variante,
         "salvato_il": salvato, "stagione": stagione, "model_version": "post_shrinkage_v1"}
    return r


def _api(match_id, *, casa="Milan", ospite="Cagliari", gh=1, ga=2, status="FINISHED",
         utc="2026-05-24T18:45:00Z"):
    return {"id": int(match_id), "status": status, "utcDate": utc,
            "homeTeam": {"shortName": casa, "name": casa},
            "awayTeam": {"shortName": ospite, "name": ospite},
            "score": {"fullTime": {"home": gh, "away": ga}}}


class TestSelezione(unittest.TestCase):
    """Chi entra nel grading e chi no."""

    ADESSO = RG.datetime(2026, 9, 21, 20, 0, tzinfo=RG.UTC)

    def test_solo_le_righe_senza_esito(self):
        righe = [_riga(1), _riga(2, esito="✅"), _riga(3, esito="❌")]
        sel = RG.seleziona_in_attesa(righe, adesso=self.ADESSO)
        self.assertEqual([1], [r["match_id"] for r in sel])

    def test_una_partita_appena_giocata_non_e_un_buco(self):
        righe = [_riga(1, data="21/09/2026 18:00")]
        self.assertEqual([], RG.seleziona_in_attesa(righe, adesso=self.ADESSO))

    def test_una_partita_futura_non_si_seleziona(self):
        righe = [_riga(1, data="25/09/2026 20:45")]
        self.assertEqual([], RG.seleziona_in_attesa(righe, adesso=self.ADESSO))

    def test_riga_senza_data_leggibile_non_si_seleziona(self):
        righe = [_riga(1, data="")]
        self.assertEqual([], RG.seleziona_in_attesa(righe, adesso=self.ADESSO))

    def test_ordinamento_per_data_di_partita(self):
        righe = [_riga(1, data="24/05/2026 20:45"), _riga(2, data="23/05/2026 18:00")]
        sel = RG.seleziona_in_attesa(righe, adesso=self.ADESSO)
        self.assertEqual([2, 1], [r["match_id"] for r in sel])

    def test_filtro_per_stagione(self):
        righe = [_riga(1), _riga(2, stagione="2026/2027", data="06/09/2026 18:00", salvato="05/09/2026 12:00")]
        sel = RG.seleziona_in_attesa(righe, adesso=self.ADESSO, stagione="2025/2026")
        self.assertEqual([1], [r["match_id"] for r in sel])

    def test_la_stagione_si_ricava_dalla_data_quando_manca(self):
        riga = _riga(1)
        riga.pop("stagione")
        self.assertEqual("2025/2026", RG.stagione_riga(riga))


class TestValidazioneDellaPartita(unittest.TestCase):
    """Il risultato vale solo se la partita e' quella della riga."""

    def test_partita_valida(self):
        riga = _riga(537186)
        ok, motivo = RG.valida_partita(_api(537186), riga)
        self.assertTrue(ok, motivo)

    def test_partita_non_finita_non_si_usa(self):
        ok, motivo = RG.valida_partita(_api(537186, status="TIMED"), _riga(537186))
        self.assertFalse(ok)
        self.assertIn("non finita", motivo)

    def test_risultato_finale_assente(self):
        payload = _api(537186)
        payload["score"]["fullTime"] = {"home": None, "away": None}
        ok, motivo = RG.valida_partita(payload, _riga(537186))
        self.assertFalse(ok)
        self.assertIn("assente", motivo)

    def test_squadre_diverse_non_si_usa(self):
        ok, motivo = RG.valida_partita(_api(537186, casa="Inter"), _riga(537186))
        self.assertFalse(ok)
        self.assertIn("casa diversa", motivo)

    def test_giorno_diverso_non_si_usa(self):
        ok, motivo = RG.valida_partita(_api(537186, utc="2026-05-30T18:45:00Z"), _riga(537186))
        self.assertFalse(ok)
        self.assertIn("giorno diverso", motivo)

    def test_id_diverso_non_si_usa(self):
        ok, motivo = RG.valida_partita(_api(1), _riga(537186))
        self.assertFalse(ok)
        self.assertIn("id diverso", motivo)

    def test_nome_display_uguale_a_quello_della_riga(self):
        """L'API risponde con lo shortName, la riga mostra il nome display."""
        ok, motivo = RG.valida_partita(_api(537189, casa="Verona", ospite="Roma"),
                                       _riga(537189, home="Verona", away="Roma"))
        self.assertTrue(ok, motivo)
        # "Athletic" e' lo shortName, "Ath Bilbao" il nome canonico: la riga
        # scritta dal vivo porta "Athletic", quindi il confronto passa da clean_name.
        ok, motivo = RG.valida_partita(_api(544587, casa="Athletic", ospite="Real Madrid"),
                                       _riga(544587, home="Real Madrid", away="Athletic"))
        self.assertFalse(ok)          # casa/ospiti invertiti: si accorge
        ok, motivo = RG.valida_partita(_api(544587, casa="Real Madrid", ospite="Athletic"),
                                       _riga(544587, home="Real Madrid", away="Athletic"))
        self.assertTrue(ok, motivo)


class TestArchivioDellaStagione(unittest.TestCase):
    """La controprova locale: la partita si ritrova UNA volta sola."""

    CSV = [
        {"Date": "23/05/2026", "HomeTeam": "Bologna", "AwayTeam": "Inter", "FTHG": "3", "FTAG": "3"},
        {"Date": "24/05/2026", "HomeTeam": "Milan", "AwayTeam": "Cagliari", "FTHG": "1", "FTAG": "2"},
        {"Date": "24/05/2026", "HomeTeam": "Milan", "AwayTeam": "Cagliari", "FTHG": "0", "FTAG": "0"},
    ]

    def test_partita_trovata(self):
        gol, motivo = RG.risultato_da_archivio(_riga(537187, home="Bologna", away="Inter", data="23/05/2026 18:00"),
                                               righe_csv=self.CSV)
        self.assertEqual((3, 3), gol, motivo)

    def test_partita_ambigua_non_si_usa(self):
        gol, motivo = RG.risultato_da_archivio(_riga(537186), righe_csv=self.CSV)
        self.assertIsNone(gol)
        self.assertIn("ambigua", motivo)

    def test_partita_assente(self):
        gol, motivo = RG.risultato_da_archivio(_riga(1, home="Roma", away="Lazio"), righe_csv=self.CSV)
        self.assertIsNone(gol)
        self.assertIn("non trovata", motivo)

    def test_alias_dichiarato_per_i_nomi_non_piu_in_tabella(self):
        """Oviedo e Wolves: nomi diversi fra riga e archivio, dichiarati a mano."""
        csv_righe = [{"Date": "23/05/2026", "HomeTeam": "Mallorca", "AwayTeam": "Oviedo",
                      "FTHG": "3", "FTAG": "0"},
                     {"Date": "24/05/2026", "HomeTeam": "Burnley", "AwayTeam": "Wolves",
                      "FTHG": "1", "FTAG": "1"}]
        gol, motivo = RG.risultato_da_archivio(
            _riga(544586, home="Mallorca", away="Real Oviedo", data="23/05/2026 21:00",
                  campionato="La Liga"), righe_csv=csv_righe)
        self.assertEqual((3, 0), gol, motivo)
        gol, motivo = RG.risultato_da_archivio(
            _riga(538158, home="Burnley", away="Wolverhampton", data="24/05/2026 17:00",
                  campionato="Premier League"), righe_csv=csv_righe)
        self.assertEqual((1, 1), gol, motivo)


class TestCampiGrading(unittest.TestCase):
    """Cosa si scrive, e cosa NON si riscrive."""

    def test_due_campi_e_l_esito_della_produzione(self):
        campi, motivo = RG.campi_grading(_riga(1, mercato="1"), 1, 2)
        self.assertEqual({"risultato_reale": "1-2", "esito": "❌"}, campi, motivo)
        campi, _ = RG.campi_grading(_riga(1, mercato="UNDER_2.5"), 1, 2)   # 3 gol: under NO
        self.assertEqual("❌", campi["esito"])
        campi, _ = RG.campi_grading(_riga(1, mercato="UNDER_2.5"), 1, 0)
        self.assertEqual("✅", campi["esito"])
        campi, _ = RG.campi_grading(_riga(1, mercato="GG"), 1, 2)
        self.assertEqual("✅", campi["esito"])
        campi, _ = RG.campi_grading(_riga(1, mercato="NG"), 1, 2)
        self.assertEqual("❌", campi["esito"])

    def test_mercato_non_graduabile_non_si_tocca(self):
        campi, motivo = RG.campi_grading(_riga(1, mercato="ALTRO"), 1, 2)
        self.assertIsNone(campi)
        self.assertIn("non graduabile", motivo)

    def test_risultato_gia_dichiarato_diverso_ferma_la_riga(self):
        campi, motivo = RG.campi_grading(_riga(1, risultato="5-5"), 1, 2)
        self.assertIsNone(campi)
        self.assertIn("gia'", motivo)

    def test_risultato_gia_dichiarato_uguale_non_ferma(self):
        campi, motivo = RG.campi_grading(_riga(1, risultato="1-2"), 1, 2)
        self.assertEqual("❌", campi["esito"], motivo)

    def test_applica_cambia_solo_i_campi_indicati(self):
        riga = _riga(1)
        nuova = RG.applica(riga, {"risultato_reale": "1-2", "esito": "❌"})
        diverse = {k for k in set(riga) | set(nuova) if riga.get(k) != nuova.get(k)}
        self.assertEqual({"risultato_reale", "esito"}, diverse)
        self.assertEqual("1", nuova["mercato_standard"])


class TestPiano(unittest.TestCase):
    """Il piano completo: fonti, controprova, salvataggi."""

    def _righe(self):
        return [
            _riga(537186, home="Milan", away="Cagliari", data="24/05/2026 20:45"),
            _riga(537187, home="Bologna", away="Inter", data="23/05/2026 18:00", mercato="1"),
            _riga(538158, home="Burnley", away="Wolverhampton", data="24/05/2026 17:00",
                  campionato="Premier League", mercato="UNDER_2.5"),
            _riga(999999, home="Roma", away="Lazio", data="24/05/2026 20:45"),
        ]

    def test_fonte_file_senza_rete(self):
        p = RG.piano(self._righe(), fonte="file", risultati={"537186": "1-2", "537187": "3-3",
                                                             "538158": "1-1"},
                     adesso=RG.datetime(2026, 9, 21, 20, 0, tzinfo=RG.UTC))
        self.assertEqual(4, p["selezionate"])
        self.assertEqual(3, len(p["da_gradare"]))
        self.assertEqual(["file"], p["da_gradare"][0]["fonti"])
        self.assertEqual(1, len(p["saltate"]))

    def test_api_e_archivio_devono_coincidere(self):
        with mock.patch.object(RG, "partita_da_api", return_value=(_api(537186), "")), \
             mock.patch.object(RG, "percorso_archivio", return_value="finto.csv"), \
             mock.patch.object(RG, "risultato_da_archivio", return_value=((1, 2), "")):
            p = RG.piano([_riga(537186)], api_key="x")
        self.assertEqual(1, len(p["da_gradare"]))
        self.assertEqual(["api", "archivio"], p["da_gradare"][0]["fonti"])
        with mock.patch.object(RG, "partita_da_api", return_value=(_api(537186), "")), \
             mock.patch.object(RG, "percorso_archivio", return_value="finto.csv"), \
             mock.patch.object(RG, "risultato_da_archivio", return_value=((0, 0), "")):
            p = RG.piano([_riga(537186)], api_key="x")
        self.assertEqual(0, len(p["da_gradare"]))
        self.assertIn("disaccordo", p["saltate"][0]["saltata"])

    def test_senza_api_si_usa_l_archivio_e_il_motivo_resta_nel_referto(self):
        with mock.patch.object(RG, "partita_da_api", return_value=(None, "HTTP 403")), \
             mock.patch.object(RG, "risultato_da_archivio", return_value=((1, 2), "")):
            p = RG.piano([_riga(537186)], api_key="")
        voce = p["da_gradare"][0]
        self.assertEqual(["archivio"], voce["fonti"])
        self.assertEqual("HTTP 403", voce["api"])
        self.assertIn("HTTP 403", "\n".join(RG.righe_compatti(p)))

    def test_partita_non_valida_va_nell_elenco_delle_saltate(self):
        with mock.patch.object(RG, "partita_da_api",
                               return_value=(_api(537186, status="TIMED"), "")), \
             mock.patch.object(RG, "risultato_da_archivio",
                               return_value=(None, "archivio della stagione non disponibile")):
            p = RG.piano([_riga(537186)], api_key="x")
        self.assertEqual(0, len(p["da_gradare"]))
        self.assertEqual(1, len(p["saltate"]))
        self.assertIn("non finita", p["saltate"][0]["saltata"])

    def test_la_scrittura_reale_usa_i_soli_due_campi(self):
        """Dal piano alla riga scritta: due campi, e la probabilita' non si tocca."""
        with mock.patch.object(RG, "partita_da_api", return_value=(_api(537186), "")), \
             mock.patch.object(RG, "risultato_da_archivio", return_value=((1, 2), "")):
            p = RG.piano([_riga(537186)], api_key="x")
        riga = _riga(537186)
        nuova = RG.applica(riga, p["da_gradare"][0]["campi"])
        self.assertEqual("1-2", nuova["risultato_reale"])
        self.assertEqual("❌", nuova["esito"])
        self.assertEqual(riga["prob_sicuro"], nuova["prob_sicuro"])
        self.assertEqual(riga["pronostico_sicuro"], nuova["pronostico_sicuro"])


class TestVerificaScrittura(unittest.TestCase):
    """La verifica indipendente: due campi per riga, tutto il resto identico."""

    def _prima(self):
        return [_riga(1), _riga(2, esito="✅", risultato="2-0", mercato="OVER_2.5")]

    def test_scrittura_corretta(self):
        prima = self._prima()
        dopo = [RG.applica(prima[0], {"risultato_reale": "1-2", "esito": "❌"}), prima[1]]
        v = RG.verifica_scrittura(prima, dopo, {"1": {"risultato_reale": "1-2", "esito": "❌"}})
        self.assertTrue(v["ok"], v["dettagli"])
        self.assertEqual(1, v["righe_gradate"])
        self.assertTrue(v["fuori_selezione_identiche"])

    def test_una_riga_non_selezionata_cambiata_e_un_guasto(self):
        prima = self._prima()
        dopo = [RG.applica(prima[0], {"risultato_reale": "1-2", "esito": "❌"}),
                dict(prima[1], prob_sicuro=99.0)]
        v = RG.verifica_scrittura(prima, dopo, {"1": {"risultato_reale": "1-2", "esito": "❌"}})
        self.assertFalse(v["ok"])
        self.assertFalse(v["fuori_selezione_identiche"])

    def test_un_campo_in_piu_modificato_e_un_guasto(self):
        prima = self._prima()
        dopo = [dict(prima[0], risultato_reale="1-2", esito="❌", prob_sicuro=1.0), prima[1]]
        v = RG.verifica_scrittura(prima, dopo, {"1": {"risultato_reale": "1-2", "esito": "❌"}})
        self.assertFalse(v["ok"])
        self.assertEqual(1, v["campi_sbagliati"])

    def test_esito_rimasto_in_attesa(self):
        prima = self._prima()
        dopo = [dict(prima[0], risultato_reale="1-2"), prima[1]]
        v = RG.verifica_scrittura(prima, dopo, {"1": {"risultato_reale": "1-2", "esito": "❌"}})
        self.assertFalse(v["ok"])
        self.assertEqual(1, v["ancora_in_attesa"])

    def test_riga_sparita_e_un_guasto(self):
        prima = self._prima()
        v = RG.verifica_scrittura(prima, [prima[1]], {"1": {"risultato_reale": "1-2", "esito": "❌"}})
        self.assertFalse(v["ok"])


class TestRiparazioneNomiVecchi(unittest.TestCase):
    """Un aggiornamento sotto un nome di campo VECCHIO lascia un doppione da togliere.

    Il salvataggio scrive la riga sotto il nome canonico di oggi; la copia sotto il
    nome di una convenzione precedente resta con il contenuto di prima, e due campi
    con la stessa chiave e contenuto diverso FERMANO la lettura del Registro. Qui si
    prova che si toglie SOLO quel campo: non il canonico, non i campi di altre righe.
    """

    def _coppia(self):
        prima = _riga(537186)
        dopo = RG.applica(prima, {"risultato_reale": "1-2", "esito": "❌"})
        return prima, dopo

    def test_toglie_il_nome_vecchio_e_risparmia_il_canonico(self):
        prima, dopo = self._coppia()
        grezzi = {"537186|top_mix||current": (RG.canon(prima), prima),
                  "537186|top_mix||legacy": (RG.canon(dopo), dopo)}
        nomi = RG.nomi_stantii(grezzi, {"537186|top_mix||legacy": prima},
                              {"537186|top_mix||legacy": dopo})
        self.assertEqual(["537186|top_mix||current"], nomi)

    def test_un_doppione_IDENTICO_non_si_tocca(self):
        """Se i due campi hanno lo stesso contenuto la lettura non si rompe: non e'
        compito di questa riparazione ripulirli."""
        prima, dopo = self._coppia()
        grezzi = {"537186|top_mix||current": (RG.canon(dopo), dopo),
                  "537186|top_mix||legacy": (RG.canon(dopo), dopo)}
        self.assertEqual([], RG.nomi_stantii(grezzi, {"537186|top_mix||legacy": prima},
                                            {"537186|top_mix||legacy": dopo}))

    def test_le_righe_di_altre_chiavi_non_si_toccano(self):
        prima, dopo = self._coppia()
        altra = _riga(999, home="Roma", away="Lazio")
        grezzi = {"537186|top_mix||current": (RG.canon(prima), prima),
                  "999|top_mix||legacy": (RG.canon(altra), altra)}
        nomi = RG.nomi_stantii(grezzi, {"537186|top_mix||legacy": prima, "999|top_mix||legacy": altra},
                              {"537186|top_mix||legacy": dopo, "999|top_mix||legacy": altra})
        self.assertEqual(["537186|top_mix||current"], nomi)

    def test_riparazione_verificata_dopo_la_scrittura(self):
        prima, dopo = self._coppia()
        with mock.patch.object(rs, "upstash_snapshot_read", return_value=[prima]), \
             mock.patch.object(RG, "campi_grezzi",
                               return_value={"537186|top_mix||current": (RG.canon(prima), prima)}), \
             mock.patch.object(RG, "piano", return_value={"selezionate": 1, "saltate": [], "voci": [],
                 "da_gradare": [{"match_id": 537186,
                                 "campi": {"risultato_reale": "1-2", "esito": "❌"}}]}), \
             mock.patch.object(rs, "upstash_raw", return_value={"result": 1}) as raw, \
             mock.patch.object(rs, "upstash_rows", return_value=[dopo]):
            r = RG.ripara_nomi(istantanea="2026-09-21-pre-grading", scrivi=True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(["537186|top_mix||current"], r["nomi_stantii"])
        self.assertTrue(raw.call_args[0][0][0] == "HDEL")

    def test_riparazione_in_prova_non_scrive(self):
        prima, _dopo = self._coppia()
        with mock.patch.object(rs, "upstash_snapshot_read", return_value=[prima]), \
             mock.patch.object(RG, "campi_grezzi",
                               return_value={"537186|top_mix||current": (RG.canon(prima), prima)}), \
             mock.patch.object(RG, "piano", return_value={"selezionate": 1, "saltate": [], "voci": [],
                 "da_gradare": [{"match_id": 537186,
                                 "campi": {"risultato_reale": "1-2", "esito": "❌"}}]}), \
             mock.patch.object(rs, "upstash_raw") as raw:
            r = RG.ripara_nomi(istantanea="2026-09-21-pre-grading", scrivi=False)
        self.assertFalse(r["scritto"])
        self.assertEqual(["537186|top_mix||current"], r["nomi_stantii"])
        raw.assert_not_called()

    def test_un_doppione_identico_su_una_riga_NON_toccata_non_si_tocca(self):
        """Fuori dalla richiesta: la scrittura aggiorna 10 righe, non fa pulizia
        generale dei nomi doppi preesistenti (che la lettura tollera)."""
        aggiornata = RG.applica(_riga(537186), {"risultato_reale": "1-2", "esito": "❌"})
        altra = _riga(999, home="Roma", away="Lazio")
        grezzi = {"537186|top_mix||current": (RG.canon(_riga(537186)), _riga(537186)),
                  "999|top_mix||current": (RG.canon(altra), altra)}
        nomi = RG.nomi_stantii(grezzi, {"537186|top_mix||legacy": _riga(537186),
                                       "999|top_mix||legacy": altra},
                              {"537186|top_mix||legacy": aggiornata,
                               "999|top_mix||legacy": altra},
                              {"537186|top_mix||legacy"})
        self.assertEqual(["537186|top_mix||current"], nomi)

    def test_diagnosi_conta_i_doppi_e_i_contenuti_diversi(self):
        a, b = _riga(1), _riga(2, home="Roma", away="Lazio")
        grezzi = {"1|top_mix||legacy": (RG.canon(a), a),
                  "1|top_mix||current": (RG.canon(a), a),          # doppione identico
                  "2|top_mix||legacy": (RG.canon(b), b)}
        with mock.patch.object(RG, "campi_grezzi", return_value=grezzi), \
             mock.patch.object(rs, "upstash_rows", return_value=[a, b]):
            d = RG.diagnosi_nomi()
        self.assertEqual(3, d["campi_grezzi"])
        self.assertEqual(2, d["righe_logiche"])
        self.assertEqual(1, d["chiavi_con_piu_nomi"])
        self.assertEqual(0, d["chiavi_con_contenuti_diversi"])
        self.assertTrue(d["lettura_ok"])

    def test_diagnosi_senza_istantanea_denuncia_i_contenuti_diversi(self):
        a, b = _riga(1), dict(_riga(1), esito="❌")
        grezzi = {"1|top_mix||legacy": (RG.canon(b), b),
                  "1|top_mix||current": (RG.canon(a), a)}
        with mock.patch.object(RG, "campi_grezzi", return_value=grezzi), \
             mock.patch.object(rs, "upstash_rows", side_effect=rs.RegistryStoreError("doppione")):
            d = RG.diagnosi_nomi()
        self.assertFalse(d["lettura_ok"])
        self.assertEqual(1, d["chiavi_con_contenuti_diversi"])

    def test_diagnosi_confronta_con_l_istantanea(self):
        prima = _riga(537186)
        dopo = RG.applica(prima, {"risultato_reale": "1-2", "esito": "❌"})
        with mock.patch.object(RG, "campi_grezzi",
                               return_value={rs.field_of(dopo): (RG.canon(dopo), dopo)}), \
             mock.patch.object(rs, "upstash_rows", return_value=[dopo]), \
             mock.patch.object(rs, "upstash_snapshot_read", return_value=[prima]), \
             mock.patch.object(RG, "piano", return_value={"selezionate": 1, "saltate": [], "voci": [],
                 "da_gradare": [{"match_id": 537186,
                                 "campi": {"risultato_reale": "1-2", "esito": "❌"}}]}):
            d = RG.diagnosi_nomi(istantanea="2026-09-21-pre-grading")
        self.assertTrue(d["coerente"], d)
        self.assertEqual(0, d["diverse"])

    def test_istantanea_assente_ferma_tutto(self):
        with mock.patch.object(rs, "upstash_snapshot_read", return_value=None):
            r = RG.ripara_nomi(istantanea="2026-09-21-pre-grading", scrivi=True)
        self.assertFalse(r["ok"])
        self.assertIn("non leggibile", r["motivo"])

    def test_la_riparazione_denuncia_una_riga_diversa_dall_atteso(self):
        prima, dopo = self._coppia()
        sbagliata = dict(dopo, prob_sicuro=12.0)
        with mock.patch.object(rs, "upstash_snapshot_read", return_value=[prima]), \
             mock.patch.object(RG, "campi_grezzi",
                               return_value={"537186|top_mix||current": (RG.canon(prima), prima)}), \
             mock.patch.object(RG, "piano", return_value={"selezionate": 1, "saltate": [], "voci": [],
                 "da_gradare": [{"match_id": 537186,
                                 "campi": {"risultato_reale": "1-2", "esito": "❌"}}]}), \
             mock.patch.object(rs, "upstash_raw", return_value={"result": 1}), \
             mock.patch.object(rs, "upstash_rows", return_value=[sbagliata]):
            r = RG.ripara_nomi(istantanea="2026-09-21-pre-grading", scrivi=True)
        self.assertFalse(r["ok"])
        self.assertTrue(any("contenuto diverso" in e for e in r["errori"]))


class TestIstantaneeDeiCampi(unittest.TestCase):
    """Che cosa dicono le fotografie dell'hash, e quali nomi sono stati tolti dopo."""

    @staticmethod
    def _corpo(dati):
        return {"result": RG.json.dumps(dati, ensure_ascii=False)}

    def test_elenca_istantanee_distingue_righe_e_campi(self):
        righe = [_riga(1), _riga(2, home="Roma", away="Lazio")]
        campi = {rs.field_of(_riga(1)): RG.canon(_riga(1)),
                 "1|top_mix||current": RG.canon(_riga(1)),
                 rs.field_of(righe[1]): RG.canon(righe[1])}
        risposte = [{"result": ["sm:registro:snapshot:2026-09-21-pre-grading",
                                "sm:registro:snapshot:2026-09-21-pre-pulizia-campi"]},
                    self._corpo(righe), self._corpo(campi)]
        with mock.patch.object(rs, "upstash_raw", side_effect=risposte):
            elenco = RG.elenca_istantanee()
        per_chiave = {v["chiave"]: v for v in elenco}
        self.assertEqual("righe", per_chiave["2026-09-21-pre-grading"]["tipo"])
        self.assertIsNone(per_chiave["2026-09-21-pre-grading"]["extra"])
        self.assertEqual(2, per_chiave["2026-09-21-pre-grading"]["righe_logiche"])
        self.assertEqual("campi", per_chiave["2026-09-21-pre-pulizia-campi"]["tipo"])
        self.assertEqual(3, per_chiave["2026-09-21-pre-pulizia-campi"]["campi"])
        self.assertEqual(2, per_chiave["2026-09-21-pre-pulizia-campi"]["righe_logiche"])
        self.assertEqual(1, per_chiave["2026-09-21-pre-pulizia-campi"]["extra"])

    def test_elenca_campi_extra_dice_quali_esistono_ancora(self):
        riga = _riga(1)
        campi = {rs.field_of(riga): RG.canon(riga),
                 "1|top_mix||current": RG.canon(riga)}
        with mock.patch.object(rs, "upstash_raw", return_value=self._corpo(campi)), \
             mock.patch.object(RG, "campi_grezzi",
                               return_value={rs.field_of(riga): (RG.canon(riga), riga)}):
            d = RG.elenca_campi_extra("2026-09-21-pre-pulizia-campi")
        self.assertEqual(1, len(d["extra"]))
        self.assertFalse(d["extra"][0]["ancora_presente"])
        self.assertEqual(1, d["extra_non_piu_presenti"])
        self.assertEqual("1|top_mix||current", d["extra"][0]["nome"])
        self.assertEqual("Milan - Cagliari", f"{d['extra'][0]['home']} - {d['extra'][0]['away']}")

    def test_un_nome_ancora_presente_non_si_dichiara_tolto(self):
        riga = _riga(1)
        campi = {rs.field_of(riga): RG.canon(riga), "1|top_mix||current": RG.canon(riga)}
        with mock.patch.object(rs, "upstash_raw", return_value=self._corpo(campi)), \
             mock.patch.object(RG, "campi_grezzi", return_value=dict(campi)):
            d = RG.elenca_campi_extra("2026-09-21-pre-pulizia-campi")
        self.assertTrue(d["extra"][0]["ancora_presente"])
        self.assertEqual(0, d["extra_non_piu_presenti"])
        self.assertEqual(1, d["extra_ancora_presenti"])

    def test_la_chiave_si_puo_indicare_col_solo_nome_del_giorno(self):
        riga = _riga(1)
        campi = {rs.field_of(riga): RG.canon(riga), "1|top_mix||current": RG.canon(riga)}
        with mock.patch.object(rs, "upstash_raw", return_value=self._corpo(campi)) as raw, \
             mock.patch.object(RG, "campi_grezzi", return_value={}):
            d = RG.elenca_campi_extra("2026-09-21-pre-pulizia-campi")
        self.assertEqual("sm:registro:snapshot:2026-09-21-pre-pulizia-campi", raw.call_args[0][0][1])
        self.assertTrue(d["esiste"])

    def test_istantanea_assente_non_inventa_elenchi(self):
        with mock.patch.object(rs, "upstash_raw", return_value={"result": None}):
            d = RG.elenca_campi_extra("2026-09-21-pre-pulizia-campi")
        self.assertFalse(d["esiste"])
        self.assertEqual([], d["extra"])

    def test_istantanea_di_righe_non_e_una_foto_di_campi(self):
        with mock.patch.object(rs, "upstash_raw", return_value=self._corpo([_riga(1)])):
            d = RG.elenca_campi_extra("2026-09-20")
        self.assertTrue(d["esiste"])
        self.assertTrue(d.get("non_e_una_foto_di_campi"))
        self.assertEqual([], d["extra"])


class TestIngressiEProtezioni(unittest.TestCase):
    """Registro illeggibile, serrature, idempotenza: nessuna scrittura per sbaglio."""

    RIGHE = [_riga(537186)]

    def test_senza_registro_esce_due(self):
        with mock.patch.object(rs, "load_rows", return_value=(None, "nessuno")):
            self.assertEqual(2, RG.main([]))

    def test_scrivi_senza_conferma_non_scrive(self):
        with mock.patch.object(rs, "load_rows", return_value=(self.RIGHE, rs.BACKEND_UPSTASH)), \
             mock.patch.object(RG, "piano", return_value={"selezionate": 1, "da_gradare": [
                 {"match_id": 537186, "campi": {"risultato_reale": "1-2", "esito": "❌"}}],
                 "saltate": [], "voci": []}), \
             mock.patch.object(rs, "save_rows") as salva:
            self.assertEqual(3, RG.main(["--scrivi"]))
        salva.assert_not_called()

    def test_attesi_diversi_ferma_tutto(self):
        with mock.patch.object(rs, "load_rows", return_value=(self.RIGHE, rs.BACKEND_UPSTASH)), \
             mock.patch.object(RG, "piano", return_value={"selezionate": 1, "da_gradare": [
                 {"match_id": 537186, "campi": {"risultato_reale": "1-2", "esito": "❌"}}],
                 "saltate": [], "voci": []}), \
             mock.patch.object(rs, "save_rows") as salva:
            self.assertEqual(3, RG.main(["--scrivi", "--conferma", "--attesi", "10"]))
        salva.assert_not_called()

    def test_niente_da_gradare_non_scrive(self):
        with mock.patch.object(rs, "load_rows", return_value=(self.RIGHE, rs.BACKEND_UPSTASH)), \
             mock.patch.object(RG, "piano", return_value={"selezionate": 1, "da_gradare": [],
                                                          "saltate": [], "voci": []}), \
             mock.patch.object(rs, "save_rows") as salva, \
             mock.patch.object(rs, "upstash_snapshot") as snap:
            self.assertEqual(0, RG.main(["--scrivi", "--conferma"]))
        salva.assert_not_called()
        snap.assert_not_called()

    def test_istantanea_prima_della_scrittura_e_verifica_dopo(self):
        scalate = {"n": 0}

        def _save(righe, **kw):
            scalate["n"] += 1
            return {"righe_scritte": 1, "righe_saltate": 1}

        with mock.patch.object(rs, "load_rows", return_value=(self.RIGHE, rs.BACKEND_UPSTASH)), \
             mock.patch.object(rs, "upstash_raw", return_value={"result": None}), \
             mock.patch.object(rs, "upstash_snapshot",
                               return_value={"chiave": "k", "righe": 1, "byte": 10}) as snap, \
             mock.patch.object(rs, "save_rows", side_effect=_save) as salva, \
             mock.patch.object(rs, "upstash_rows", return_value=[
                 dict(self.RIGHE[0], risultato_reale="1-2", esito="❌")]), \
             mock.patch.object(RG, "piano", return_value={"selezionate": 1, "da_gradare": [
                 {"match_id": 537186, "campi": {"risultato_reale": "1-2", "esito": "❌"}}],
                 "saltate": [], "voci": []}):
            self.assertEqual(0, RG.main(["--scrivi", "--conferma", "--attesi", "1"]))
        snap.assert_called_once()
        self.assertTrue(str(snap.call_args[0][0]).endswith("-pre-grading"))
        salva.assert_called_once()
        self.assertEqual(1, scalate["n"])

    def test_backend_non_upstash_non_si_scrive(self):
        with mock.patch.object(rs, "load_rows", return_value=(self.RIGHE, rs.BACKEND_JSONBIN)), \
             mock.patch.object(rs, "save_rows") as salva:
            self.assertEqual(2, RG.main(["--scrivi", "--conferma"]))
        salva.assert_not_called()

    def test_chiave_istantanea_libera_non_sovrascrive(self):
        with mock.patch.object(rs, "upstash_raw", side_effect=[{"result": "occupata"},
                                                               {"result": "occupata"},
                                                               {"result": None}]) as raw:
            self.assertEqual("2026-09-21-pre-grading-3",
                             RG.chiave_istantanea_libera("2026-09-21", True))
        self.assertEqual(3, raw.call_count)
        with mock.patch.object(rs, "upstash_raw") as raw2:
            self.assertEqual("2026-09-21-pre-grading",
                             RG.chiave_istantanea_libera("2026-09-21", False))
        raw2.assert_not_called()

    def test_referto_compatto_con_i_prefissi(self):
        p = {"selezionate": 1, "da_gradare": [{"data": "24/05/2026 20:45", "home": "Milan",
                                               "away": "Cagliari", "campionato": "Serie A",
                                               "mercato": "1", "risultato": "1-2", "esito": "❌",
                                               "fonti": ["api", "archivio"],
                                               "salvato_il": "23/05/2026 08:19",
                                               "variante": "legacy", "stagione": "2025/2026",
                                               "match_id": 537186}],
             "saltate": [{"data": "x", "home": "Roma", "away": "Lazio", "campionato": "Serie A",
                          "mercato": "1", "saltata": "nessuna fonte", "stagione": "2025/2026",
                          "match_id": 9}],
             "voci": [{"data": "24/05/2026 20:45", "home": "Milan", "away": "Cagliari",
                       "campionato": "Serie A", "mercato": "1", "risultato": "1-2", "esito": "❌",
                       "fonti": ["api"], "salvato_il": "23/05/2026 08:19", "variante": "legacy",
                       "stagione": "2025/2026", "match_id": 537186, "campi": {"esito": "❌"}},
                      {"data": "x", "home": "Roma", "away": "Lazio", "campionato": "Serie A",
                       "mercato": "1", "saltata": "nessuna fonte", "stagione": "2025/2026",
                       "match_id": 9, "campi": None}]}
        testo = "\n".join(RG.righe_compatti(p))
        self.assertIn("SELEZIONE| righe in attesa", testo)
        self.assertIn("GRADING| 24/05/2026 20:45", testo)
        self.assertIn("SALTATA| x", testo)


if __name__ == "__main__":
    unittest.main()
