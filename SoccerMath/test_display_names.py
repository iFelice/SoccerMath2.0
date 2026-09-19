"""DISPLAY_NAME_MAP: nomi SOLO display, zero impatto su matching e numeri.

Il referto originale (``audit/results/giornata_nomi_e_date_matchday6.md``,
15/09, mai committato e non recuperabile) e' stato ricostruito dai dati
misurati nel repo; il referto rifatto vive in
``audit/results/display_name_map_referto.md`` (generato da
``audit/display_name_map_check.py``).

Qui si verifica, dal piu' piccolo al piu' grande:

1. ``TestInvariantiMappa`` -- le chiavi sono nomi canonici
   (``clean_name(chiave) == chiave``), i valori sono nomi non vuoti e
   DUE chiavi diverse non possono produrre lo stesso nome mostrato.
2. ``TestRisoluzioneFormeGrezze`` -- ogni forma grezza MISURATA
   (righe raw nei ``*_Live.csv`` 2026/27, alias documentati in
   ``TEAM_NAME_MAP``) atterra sul nome display atteso, qualunque
   variante (shortName, name lungo, forma accentata) arrivi dall'API.
3. ``TestPassThrough`` -- i nomi fuori mappa escono IMMUTATI: nessun
   fuzzy matching, nessun guess (comportamento pre-esistente).
4. ``TestMatchingIntatto`` -- ``clean_name``/``TEAM_NAME_MAP`` NON
   imparano nulla dai nomi display: il nome mostrato non e' una chiave
   di calcolo, e la catena del matching non importa mai questo modulo.
5. ``TestSelettoreNeutroSuiNomi`` -- ``seleziona_riga_top_mix`` con nomi
   grezzi vs nomi display: mercato_standard, prob, prob_val, poisson,
   elo ed elo_disponibile IDENTICI; cambia solo l'etichetta.
6. ``TestAnalisiRapidaRegistraDisplay`` -- ``analisi_rapida_giornata``
   gira due volte (display reale vs ``display_name`` ridotta a identita',
   cioe' il comportamento pre-cambio): le probabilita', i codici
   mercato_standard e gli id salvati coincidono; solo home/away e le
   etichette del pronostico cambiano, e SOLO per le squadre mappate.
7. ``TestGuardiaSorgente`` -- i 4 punti di applicazione (ultimi
   risultati, Top Mix, Analisi Rapida, card PARTITE) usano
   ``display_name`` SOLO per la visualizzazione: ogni punto di
   confronto/chiave (``team_stats.get(clean_name(...))``,
   ``predict_elo_probs``, ``blend_elo_into_1x2``, ``show_details``)
   riceve ancora il nome grezzo. Guardia di cablaggio sul sorgente,
   stesso stile di ``test_topmix_selector_parity.py``.

Esecuzione:
    python -m pytest SoccerMath/test_display_names.py -v
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _REPO_ROOT)

from display_names import DISPLAY_NAME_MAP, display_name  # noqa: E402
from team_aliases import (  # noqa: E402
    TEAM_NAME_MAP,
    UNDERSTAT_NAME_MAP,
    clean_name,
)

import app as prod_app  # noqa: E402

APP_PATH = os.path.join(_HERE, "app.py")
ALIASES_PATH = os.path.join(_HERE, "team_aliases.py")
CONFIG_PATH = os.path.join(_HERE, "config.py")
ELO_PATH = os.path.join(_HERE, "models", "elo_engine.py")


def _sorgente(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


# Forme grezze misurate (stagione 2026/27) -> nome display atteso.
# Fonti: righe raw nei *_Live.csv scritte prima degli alias, alias in
# TEAM_NAME_MAP, audit/results/schalke_bayern_921.json.
FORME_GREZZE_ATTESE = {
    # La Liga
    "Atleti": "Atletico Madrid",
    "Atletico Madrid": "Atletico Madrid",
    "Barça": "Barcelona",
    "Barcelona": "Barcelona",
    "Athletic": "Athletic Bilbao",
    "Athletic Bilbao": "Athletic Bilbao",
    "Santander": "Racing Santander",
    "Racing Santander": "Racing Santander",
    # Premier League
    "Brighton Hove": "Brighton",
    "Brighton and Hove Albion": "Brighton",
    "Brighton": "Brighton",
    "Nottingham": "Nottingham Forest",
    "Nott'm Forest": "Nottingham Forest",
    "Nottingham Forest": "Nottingham Forest",
    # Bundesliga
    "HSV": "Hamburg",
    "Hamburg": "Hamburg",
    "Schalke": "Schalke 04",
    "Schalke 04": "Schalke 04",
    "FC Schalke 04": "Schalke 04",
    "Bremen": "Werder Bremen",
    "Werder Bremen": "Werder Bremen",
    "Frankfurt": "Eintracht Frankfurt",
    "Eintracht Frankfurt": "Eintracht Frankfurt",
    "Ein Frankfurt": "Eintracht Frankfurt",
    "M'gladbach": "Borussia Mönchengladbach",
    "Borussia Mönchengladbach": "Borussia Mönchengladbach",
    # Ligue 1
    "Stade Rennais": "Rennes",
    "Stade Rennais FC": "Rennes",
    "Rennes": "Rennes",
    "Olympique Lyon": "Lyon",
    "Olympique Lyonnais": "Lyon",
    "Lyon": "Lyon",
    "Paris": "Paris FC",
    "Paris FC": "Paris FC",
}

# Titoli Understat ("Athletic Club", "Hamburger SV", "Borussia M.Gladbach")
# NON passano da clean_name (risolve solo gli alias delle API live): escono
# IMMUTATI dal pass-through. Corretto perche' ai 4 punti di display arrivano
# solo nomi football-data (misurato), e comunque sono gia' nomi leggibili.
FORME_UNDERSTAT_PASSTHROUGH = [
    "Athletic Club", "Hamburger SV", "Borussia M.Gladbach", "Paris Saint Germain",
]

# Nomi gia' corretti che devono uscire IMMUTATI (nessuna voce in mappa).
NOMI_IMMUTATI = [
    "Inter", "Milan", "Juventus", "Napoli", "Roma", "Lazio", "Fiorentina",
    "Atalanta", "Bologna", "Como", "Cagliari", "Genoa", "Lecce", "Monza",
    "Parma", "Sassuolo", "Torino", "Udinese", "Venezia", "Frosinone",
    "Arsenal", "Liverpool", "Man City", "Man United", "Newcastle",
    "Tottenham", "Chelsea", "Aston Villa", "West Ham", "Leeds United",
    "Coventry City", "Hull City", "Ipswich", "Sunderland", "Crystal Palace",
    "Everton", "Fulham", "Brentford", "Bournemouth",
    "Real Madrid", "Sevilla", "Valencia", "Villarreal", "Betis",
    "Real Betis", "Espanyol", "Espanol", "Getafe", "Osasuna", "Celta",
    "Alaves", "Alavés", "Málaga", "Rayo Vallecano", "Real Sociedad",
    "Sociedad", "Vallecano", "Levante", "Elche", "Girona", "Deportivo",
    "Bayern", "Bayern Munich", "Dortmund", "Borussia Dortmund", "Leverkusen",
    "Bayer 04 Leverkusen", "RB Leipzig", "Leipzig", "Stuttgart", "VfB Stuttgart",
    "Wolfsburg", "Mainz", "Augsburg", "Hoffenheim", "Freiburg", "Union Berlin",
    "Köln", "Elversberg", "SC Paderborn",
    "PSG", "Paris Saint-Germain", "Paris SG", "Marseille", "Monaco", "Lille",
    "Nice", "Lens", "Strasbourg", "Toulouse", "Brest", "Nantes", "Auxerre",
    "Angers", "Le Havre", "Lorient", "Metz", "Troyes", "Le Mans",
    # fallback impossibili
    "Team Mai Vista", "?",
]


class TestInvariantiMappa(unittest.TestCase):
    def test_chiavi_gia_canoniche(self):
        """Ogni chiave e' un nome canonico: clean_name(chiave) == chiave."""
        for k in DISPLAY_NAME_MAP:
            self.assertEqual(
                clean_name(k), k,
                f"la chiave {k!r} non e' canonica: clean_name(k) = {clean_name(k)!r}",
            )

    def test_valori_non_vuoti(self):
        for k, v in DISPLAY_NAME_MAP.items():
            self.assertIsInstance(v, str)
            self.assertTrue(v.strip(), f"valore vuoto per {k!r}")

    def test_valori_distinti(self):
        """Due squadre diverse non possono mostrare lo stesso nome."""
        vals = list(DISPLAY_NAME_MAP.values())
        self.assertEqual(len(vals), len(set(vals)),
                         "nomi display duplicati nella mappa")

    def test_mappa_copre_le_cinque_leghe(self):
        """Il referto riguarda tutte e 5 le leghe: la mappa deve avere voci
        per Premier, La Liga, Bundesliga e Ligue 1 (la Serie A 2026/27 non
        ne ha bisogno: 20 shortName gia' puliti, misurato nel referto)."""
        self.assertIn("Nott'm Forest", DISPLAY_NAME_MAP)      # Premier
        self.assertIn("Ath Madrid", DISPLAY_NAME_MAP)         # La Liga
        self.assertIn("M'gladbach", DISPLAY_NAME_MAP)         # Bundesliga
        self.assertIn("Paris", DISPLAY_NAME_MAP)              # Ligue 1


class TestRisoluzioneFormeGrezze(unittest.TestCase):
    def test_forme_misurate(self):
        for raw, atteso in FORME_GREZZE_ATTESE.items():
            self.assertEqual(display_name(raw), atteso,
                             f"display_name({raw!r}) != {atteso!r}")

    def test_forme_understat_passthrough(self):
        """I titoli Understat non sono alias delle API live: pass-through."""
        for raw in FORME_UNDERSTAT_PASSTHROUGH:
            self.assertEqual(display_name(raw), raw)

    def test_paris_fc_non_e_psg(self):
        """"Paris" (Paris FC) e "PSG" sono due club diversi: il display li
        deve tenere distinguibili (motivo della voce "Paris" -> "Paris FC")."""
        self.assertEqual(display_name("Paris"), "Paris FC")
        self.assertEqual(display_name("PSG"), "PSG")
        self.assertNotEqual(display_name("Paris"), display_name("PSG"))


class TestPassThrough(unittest.TestCase):
    def test_nomi_fuori_mappa_immutati(self):
        for n in NOMI_IMMUTATI:
            self.assertEqual(display_name(n), n,
                             f"display_name({n!r}) non deve cambiare questo nome")

    def test_vuoto_e_none(self):
        self.assertEqual(display_name(""), "")
        self.assertEqual(display_name(None), "")


class TestMatchingIntatto(unittest.TestCase):
    """Il nome display NON e' una chiave: clean_name non impara nulla."""

    def test_clean_name_non_esteso(self):
        # il display "Atletico Madrid" NON risolve ad "Ath Madrid": se
        # accadesse, qualcuno avrebbe messo il display nel matching.
        self.assertEqual(clean_name("Atletico Madrid"), "Atletico Madrid")
        self.assertEqual(clean_name("Atleti"), "Ath Madrid")
        self.assertEqual(clean_name("Barça"), "Barcelona")
        self.assertEqual(clean_name("Brighton Hove"), "Brighton")
        self.assertEqual(clean_name("HSV"), "Hamburg")
        self.assertEqual(clean_name("Paris FC"), "Paris")
        self.assertEqual(clean_name("Borussia Mönchengladbach"), "M'gladbach")

    def test_alias_del_calcolo_invariati(self):
        # campionatura delle voci usate dal motore: devono essere esattamente
        # quelle di prima del cambio (la mappa display non le tocca).
        for raw, canon in [
            ("Atleti", "Ath Madrid"),
            ("Athletic", "Ath Bilbao"),
            ("Barça", "Barcelona"),
            ("Nottingham", "Nott'm Forest"),
            ("Brighton Hove", "Brighton"),
            ("HSV", "Hamburg"),
            ("Köln", "Koln"),
            ("Schalke", "Schalke 04"),
            ("Bremen", "Werder Bremen"),
            ("Frankfurt", "Ein Frankfurt"),
            ("Stade Rennais", "Rennes"),
            ("Olympique Lyon", "Lyon"),
            ("Paris Saint-Germain", "PSG"),
        ]:
            self.assertEqual(TEAM_NAME_MAP.get(raw), canon)
        self.assertEqual(UNDERSTAT_NAME_MAP.get("Atletico Madrid"), "Ath Madrid")

    def test_la_catena_di_calcolo_non_importa_il_display(self):
        """team_aliases/config/elo_engine non consumano mai il layer display:
        e' la garanzia strutturale che il cambio e' solo UI."""
        for path in (ALIASES_PATH, CONFIG_PATH, ELO_PATH):
            src = _sorgente(path)
            self.assertNotIn("display_name", src,
                             f"{os.path.basename(path)} non deve usare display_name")
            self.assertNotIn("DISPLAY_NAME_MAP", src,
                             f"{os.path.basename(path)} non deve usare DISPLAY_NAME_MAP")


class TestSelettoreNeutroSuiNomi(unittest.TestCase):
    """seleziona_riga_top_mix: stessi numeri e stesso codice mercato con
    nome grezzo o display; cambia solo l'etichetta del mercato."""

    M_HOME = {"1": 0.62, "X": 0.22, "2": 0.16, "u25": 0.50, "gg": 0.55}
    ELO_HOME = {"1": 0.60, "X": 0.22, "2": 0.18}
    M_AWAY = {"1": 0.14, "X": 0.21, "2": 0.65, "u25": 0.48, "gg": 0.52}
    ELO_AWAY = {"1": 0.17, "X": 0.21, "2": 0.62}
    M_TOTALE = {"1": 0.33, "X": 0.30, "2": 0.37, "u25": 0.25, "gg": 0.50}

    CAMPI_NUMERICI = ("prob", "prob_val", "poisson", "elo", "elo_disponibile")

    def _confronta(self, m, elo, h_raw, a_raw, h_disp, a_disp):
        r_raw = prod_app.seleziona_riga_top_mix(m, elo, True, h_raw, a_raw)
        r_disp = prod_app.seleziona_riga_top_mix(m, elo, True, h_disp, a_disp)
        self.assertIsNotNone(r_raw)
        self.assertIsNotNone(r_disp)
        # codice mercato e numeri IDENTICI
        self.assertEqual(r_raw["mercato_standard"], r_disp["mercato_standard"])
        for campo in self.CAMPI_NUMERICI:
            self.assertEqual(r_raw[campo], r_disp[campo],
                             f"{campo} cambia tra nome grezzo e display")
        # l'etichetta e' la stessa a meno della sostituzione dei nomi
        attesa = (r_raw["market"]
                  .replace(h_raw, h_disp)
                  .replace(a_raw, a_disp))
        self.assertEqual(r_disp["market"], attesa)
        return r_raw, r_disp

    def test_vittoria_casa(self):
        r_raw, r_disp = self._confronta(
            self.M_HOME, self.ELO_HOME, "Atleti", "Barça", "Atletico Madrid", "Barcelona")
        self.assertEqual(r_raw["mercato_standard"], "1")
        self.assertEqual(r_disp["market"], "Vittoria Atletico Madrid")
        self.assertEqual(r_disp["mercato_standard"], "1")

    def test_vittoria_trasferta(self):
        r_raw, r_disp = self._confronta(
            self.M_AWAY, self.ELO_AWAY, "Brighton Hove", "Nottingham",
            "Brighton", "Nottingham Forest")
        self.assertEqual(r_raw["mercato_standard"], "2")
        self.assertEqual(r_disp["market"], "Vittoria Nottingham Forest")

    def test_mercato_senza_nomi_invariato(self):
        """Pareggio / Over / Under / GG / NG non contengono nomi squadra."""
        for m, elo in ((self.M_TOTALE, None),):
            r_raw = prod_app.seleziona_riga_top_mix(m, None, False, "Atleti", "Barça")
            r_disp = prod_app.seleziona_riga_top_mix(m, None, False,
                                                     "Atletico Madrid", "Barcelona")
            self.assertEqual(r_raw, r_disp,
                             "i mercati senza nomi squadra devono essere bit-identici")


class TestAnalisiRapidaRegistraDisplay(unittest.TestCase):
    """analisi_rapida_giornata: due giri (display reale vs display=identita'),
    cioe' prima/dopo il cambio. Le probabilita' e i codici salvati coincidono;
    cambiano solo i nomi mostrati/salvati, e solo per le squadre mappate."""

    MATCHES = [
        # (id, raw_home, rawAway) su tutte e 5 le leghe
        {"id": 900001, "matchday": 7,
         "utcDate": "2026-09-20T14:00:00Z",
         "homeTeam": {"shortName": "Atleti"}, "awayTeam": {"shortName": "Barça"}},
        {"id": 900002, "matchday": 7,
         "utcDate": "2026-09-20T14:00:00Z",
         "homeTeam": {"shortName": "Brighton Hove"}, "awayTeam": {"shortName": "Nottingham"}},
        {"id": 900003, "matchday": 7,
         "utcDate": "2026-09-20T14:00:00Z",
         "homeTeam": {"shortName": "HSV"}, "awayTeam": {"shortName": "Schalke"}},
        {"id": 900004, "matchday": 7,
         "utcDate": "2026-09-20T14:00:00Z",
         "homeTeam": {"shortName": "Stade Rennais"}, "awayTeam": {"shortName": "Olympique Lyon"}},
        {"id": 900005, "matchday": 7,
         "utcDate": "2026-09-20T14:00:00Z",
         "homeTeam": {"shortName": "Inter"}, "awayTeam": {"shortName": "Milan"}},
    ]

    TEAM_STATS = {
        "Ath Madrid": {"att": 1.45, "def": 0.80},
        "Barcelona": {"att": 1.40, "def": 0.85},
        "Brighton": {"att": 1.15, "def": 1.05},
        "Nott'm Forest": {"att": 1.05, "def": 1.10},
        "Hamburg": {"att": 0.95, "def": 1.20},
        "Schalke 04": {"att": 0.90, "def": 1.30},
        "Rennes": {"att": 1.10, "def": 1.00},
        "Lyon": {"att": 1.20, "def": 1.05},
        "Inter": {"att": 1.50, "def": 0.70},
        "Milan": {"att": 1.30, "def": 0.90},
    }

    def _gira(self, display_reale: bool):
        salvate = []
        def _cattura(match_id, h, a, camp, giornata, match_date, pron, top3, prob,
                     ris_attesi, **kw):
            salvate.append({
                "match_id": match_id, "home": h, "away": a, "camp": camp,
                "giornata": giornata, "match_date": match_date, "pron": pron,
                "top3": top3, "prob": prob, **kw,
            })
            return {"azione": "aggiunta"}
        with mock.patch.object(prod_app, "save_prediction_entry", side_effect=_cattura), \
             mock.patch.object(prod_app, "blend_elo_into_1x2",
                               side_effect=lambda m, h, a, camp: dict(m)):
            if display_reale:
                n = prod_app.analisi_rapida_giornata(
                    self.MATCHES, self.TEAM_STATS, 1.35, 1.15, "Serie A", {}, 7)
            else:
                with mock.patch.object(prod_app, "display_name", side_effect=lambda x: x):
                    n = prod_app.analisi_rapida_giornata(
                        self.MATCHES, self.TEAM_STATS, 1.35, 1.15, "Serie A", {}, 7)
        self.assertEqual(n, len(self.MATCHES))
        return {r["match_id"]: r for r in salvate}

    def test_stessi_numeri_solo_nomi_diversi(self):
        con_display = self._gira(display_reale=True)
        senza_display = self._gira(display_reale=False)
        self.assertEqual(set(con_display), set(sezza := senza_display))
        mappa_nomi = {
            "Atleti": "Atletico Madrid", "Barça": "Barcelona",
            "Brighton Hove": "Brighton", "Nottingham": "Nottingham Forest",
            "HSV": "Hamburg", "Schalke": "Schalke 04",
            "Stade Rennais": "Rennes", "Olympique Lyon": "Lyon",
            "Inter": "Inter", "Milan": "Milan",
        }
        for mid, dopo in con_display.items():
            prima = senza_display[mid]
            # identico: tutto quello che non e' nome
            for campo in ("prob", "prob_poisson", "mercato_standard",
                          "origin", "giornata", "match_id"):
                self.assertEqual(prima[campo], dopo[campo],
                                 f"{campo} cambia per match {mid}")
            # i nomi salvati sono quelli display
            self.assertEqual(dopo["home"], mappa_nomi[prima["home"]])
            self.assertEqual(dopo["away"], mappa_nomi[prima["away"]])
            # il pronostico cambia SOLO nella sostituzione dei nomi squadra
            self.assertEqual(
                dopo["pron"],
                prima["pron"].replace(prima["home"], dopo["home"])
                              .replace(prima["away"], dopo["away"]),
            )
            self.assertEqual(
                dopo["match_date"], prima["match_date"])
            # i top3 hanno gli stessi numeri, nello stesso ordine
            self.assertEqual([t.split(" - ")[-1] for t in prima["top3"]],
                             [t.split(" - ")[-1] for t in dopo["top3"]])

    def test_serie_a_non_toccata(self):
        """Inter-Milan: nessuna voce in mappa, record byte-identico."""
        con_display = self._gira(display_reale=True)
        senza_display = self._gira(display_reale=False)
        self.assertEqual(con_display[900005], senza_display[900005])


class TestGuardiaSorgente(unittest.TestCase):
    """I 4 punti di applicazione usano display_name SOLO in visualizzazione;
    ogni punto di confronto/chiave resta sul nome grezzo."""

    def setUp(self):
        self.src = _sorgente(APP_PATH)

    def test_import_presente(self):
        self.assertIn("from display_names import display_name", self.src)

    def test_punto_ultimi_risultati(self):
        self.assertIn("risultati.append(f\"{display_name(match['homeTeam'].get('shortName','?'))}",
                      self.src)

    def test_punto_top_mix(self):
        # il nome mostrato/salvato passa da h_disp/a_disp...
        self.assertIn("h_disp, a_disp = display_name(h), display_name(a)", self.src)
        self.assertIn("seleziona_riga_top_mix(m_poisson, elo_probs, elo_disponibile, h_disp, a_disp)",
                      self.src)
        self.assertIn('"home": h_disp, "away": a_disp', self.src)
        # ...ma le chiavi restano sul grezzo
        self.assertIn('h_s = team_stats.get(clean_name(h), {"att": 1.0, "def": 1.0})', self.src)
        self.assertIn("predict_elo_probs(h, a, league)", self.src)

    def test_punto_analisi_rapida(self):
        self.assertIn('mercati = {f"Vittoria {h_disp}": m["1"]', self.src)
        self.assertIn("save_prediction_entry(m_id, h_disp, a_disp,", self.src)
        # chiavi sul grezzo
        self.assertIn('team_stats.get(clean_name(h), {"att": 1.0, "def": 1.0}), team_stats.get(clean_name(a), {"att": 1.0, "def": 1.0})',
                      self.src)
        self.assertIn("blend_elo_into_1x2(m, h, a, camp_sel)", self.src)

    def test_punto_card_partite(self):
        self.assertIn("{display_name(h_api)}<br>{display_name(a_api)}", self.src)
        # chiavi sul grezzo
        self.assertIn('h_s = team_stats.get(clean_name(h_api), {"att": 1.0, "def": 1.0})', self.src)
        self.assertIn("blend_elo_into_1x2(m_poisson, h_api, a_api, camp_sel)", self.src)
        # show_details riceve il grezzo: dentro fa matching su live_data/classifica
        self.assertIn("args=(h_api, a_api, m, m_poisson, camp_sel, g_sel)", self.src)

    def test_display_name_usato_solo_nei_4_punti(self):
        """Nessuna ottava chiamata nascosta: 2 (ultimi risultati) + 2 (Top Mix)
        + 2 (Analisi Rapida) + 2 (card PARTITE) = 8 usate come chiamata."""
        self.assertEqual(self.src.count("display_name("), 8,
                         "numero inatteso di chiamate display_name in app.py")


if __name__ == "__main__":
    unittest.main()
