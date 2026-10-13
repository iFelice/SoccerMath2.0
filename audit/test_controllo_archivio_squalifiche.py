"""Test offline del controllo «Nessun file dell'archivio nel repository».

Il controllo sta DENTRO il workflow ``.github/workflows/audit_squalifiche.yml``
(step ``Nessun file dell'archivio nel repository``): questo test lo ESTRAE dal
file YAML (senza dipendenze: lettura per indentazione) e lo esegue davvero, con
``bash -e``, dentro un repository git temporaneo costruito come quello reale.

Perche' esiste. Il run 38393593454 (2026-10-13, primo lancio manuale della
sonda squalifiche) aveva tutti gli step verdi fino a questo, che falliva con::

    Error: audit/output e' tracciato: l'archivio non deve entrare nel repository

Il controllo usava ``git ls-files --error-unmatch audit/output``, che risponde
"si'" per QUALUNQUE file tracciato sotto ``audit/output/``: nel repository ce ne
sono 18, committati dalla PR #34 (2026-10-06, audit economici: log e CSV come
``audit/output/ev_pooled.csv`` o ``audit/output/reruns/*.log``) e senza alcun
legame con l'archivio ``player_match``. Un falso positivo: l'archivio non era
entrato nel repository, il referto non e' stato committato e la sonda e' risultata
fallita pur avendo misurato tutto.

Cosa verifica questo test, in parole povere:

* il controllo ESTRATTO dal workflow passa quando sotto ``audit/output/`` ci
  sono file tracciati PREESISTENTI e non correlati (il caso della PR #34) e
  l'archivio appena scaricato resta non versionato;
* FALLISCE se un ``player_match_*.json`` finisce nell'indice (staged), in
  qualunque cartella;
* FALLISCE se un file della cartella scaricata
  (``audit/output/ppda-player-verify-*/``) finisce nell'indice, anche se non si
  chiama ``player_match_*.json``;
* FALLISCE se la cartella scaricata non esiste o non contiene archivi: il
  controllo non deve poter passare "perche' non c'era niente da trovare";
* il referto ``audit/results/sonda_squalifiche.md`` modificato dalla sonda e'
  ammesso (e' l'unico file che il workflow committa);
* una modifica dentro ``SoccerMath/`` resta un errore;
* il VECCHIO controllo (``git ls-files --error-unmatch audit/output``) sullo
  stesso repository temporaneo risponde "tracciato": la prova che il falso
  positivo era del controllo, non dei dati.

Nessuna rete, nessun secret, nessun archivio vero: i ``player_match_*.json`` del
repository temporaneo sono finti e servono solo a provare l'indice di git.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PERCORSO_WORKFLOW = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".github", "workflows", "audit_squalifiche.yml")
NOME_STEP = "Nessun file dell'archivio nel repository"
RUN_ID = "37917985080"
CARTELLA_SCARICATA = f"audit/output/ppda-player-verify-{RUN_ID}"
# Gli stessi nomi dei file tracciati dalla PR #34 (qui con contenuto finto).
PREESISTENTI = (
    "audit/output/ev_pooled.csv",
    "audit/output/ev_recalculation.json",
    "audit/output/reruns/status.txt",
)
ARCHIVI = (
    f"{CARTELLA_SCARICATA}/database/player_match_EPL.json",
    f"{CARTELLA_SCARICATA}/database/player_match_Serie_A.json",
)
ALTRO_FILE_SCARICATO = f"{CARTELLA_SCARICATA}/reports/acquisizione.json"
REFERTO = "audit/results/sonda_squalifiche.md"


def estrai_script_del_controllo(percorso: str = PERCORSO_WORKFLOW,
                                nome_step: str = NOME_STEP) -> str:
    """Lo script ``run:`` dello step, letto dal workflow per indentazione.

    Nessuna dipendenza esterna (niente PyYAML): si cerca la riga dello step e si
    prende il blocco letterale ``run: |`` che segue, de-indentato. Se lo step non
    c'e' piu' il test lo dice invece di passare in silenzio.
    """
    with open(percorso, encoding="utf-8") as fh:
        righe = fh.read().splitlines()

    indice_step = None
    for numero, riga in enumerate(righe):
        if riga.strip() == f"- name: {nome_step}":
            indice_step = numero
            break
    if indice_step is None:
        raise AssertionError(
            f"step {nome_step!r} non trovato in {percorso}: il controllo e' stato "
            f"rinominato o rimosso, questo test non sta piu' provando niente")

    indentazione_step = len(righe[indice_step]) - len(righe[indice_step].lstrip())
    indice_run = None
    for numero in range(indice_step + 1, len(righe)):
        riga = righe[numero]
        if not riga.strip():
            continue
        indentazione = len(riga) - len(riga.lstrip())
        if indentazione <= indentazione_step and riga.strip().startswith("- "):
            break                                    # step successivo: niente run
        if riga.strip() == "run: |":
            indice_run = numero
            break
    if indice_run is None:
        raise AssertionError(f"lo step {nome_step!r} non ha un blocco 'run: |'")

    indentazione_run = len(righe[indice_run]) - len(righe[indice_run].lstrip())
    corpo = []
    for riga in righe[indice_run + 1:]:
        if riga.strip() and (len(riga) - len(riga.lstrip())) <= indentazione_run:
            break                                    # fine del blocco letterale
        corpo.append(riga[indentazione_run + 2:] if riga.strip() else "")
    script = "\n".join(corpo).strip("\n")
    if not script.strip():
        raise AssertionError(f"lo step {nome_step!r} ha un blocco 'run:' vuoto")
    if "${{" in script:
        raise AssertionError(
            "lo script del controllo contiene un'espressione ${{ }} di GitHub: "
            "il test non sa come sostituirla, va resa una variabile d'ambiente")
    return script


def righe_di_codice(script: str) -> list[str]:
    """Le righe eseguite dello script: via i commenti e le righe vuote."""
    return [riga.strip() for riga in script.splitlines()
            if riga.strip() and not riga.strip().startswith("#")]


class RepositoryTemporaneo:
    """Un repository git costruito come quello del workflow, in una cartella a parte."""

    def __init__(self) -> None:
        self.radice = tempfile.mkdtemp(prefix="sonda-squalifiche-")
        self.script = os.path.join(self.radice, "controllo.sh")
        self.repo = os.path.join(self.radice, "repo")
        os.makedirs(self.repo)
        with open(self.script, "w", encoding="utf-8") as fh:
            fh.write(estrai_script_del_controllo())

    def chiudi(self) -> None:
        shutil.rmtree(self.radice, ignore_errors=True)

    # -- costruzione del repository ----------------------------------------
    def _git(self, *argomenti: str) -> subprocess.CompletedProcess:
        ambiente = dict(os.environ)
        ambiente["GIT_CONFIG_GLOBAL"] = os.devnull
        ambiente["GIT_CONFIG_SYSTEM"] = os.devnull
        ambiente["HOME"] = self.radice
        return subprocess.run(("git", *argomenti), cwd=self.repo, env=ambiente,
                              capture_output=True, text=True)

    def prepara(self) -> None:
        """Stato iniziale: quello del checkout DOPO il download dell'archivio."""
        for comando in (
            ("init", "-q"),
            ("config", "user.name", "sonda-squalifiche-test"),
            ("config", "user.email", "test@example.invalid"),
            ("config", "commit.gpgsign", "false"),
            ("config", "core.autocrlf", "false"),
        ):
            esito = self._git(*comando)
            if esito.returncode != 0:
                raise AssertionError(f"git {comando}: {esito.stderr.strip()}")

        self.scrivi(".gitignore", "audit/output/\n")
        self.scrivi("SoccerMath/database/squadre.csv", "squadra\nArsenal\n")
        # I 18 file della PR #34 qui sono 3: tracciati PUR essendo audit/output/
        # in .gitignore, esattamente come nel repository vero (git add -f).
        for percorso in PREESISTENTI:
            self.scrivi(percorso, "contenuto preesistente, non correlato\n")
        # Il referto e' TRACCIATO nel repository vero (la sonda lo riscrive ad
        # ogni run): qui va committato, altrimenti git status mostrerebbe la
        # cartella "?? audit/results/" e il test non somiglierebbe al caso reale.
        self.scrivi(REFERTO, "# Sonda squalifiche\n\nesito: referto precedente\n")
        self._git("add", "-f", ".gitignore", "SoccerMath/database/squadre.csv",
                  REFERTO, *PREESISTENTI)
        self._git("commit", "-q", "-m", "stato iniziale (come dopo la PR #34)")

        # L'archivio scaricato dal workflow: ignorato, quindi NON tracciato.
        for percorso in ARCHIVI:
            self.scrivi(percorso, '{"finto": true}\n')
        self.scrivi(ALTRO_FILE_SCARICATO, '{"finto": true}\n')
        # La sonda ha appena riscritto il referto: l'unico file da committare.
        self.scrivi(REFERTO, "# Sonda squalifiche\n\nesito: prova\n")

    def scrivi(self, percorso_relativo: str, contenuto: str) -> str:
        percorso = os.path.join(self.repo, percorso_relativo)
        os.makedirs(os.path.dirname(percorso), exist_ok=True)
        with open(percorso, "w", encoding="utf-8") as fh:
            fh.write(contenuto)
        return percorso

    def rimuovi(self, percorso_relativo: str) -> None:
        shutil.rmtree(os.path.join(self.repo, percorso_relativo), ignore_errors=True)

    def staged(self, *percorsi: str) -> None:
        esito = self._git("add", "-f", *percorsi)
        if esito.returncode != 0:
            raise AssertionError(f"git add: {esito.stderr.strip()}")

    # -- esecuzione del controllo ------------------------------------------
    def esegui_controllo(self, run_id: str = RUN_ID) -> subprocess.CompletedProcess:
        """Il controllo come lo esegue GitHub Actions: ``bash -e``, cwd=repo."""
        ambiente = dict(os.environ)
        ambiente["GIT_CONFIG_GLOBAL"] = os.devnull
        ambiente["GIT_CONFIG_SYSTEM"] = os.devnull
        ambiente["HOME"] = self.radice
        ambiente["RUN_SORGENTE_ID"] = run_id
        return subprocess.run(("bash", "-e", self.script), cwd=self.repo,
                              env=ambiente, capture_output=True, text=True)

    # -- asserzioni ---------------------------------------------------------
    def assertPassa(self, esito: subprocess.CompletedProcess, contesto: str) -> None:
        if esito.returncode != 0:
            raise AssertionError(
                f"{contesto}: il controllo doveva passare, e' uscito con "
                f"{esito.returncode}\nstdout:\n{esito.stdout}\nstderr:\n{esito.stderr}")

    def assertFallisce(self, esito: subprocess.CompletedProcess, contesto: str,
                       *frasi_attese: str) -> None:
        if esito.returncode == 0:
            raise AssertionError(
                f"{contesto}: il controllo doveva fallire, e' passato\n"
                f"stdout:\n{esito.stdout}")
        testo = esito.stdout + esito.stderr
        for frase in frasi_attese:
            if frase not in testo:
                raise AssertionError(
                    f"{contesto}: nell'output manca {frase!r}\nstdout:\n{esito.stdout}")


class TestControlloArchivio(unittest.TestCase):
    """Il controllo estratto dal workflow, eseguito su repository temporanei."""

    def setUp(self) -> None:
        if shutil.which("git") is None:                # pragma: no cover
            self.skipTest("git non disponibile")
        self.casi = []

    def tearDown(self) -> None:
        for caso in self.casi:
            caso.chiudi()

    def nuovo(self) -> RepositoryTemporaneo:
        caso = RepositoryTemporaneo()
        caso.prepara()
        self.casi.append(caso)
        return caso

    def test_lo_step_esiste_e_non_ha_espressioni_github(self):
        script = estrai_script_del_controllo()
        self.assertIn("git ls-files", script)
        self.assertIn("player_match_", script)
        self.assertIn("ppda-player-verify-", script)
        # Il vecchio controllo, quello del falso positivo, non deve tornarci fra
        # le righe eseguite (nei commenti il workflow lo cita come spiegazione).
        eseguite = righe_di_codice(script)
        for riga in eseguite:
            self.assertNotIn("ls-files --error-unmatch audit/output", riga,
                             f"il controllo del falso positivo e' tornato: {riga}")

    def test_preesistenti_tracciati_passano(self):
        """Il caso reale del run 38393593454: 18 file tracciati sotto audit/output/."""
        caso = self.nuovo()
        esito = caso.esegui_controllo()
        caso.assertPassa(esito, "file preesistenti tracciati in audit/output/")
        self.assertIn("OK: nessun player_match", esito.stdout)
        # I preesistenti vengono elencati come informazione, non come errore.
        for percorso in PREESISTENTI:
            self.assertIn(percorso, esito.stdout)
        self.assertIn("tollerati", esito.stdout)
        # E dice quanti archivi ha visti nella cartella scaricata (non versionata).
        self.assertIn("player_match_*.json scaricati", esito.stdout)
        self.assertNotIn("::error::", esito.stdout)

    def test_il_vecchio_controllo_era_un_falso_positivo(self):
        """Sullo stesso repository, `git ls-files --error-unmatch audit/output` diceva 'tracciato'."""
        caso = self.nuovo()
        esito = caso._git("ls-files", "--error-unmatch", "audit/output")
        self.assertEqual(0, esito.returncode,
                         "il vecchio controllo trovava audit/output tracciato e "
                         "per questo il run falliva anche senza archivio committato")
        # Nessuno di quei file e' un archivio player_match.
        tracciati = caso._git("ls-files", "audit/output").stdout.split()
        self.assertEqual(sorted(PREESISTENTI), sorted(tracciati))
        for percorso in tracciati:
            self.assertNotIn("player_match_", percorso)
            self.assertNotIn("ppda-player-verify-", percorso)

    def test_player_match_staged_fa_fallire(self):
        caso = self.nuovo()
        caso.staged(ARCHIVI[0])
        esito = caso.esegui_controllo()
        caso.assertFallisce(esito, "player_match_*.json aggiunto all'indice",
                            "l'archivio player_match e' entrato nell'indice",
                            ARCHIVI[0])

    def test_tutti_i_player_match_staged_fa_fallire(self):
        caso = self.nuovo()
        caso.staged(*ARCHIVI)
        esito = caso.esegui_controllo()
        caso.assertFallisce(esito, "tutti gli archivi aggiunti all'indice",
                            ARCHIVI[0], ARCHIVI[1])

    def test_altro_file_della_cartella_scaricata_fa_fallire(self):
        """Anche un file che non si chiama player_match_*.json, se viene dalla cartella scaricata."""
        caso = self.nuovo()
        caso.staged(ALTRO_FILE_SCARICATO)
        esito = caso.esegui_controllo()
        caso.assertFallisce(esito, "file della cartella scaricata staged",
                            "l'archivio player_match e' entrato nell'indice",
                            ALTRO_FILE_SCARICATO)

    def test_player_match_fuori_dalla_cartella_scaricata_fa_fallire(self):
        """Il pattern guarda il nome del file, non solo la cartella del download."""
        caso = self.nuovo()
        percorso = "audit/data/player_match_Bundesliga.json"
        caso.scrivi(percorso, '{"finto": true}\n')
        caso.staged(percorso)
        esito = caso.esegui_controllo()
        caso.assertFallisce(esito, "player_match_*.json staged fuori dalla cartella scaricata",
                            percorso)

    def test_senza_archivio_scaricato_il_controllo_non_passa(self):
        """Se la cartella scaricata non c'e', il controllo non deve passare per vuoto."""
        caso = self.nuovo()
        caso.rimuovi(CARTELLA_SCARICATA)
        esito = caso.esegui_controllo()
        caso.assertFallisce(esito, "cartella scaricata assente",
                            "nessun player_match_*.json scaricato")

    def test_referto_modificato_ammesso_ma_altre_modifiche_in_audit_no(self):
        caso = self.nuovo()
        caso.scrivi("audit/results/altro_referto.md", "non richiesto\n")
        esito = caso.esegui_controllo()
        caso.assertFallisce(esito, "un altro file scritto in audit/",
                            "oltre al referto sono cambiati altri file in audit/")

    def test_modifica_in_soccermath_fa_fallire(self):
        caso = self.nuovo()
        caso.scrivi("SoccerMath/database/squadre.csv", "squadra\nArsenal\nChelsea\n")
        esito = caso.esegui_controllo()
        caso.assertFallisce(esito, "SoccerMath/ toccato",
                            "lo scaricamento ha toccato SoccerMath/")

    def test_solo_il_referto_cambiato_passa(self):
        """Il caso normale: la sonda ha riscritto il referto e basta."""
        caso = self.nuovo()
        caso.scrivi(REFERTO, "# Sonda squalifiche\n\nesito: copertura 100%\n")
        esito = caso.esegui_controllo()
        caso.assertPassa(esito, "solo il referto cambiato")
        self.assertIn("OK: nessun player_match", esito.stdout)


class TestEstrazioneDalWorkflow(unittest.TestCase):
    """L'estrazione per indentazione deve seguire il workflow, non copiarlo."""

    def test_lo_script_estratto_e_quello_del_workflow(self):
        script = estrai_script_del_controllo()
        eseguite = righe_di_codice(script)
        self.assertTrue(eseguite[0].startswith("PATTERN="),
                        f"prima riga eseguita inattesa: {eseguite[0]!r}")
        self.assertIn('PATTERN=', script)
        self.assertIn("git diff --cached --name-only", script)
        # Il controllo si chiude con un'informazione, non con un exit fisso.
        self.assertFalse(eseguite[-1].startswith("exit"),
                         f"lo script non deve chiudersi con {eseguite[-1]!r}")
        self.assertIn("solo il referto", eseguite[-1])

    def test_uno_step_che_non_esiste_solleva(self):
        with self.assertRaises(AssertionError):
            estrai_script_del_controllo(nome_step="Step che non esiste")

    def test_il_workflow_ha_un_solo_step_con_quel_nome(self):
        with open(PERCORSO_WORKFLOW, encoding="utf-8") as fh:
            testo = fh.read()
        self.assertEqual(1, testo.count(f"- name: {NOME_STEP}"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
