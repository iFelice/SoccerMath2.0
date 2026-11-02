"""Controlli sui DATI VERI (gruppo 2 del censimento del referto giornata 7).

Perche' questo file esiste
--------------------------
Il censimento ``audit/results/referto_fixture_apptest_giornata7_2026-11-02.md``
(punto 4) divide i test che leggono dati vivi in due gruppi:

* **gruppo 1** - test del CODICE che leggono per sbaglio dati che cambiano: si
  rendono indipendenti con una copia congelata e un orologio fermo (fatto, vedi
  ``test_snapshot_congelato.py``);
* **gruppo 2** - controlli sui DATI VERI che devono RESTARE sui dati veri:
  voci 4, 6, 7, 9, 10. Questi non si congelano. Si tolgono dalla suite completa
  (dove sono saltati con un motivo esplicito) e girano nel workflow
  ``.github/workflows/controlli_dati.yml``, ogni giorno dopo ``live_odds.yml`` e
  dopo ``update_database.yml``.

Le voci 4 e 10 hanno gia' un test che fa il controllo: qui si riusano le STESSE
funzioni di produzione e le stesse condizioni, aggiungendo soltanto il
``::error file=...,line=...::`` che dice a colpo d'occhio QUALE dato ha il
problema (squadra, partita, nome, file) - e' la richiesta della commessa: «segnala
in modo chiaro nel log quale dato ha il problema». Le voci 6, 7 e 9 non avevano
un posto dove un dato rotto si vedeva come DATO e non come test rosso: qui il
controllo e' esplicito, con il nome della squadra / della partita / del file.

Regole
------
* sola lettura: nessun file scritto, nessuna chiamata di rete, nessun commit;
* nessuna scrittura nel Registro (pytest gira con il backend in memoria e senza
  credenziali, e qui non si chiama nessuna funzione di scrittura);
* i test si eseguono SOLO con ``SM_CONTROLLI_DATI=1`` (il workflow lo imposta):
  senza la variabile la classe e' saltata, cosi' la suite completa continua a
  girare esattamente come prima.

Uso:
    SM_CONTROLLI_DATI=1 python -m pytest -q SoccerMath/test_controlli_dati.py -rs
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(REPO_ROOT, "audit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config  # noqa: E402
import market_odds as mo  # noqa: E402
import season_rosters as SR  # noqa: E402
import update_xg  # noqa: E402
from team_aliases import clean_name  # noqa: E402
from team_names import resolve_team_name  # noqa: E402

DB_DIR = Path(config.DATABASE_DIR)

LEGHE = ("Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1")

#: I file dell'archivio xG e delle medie xG, per lega (stessi nomi del
#: ``audit/test_ng_regression.py``: sono quelli che scrivono i workflow).
ARCH_FILES = {
    "Serie A": "xG archivio serie A.json",
    "Premier League": "xG archivio premier league.json",
    "La Liga": "xG archivio la liga.json",
    "Bundesliga": "xG archivio bundesliga.json",
    "Ligue 1": "xG archivio ligue 1.json",
}
XG_FILES = {
    "Serie A": "xg_serie_a.json",
    "Premier League": "xg_premier_league.json",
    "La Liga": "xg_la_liga.json",
    "Bundesliga": "xg_bundesliga.json",
    "Ligue 1": "xg_ligue_1.json",
}
LIVE_PREFIX = {"Serie A": "SerieA", "Premier League": "Premier", "La Liga": "LaLiga",
               "Bundesliga": "Bundesliga", "Ligue 1": "Ligue1"}

#: La fonte quote (snapshot probe committato, non rinnovato dai workflow) e il
#: file delle quote vive (riscritto da ``live_odds.yml`` ogni giorno).
PROBE_DIR = Path(REPO_ROOT, "audit", "data", "live_odds_probe")
LIVE_ODDS = DB_DIR / mo.LIVE_ODDS_FILE

CONTROLLI_DATI = os.environ.get("SM_CONTROLLI_DATI") == "1"
MOTIVO = ("controllo sui DATI VERI del gruppo 2: gira in "
          ".github/workflows/controlli_dati.yml (SM_CONTROLLI_DATI=1)")


# ---------------------------------------------------------------------------
# segnalazione: ogni problema diventa una riga leggibile + un'annotazione
# ---------------------------------------------------------------------------
def errore(dove: str, messaggio: str, file: str = "", riga: int = 0) -> str:
    """Il testo di un problema, con l'indicazione di DOVE sta il dato.

    ``dove`` e' la descrizione umana («Serie A / SerieA_Live.csv: nome
    'Sassuolo' non riconosciuto»). Il testo NON viene stampato qui: stampare
    l'annotazione anche per i controlli che passano farebbe credere a un guasto
    che non c'e'. Ci pensa :meth:`_BaseDatiVeri._fallisci`, che la emette solo
    per i problemi veri, nella forma ``::error file=...::`` che GitHub mostra
    nel riepilogo del run.
    """
    posizione = f" [file={file}" + (f",riga={riga}" if riga else "") + "]" if file else ""
    return f"{dove}: {messaggio}{posizione}"


class _BaseDatiVeri(unittest.TestCase):
    """Dice a voce alta su quali file si sta lavorando (e che sono vivi)."""

    @classmethod
    def setUpClass(cls):
        print(f"\n[controlli_dati] database: {DB_DIR}")
        for nome in sorted(p.name for p in DB_DIR.iterdir() if p.is_file()):
            print(f"[controlli_dati]   {nome}: {p_size(DB_DIR / nome)}")
        print(f"[controlli_dati] ora UTC: {datetime.now(timezone.utc).isoformat()}")

    def _fallisci(self, problemi, titolo: str):
        """Segnala i problemi veri: una riga ``::error`` per ciascuno, poi fallisce."""
        if problemi:
            for problema in problemi:
                print(f"::error::{problema}")
            print(f"::error::{titolo}: {len(problemi)} dato/i da correggere")
            self.fail(f"{titolo}: {len(problemi)} dato/i da correggere\n  "
                      + "\n  ".join(problemi))

    def _nota(self, testo: str):
        """Riga informativa (verde): il controllo e' passato, si legge il valore."""
        print(f"[ok] {testo}")


def p_size(path: Path) -> str:
    try:
        return f"{path.stat().st_size} byte"
    except OSError:                                 # pragma: no cover
        return "assente"


# ---------------------------------------------------------------------------
# VOCE 4 - season_rosters: roster della stagione e date future nei CSV vivi
# ---------------------------------------------------------------------------
@unittest.skipUnless(CONTROLLI_DATI, MOTIVO)
class TestVoce4RosterEDateFuture(_BaseDatiVeri):
    """Voce 4: ``SR.validate_current_rosters()`` e ``SR.validate_live_csvs()``.

    Stesso chiamante del workflow ``update_database``
    (``python season_rosters.py --check``) e stesso orologio: UTC di adesso.
    """

    def test_roster_della_stagione_corrente(self):
        adesso = datetime.now(timezone.utc)
        stagione = config.get_current_season_start_year()
        self._nota(f"voce 4 - roster: stagione {stagione}, orologio {adesso.isoformat()}")
        errori = SR.validate_current_rosters()
        self._fallisci([errore("roster", e) for e in errori],
                       "roster della stagione corrente non valido")

    def test_date_future_e_coppie_ripetute_nei_csv_vivi(self):
        adesso = datetime.now(timezone.utc)
        errori = SR.validate_live_csvs()
        self._fallisci(
            [errore("CSV vivi", e, file=str(LIVE_ODDS.parent)) for e in errori],
            f"CSV vivi non puliti (orologio {adesso.isoformat()})")


# ---------------------------------------------------------------------------
# VOCE 6 - la fonte quote (live_odds.json) contro il calendario di oggi
# ---------------------------------------------------------------------------
@unittest.skipUnless(CONTROLLI_DATI, MOTIVO)
class TestVoce6QuoteViveVersoSquadre(_BaseDatiVeri):
    """Voce 6: i nomi di ``live_odds.json`` devono essere tutti riconosciuti.

    Un nome nuovo (promossa, grafia corretta dalla fonte) senza alias in
    ``team_aliases.py`` faceva cadere ``TestCoperturaFileLive`` con un messaggio
    generico: qui il log dice il nome, la lega e il file.
    """

    def test_file_delle_quote_presente_e_leggibile(self):
        self.assertTrue(LIVE_ODDS.exists(), f"live_odds.json assente: {LIVE_ODDS}")
        payload = mo.carica_quote_live(str(LIVE_ODDS))
        self.assertIsNotNone(payload, f"live_odds.json non valido: {LIVE_ODDS}")
        self.assertGreater(int(payload.get("n_eventi") or 0), 0,
                           "live_odds.json senza eventi")
        eta = mo.ore_da(payload.get("generato_il"), datetime.now(timezone.utc))
        self._nota(f"voce 6 - live_odds.json: generato_il={payload.get('generato_il')}, "
                   f"eta'={eta:.1f} h, eventi={payload.get('n_eventi')}")

    def test_ogni_nome_della_fonte_e_riconosciuto(self):
        payload = mo.carica_quote_live(str(LIVE_ODDS))
        if payload is None:
            self.skipTest("live_odds.json assente o non valido (lo dice il test qui sopra)")
        sconosciuti = []
        for evento in mo.eventi_quote(payload):
            for ruolo in ("home_team", "away_team"):
                nome = evento.get(ruolo)
                res = resolve_team_name(nome)
                if not res.mapped:
                    sconosciuti.append(errore(
                        f"live_odds.json / {evento.get('lega')}",
                        f"nome {nome!r} non riconosciuto (pulito: {res.canonical!r}); "
                        "aggiungerlo in SoccerMath/team_aliases.py",
                        file="SoccerMath/database/live_odds.json"))
        self._fallisci(sorted(set(sconosciuti)),
                       "nomi della fonte quote non riconosciuti")

    def test_ogni_evento_e_indicizzato(self):
        payload = mo.carica_quote_live(str(LIVE_ODDS))
        if payload is None:
            self.skipTest("live_odds.json assente o non valido (lo dice il test sopra)")
        dati = mo.indice_partite(payload)
        problemi = []
        for voce in dati["non_abbinati"]:
            problemi.append(errore(
                f"live_odds.json / {voce.get('lega')}",
                f"partita {voce.get('home_raw')!r} - {voce.get('away_raw')!r} non "
                f"abbinata (casa riconosciuta: {voce.get('home_riconosciuto')}, "
                f"ospite riconosciuto: {voce.get('away_riconosciuto')})",
                file="SoccerMath/database/live_odds.json"))
        self._nota(f"voce 6 - eventi={dati['n_eventi']} indicizzati={dati['n_indicizzati']} "
                   f"non abbinati={len(dati['non_abbinati'])}")
        self._fallisci(problemi, "partite del file quote non abbinate")


# ---------------------------------------------------------------------------
# VOCE 7 - il calendario di oggi (i CSV vivi) contro la fonte quote
# ---------------------------------------------------------------------------
@unittest.skipUnless(CONTROLLI_DATI, MOTIVO)
class TestVoce7CalendarioDiOggi(_BaseDatiVeri):
    """Voce 7: le squadre dei soli ``*_Live.csv`` contro lo snapshot della fonte.

    E' il controllo di ``TestCoperturaCalendarioCorrente``, ma con il nome della
    squadra e il file nella riga di errore: se una squadra esce dal roster o un
    nome viene corretto, si vede subito quale.
    """

    def _squadre_dei_csv_vivi(self):
        """``{lega: {nome canonico: file}}`` dai ``*_Live.csv`` di oggi."""
        fuori = {}
        for lega in LEGHE:
            percorso = DB_DIR / f"{LIVE_PREFIX[lega]}_Live.csv"
            nomi = {}
            if percorso.exists():
                import csv
                with open(percorso, encoding="utf-8", newline="") as fh:
                    for riga in csv.DictReader(fh):
                        for colonna in ("HomeTeam", "AwayTeam"):
                            nome = (riga.get(colonna) or "").strip()
                            if nome:
                                nomi.setdefault(clean_name(nome), percorso.name)
            fuori[lega] = nomi
        return fuori

    def test_ogni_squadra_del_calendario_e_nel_roster(self):
        """Roster della stagione (``season_rosters.json``) contro i CSV vivi."""
        roster = SR.load_season_rosters()
        stagione = config.get_current_season_start_year()
        problemi = []
        for lega, nomi in self._squadre_dei_csv_vivi().items():
            attese = set(roster.get(lega, {}).get(stagione, []))
            for nome, file in sorted(nomi.items()):
                if nome not in attese:
                    problemi.append(errore(
                        f"{lega} / {file}",
                        f"squadra {nome!r} nei CSV vivi ma NON nel roster "
                        f"{stagione} ({len(attese)} squadre)",
                        file=f"SoccerMath/database/{file}"))
        self._fallisci(problemi, "squadre dei CSV vivi fuori dal roster")

    def test_ogni_partita_della_fonte_e_nel_calendario_di_oggi(self):
        """Gli eventi dello snapshot probe, contro i nomi dei CSV vivi di oggi."""
        eventi = []
        for nome in sorted(os.listdir(PROBE_DIR)):
            if not (nome.startswith("odds_api_soccer") and nome.endswith(".json")):
                continue
            with open(PROBE_DIR / nome, encoding="utf-8") as fh:
                snap = json.load(fh)
            for evento in snap.get("events") or []:
                eventi.append({**evento, "lega": snap.get("lega_progetto") or nome})
        self.assertGreaterEqual(len(eventi), 90,
                                f"snapshot della fonte quote incompleti: {len(eventi)} eventi")
        calendario = self._squadre_dei_csv_vivi()
        tutti = set().union(*(set(v) for v in calendario.values())) if calendario else set()
        problemi = []
        for evento in eventi:
            casa = resolve_team_name(evento.get("home_team")).canonical
            ospite = resolve_team_name(evento.get("away_team")).canonical
            for nome in (casa, ospite):
                if nome not in tutti:
                    problemi.append(errore(
                        f"calendario di oggi / {evento.get('lega')}",
                        f"{nome!r} (da {evento.get('home_team')!r} - "
                        f"{evento.get('away_team')!r}) non e' in nessun *_Live.csv",
                        file="SoccerMath/database"))
        self._nota(f"voce 7 - eventi dello snapshot={len(eventi)}, squadre nei CSV vivi={len(tutti)}")
        self._fallisci(sorted(set(problemi)),
                       "partite della fonte fuori dal calendario di oggi")


# ---------------------------------------------------------------------------
# VOCE 9 - abbinamento della prossima giornata (audit/live_odds_match.py)
# ---------------------------------------------------------------------------
@unittest.skipUnless(CONTROLLI_DATI, MOTIVO)
class TestVoce9AbbinamentoProssimaGiornata(_BaseDatiVeri):
    """Voce 9: ``build_payload()`` sui CSV vivi di oggi.

    I conteggi attesi sono quelli dello snapshot dell'08/10 (48 partite, 43
    abbinate col solo ``clean_name``, 48 col resolver): se il calendario di oggi
    non li riproduce piu', il log dice quale lega e quali partite.
    """

    ATTESO = {
        "Serie A": (10, 10, 10),
        "Premier League": (10, 10, 10),
        "La Liga": (10, 8, 10),
        "Bundesliga": (9, 7, 9),
        "Ligue 1": (9, 8, 9),
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import live_odds_match as LOM
        cls.payload = LOM.build_payload()

    def test_conteggi_per_lega(self):
        problemi = []
        for lega, (n, ok, ok_res) in self.ATTESO.items():
            v = self.payload["per_lega"].get(lega) or {}
            if not v.get("disponibile"):
                problemi.append(errore(f"audit/live_odds_match / {lega}",
                                       f"snapshot non disponibile: {v.get('motivo')}"))
                continue
            misurato = (v["n_prossima_giornata"], v["n_abbinate"], v["n_abbinate_resolver"])
            self._nota(f"voce 9 - {lega}: prossima giornata={misurato[0]}, "
                       f"abbinate clean_name={misurato[1]}, abbinate resolver={misurato[2]} "
                       f"(atteso {n}/{ok}/{ok_res})")
            for posizione, etichetta, atteso, ottenuto in (
                    (0, "partite della prossima giornata", n, misurato[0]),
                    (1, "abbinate col solo clean_name", ok, misurato[1]),
                    (2, "abbinate col resolver di produzione", ok_res, misurato[2])):
                if atteso != ottenuto:
                    righe = ", ".join(
                        f"{r.get('home_raw')} - {r.get('away_raw')}"
                        + ("" if r.get("match_ok_resolver") else " (NON abbinata)")
                        for r in v.get("righe") or [])[:600]
                    problemi.append(errore(
                        f"audit/live_odds_match / {lega}",
                        f"{etichetta}: attese {atteso}, misurate {ottenuto}. "
                        f"Partite: {righe}"))
        self._fallisci(problemi, "abbinamento della prossima giornata cambiato")

    def test_copertura_completa_col_resolver(self):
        problemi = []
        for lega, v in self.payload["per_lega"].items():
            for r in v.get("righe") or []:
                if not r.get("match_ok_resolver"):
                    problemi.append(errore(
                        f"audit/live_odds_match / {lega}",
                        f"partita {r.get('home_raw')!r} - {r.get('away_raw')!r} "
                        "non abbinata dal resolver di produzione"))
        totale = self.payload["totale"]
        self._nota(f"voce 9 - totale: prossima giornata={totale['n_prossima_giornata']}, "
                   f"abbinate={totale['n_abbinate']}, resolver={totale['n_abbinate_resolver']}")
        self._fallisci(problemi, "copertura del resolver non completa")


# ---------------------------------------------------------------------------
# VOCE 10 - nomi e lambda dei motori di produzione sui dati vivi
# ---------------------------------------------------------------------------
@unittest.skipUnless(CONTROLLI_DATI, MOTIVO)
class TestVoce10MotoriSuiDatiVivi(_BaseDatiVeri):
    """Voce 10: copertura dei nomi xG e assenza di NG estremi, sui dati veri.

    Sono le due asserzioni di ``audit/test_ng_regression.py`` (sezione 5 e 6),
    con l'elenco di CIÒ CHE NON TORNA: la squadra senza xG, la coppia con NG
    oltre il 95%.
    """

    def test_ogni_squadra_della_stagione_ha_gli_xg(self):
        problemi = []
        for lega in LEGHE:
            percorso = DB_DIR / ARCH_FILES[lega]
            if not percorso.exists():
                problemi.append(errore(f"{lega} / {percorso.name}", "archivio xG assente",
                                       file=f"SoccerMath/database/{percorso.name}"))
                continue
            with open(percorso, encoding="utf-8") as fh:
                archivio = json.load(fh)
            titoli = {m["home_team"] for m in archivio if m.get("season") == 2026}
            canonici = {update_xg.NAME_MAP.get(t, t) for t in titoli}
            live_path = DB_DIR / f"{LIVE_PREFIX[lega]}_Live.csv"
            if not live_path.exists():
                problemi.append(errore(f"{lega} / {live_path.name}", "CSV vivo assente",
                                       file=f"SoccerMath/database/{live_path.name}"))
                continue
            import pandas as pd
            live = pd.read_csv(live_path, low_memory=False)
            squadre = ({clean_name(t) for t in live["HomeTeam"]} |
                       {clean_name(t) for t in live["AwayTeam"]})
            self._nota(f"voce 10 - {lega}: squadre nel CSV vivo={len(squadre)}, "
                       f"nomi coperti dall'archivio xG={len(squadre & canonici)}")
            for mancante in sorted(squadre - canonici):
                problemi.append(errore(
                    f"{lega} / {live_path.name}",
                    f"squadra {mancante!r} senza xG nell'archivio "
                    f"({update_xg.NAME_MAP.get(mancante, 'nessuna voce in NAME_MAP')})",
                    file=f"SoccerMath/database/{live_path.name}"))
        self._fallisci(problemi, "squadre senza xG")

    def test_nessuna_coppia_con_ng_estremo(self):
        import app as app_mod
        problemi = []
        for lega in LEGHE:
            app_mod.get_league_engine.clear()
            motore = app_mod.get_league_engine(lega)
            if not motore:
                problemi.append(errore(f"{lega} / motore", "motore non disponibile "
                                       "(nessun CSV leggibile)"))
                continue
            stats, media_casa, media_ospiti, _ = motore
            squadre = sorted(stats)
            peggiore = ("", "", 0.0)
            for casa in squadre:
                for ospite in squadre:
                    if casa == ospite:
                        continue
                    ng = 1 - app_mod.get_full_poisson_two_heads(
                        stats[casa], stats[ospite], media_casa, media_ospiti)["gg"]
                    if ng > peggiore[2]:
                        peggiore = (casa, ospite, ng)
                    if ng > 0.95:
                        problemi.append(errore(
                            f"{lega} / motore",
                            f"NG={ng:.4f} per {casa}-{ospite} (soglia 95%)"))
            self._nota(f"voce 10 - {lega}: NG peggiore={peggiore[2]:.4f} "
                       f"({peggiore[0]}-{peggiore[1]}), squadre={len(squadre)}")
        self._fallisci(problemi, "NG estremi su coppie di squadre reali")


if __name__ == "__main__":
    unittest.main(verbosity=2)
