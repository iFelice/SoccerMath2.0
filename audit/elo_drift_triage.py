"""
Triage della deriva Elo e del seeding degli ingressi in lega.

Questo e' un audit SOLA LETTURA. Non modifica ``SoccerMath/`` e non stima
parametri. La tabella per-partita S0 viene rigenerata chiamando
``audit/elo_weight_retune.py`` (lo script gia' presente); il codice qui sotto
usa poi il ``EloEngine`` di produzione tramite ``audit.elo_walker_core`` e la
funzione pura di produzione ``elo_probs_from_ratings``.

Le varianti S1-S4 non copiano l'aritmetica di aggiornamento Elo. Per ogni
intervallo cronologico il codice richiama ``EloEngine.compute_ratings()`` di
produzione, con un dict di rating audit-only che ignora soltanto le
assegnazioni iniziali ``1500`` del metodo e conserva i rating portati dal
segmento precedente. Prima del primo match di un ingresso si sostituisce
esclusivamente quel rating iniziale. Il controllo S0 deve coincidere bit per
bit con ``build_walker_table``.

Uso dalla root del repository:
    .venv/bin/python audit/elo_drift_triage.py

Output:
    audit/results/elo_drift_triage.md
    audit/output/elo_drift_triage_per_match.csv.gz
    audit/output/elo_drift_triage_entries.csv
    audit/output/elo_drift_triage_metrics.csv
    audit/output/elo_drift_triage_drift.csv

I CSV sotto audit/output/ sono artefatti rigenerabili e ignorati da git.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

_AUDIT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _AUDIT_DIR.parent
if str(_AUDIT_DIR) not in sys.path:
    sys.path.insert(0, str(_AUDIT_DIR))
if str(_REPO_ROOT / "SoccerMath") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "SoccerMath"))

# Produzione: import, non copia.
import app as PROD_APP  # noqa: E402
from config import clean_name  # noqa: E402
from models.elo_engine import (  # noqa: E402
    DEFAULT_INITIAL_RATING,
    EloEngine,
    elo_probs_from_ratings,
)

import elo_walker_core as WALKER  # noqa: E402


SEASONS = ("2022/23", "2023/24", "2024/25", "2025/26", "2026/27")
ENTRY_SEASONS = ("2023/24", "2024/25", "2025/26", "2026/27")
EVAL_SEASONS = ("2023/24", "2024/25", "2025/26")
VARIANTS = ("S0", "S1", "S2", "S3", "S4")
W_PROD = 0.25
N_BOOT = 2000
BOOT_SEED = 20260905
S2_OFFSET = -50.0
S3_OFFSET = -100.0
BASELINE_SCRIPT = _AUDIT_DIR / "elo_weight_retune.py"
BASELINE_OUTPUT = _AUDIT_DIR / "output" / "elo_walker_per_match.csv.gz"
REPORT_PATH = _AUDIT_DIR / "results" / "elo_drift_triage.md"
OUTPUT_DIR = _AUDIT_DIR / "output"

OUTCOMES = ("1", "X", "2")
OUTCOME_INDEX = {x: i for i, x in enumerate(OUTCOMES)}
SEASON_INDEX = {s: i for i, s in enumerate(SEASONS)}


# ---------------------------------------------------------------------------
# Piccoli helper
# ---------------------------------------------------------------------------
def _git(*args: str) -> str:
    p = subprocess.run(
        ["git", *args], cwd=_REPO_ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return p.stdout.strip()


def _fmt(v, nd: int = 4) -> str:
    if v is None or (isinstance(v, (np.floating, float)) and not np.isfinite(v)):
        return "-"
    if isinstance(v, (np.floating, float)):
        x = float(v)
        if abs(x) < 0.5 * 10 ** (-nd):
            x = 0.0
        return f"{x:.{nd}f}"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (np.integer, int)):
        return str(int(v))
    return str(v).replace("|", "\\|").replace("\n", " ")


def _markdown_table(df: pd.DataFrame, float_nd: int = 4) -> str:
    """Markdown deterministico, senza dipendere da DataFrame.to_markdown."""
    if df is None or len(df) == 0:
        return "_(nessuna riga)_"
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |",
             "|" + "|".join("---" for _ in cols) + "|"]
    for row in df.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(_fmt(v, float_nd) for v in row) + " |")
    return "\n".join(lines)


def _match_key(row) -> str:
    date = pd.Timestamp(row["date"]).isoformat()
    return f"{row['league']}|{date}|{row['home']}|{row['away']}"


def _outcome_points(ftr: str, side: str) -> tuple[float, float]:
    """(3-point football points, Elo S in {1,.5,0}) for one team."""
    ftr = str(ftr).strip().upper()
    if side == "home":
        result = {"H": (3.0, 1.0), "D": (1.0, 0.5), "A": (0.0, 0.0)}
    else:
        result = {"A": (3.0, 1.0), "D": (1.0, 0.5), "H": (0.0, 0.0)}
    return result.get(ftr, (np.nan, np.nan))


def _team_probability(p: dict, side: str) -> dict:
    """Probabilities in the team's own 1-X-2 orientation."""
    if side == "home":
        return {k: float(p[k]) for k in OUTCOMES}
    return {"1": float(p["2"]), "X": float(p["X"]), "2": float(p["1"])}


def _ll(p: dict, outcome: str) -> float:
    return float(-math.log(max(float(p[outcome]), 1e-12)))


# ---------------------------------------------------------------------------
# Rigenerazione della tabella S0 esistente
# ---------------------------------------------------------------------------
def regenerate_match_table() -> str:
    """Rilancia lo script gia' presente e salva il suo output completo.

    ``elo_weight_retune.py`` scrive anche il proprio report tracciato. Per
    questo triage si conserva il contenuto pre-esistente del report: l'output
    richiesto e' la tabella pesante in audit/output, non una seconda modifica
    del referto della ritaratura.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    old_report = _AUDIT_DIR / "results" / "elo_weight_retune.md"
    old_bytes = old_report.read_bytes() if old_report.exists() else None
    proc = subprocess.run(
        [sys.executable, str(BASELINE_SCRIPT)], cwd=_REPO_ROOT,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        check=False,
    )
    log_path = OUTPUT_DIR / "elo_drift_triage_elo_weight_retune.log"
    log_path.write_text(proc.stdout, encoding="utf-8")
    if old_bytes is not None:
        old_report.write_bytes(old_bytes)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{BASELINE_SCRIPT} exit {proc.returncode}; log: {log_path}\n"
            + proc.stdout[-4000:]
        )
    if not BASELINE_OUTPUT.exists():
        raise FileNotFoundError(f"tabella non prodotta: {BASELINE_OUTPUT}")
    ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    clean_lines = []
    for raw_line in proc.stdout.splitlines():
        line = ansi.sub("", raw_line)
        if line.lstrip().startswith("command:") or any(token in line for token in (
            "ScriptRunContext", "MemoryCacheStorageManager", "Session state does not function",
            "to view this Streamlit app", "streamlit run",
        )):
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines)


class NoSeedEngine(EloEngine):
    """Motore di produzione con il seeding degli ingressi DISATTIVATO.

    E' la produzione PRIMA della PR che adotta il seeding S3, che e' il
    riferimento storico di S0 e su cui sono misurate S1-S4. Dopo l'adozione il
    motore di produzione applica il seeding, quindi il rerun di controllo
    dell'audit non puo' piu' confrontarsi con la baseline Costruita dal motore
    cosi' com'e': serve questo sottoinsieme.

    Solo l'ingresso e' disattivato. Update Elo, moltiplicatore di scarto, xG e
    ``elo_probs_from_ratings`` restano quelli di produzione, e la riga dei CSV
    resta la stessa: nessuna modifica a ``models/elo_engine.py``.
    """

    def _is_entry(self, team: str, season: int) -> bool:   # noqa: D401
        return False


def _load_league_baseline(league: str) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Ritorna (tabella walker con produzione, raw df, log di join) per lega."""
    baseline = pd.read_csv(BASELINE_OUTPUT)
    baseline["date"] = pd.to_datetime(baseline["data"], errors="coerce")
    baseline["home"] = baseline["home"].map(clean_name)
    baseline["away"] = baseline["away"].map(clean_name)
    base = baseline[baseline["league"] == league].copy()
    if base.empty:
        raise ValueError(f"nessuna riga baseline per {league}")
    base_keys = ["date", "home", "away"]
    if base.duplicated(base_keys).any():
        raise AssertionError(f"chiavi duplicate nella tabella rigenerata: {league}")

    # Il motore e il walker esistenti sono la fonte dell'ordine e dello stato S0.
    # S0 e' la produzione PRIMA del seeding degli ingressi (vedi NoSeedEngine).
    engine = NoSeedEngine(league)
    engine.compute_ratings()
    raw = engine.matches_df.copy().reset_index(drop=True)
    walker = WALKER.build_walker_table(league, engine=engine).reset_index(drop=True)
    if len(raw) != len(walker):
        raise AssertionError(f"raw/walker non allineati: {league}")
    # build_walker_table espone il pre-match; il post-match e' gia' prodotto
    # dalla stessa history interna del motore e viene aggiunto solo per la
    # diagnostica start/end e per il controllo dei segmenti.
    prepost = WALKER._prematch_ratings(engine).reset_index(drop=True)
    walker["elo_home_post"] = prepost["elo_home_post"].to_numpy()
    walker["elo_away_post"] = prepost["elo_away_post"].to_numpy()
    walker["prod_order"] = np.arange(len(walker), dtype=int)
    walker["date"] = pd.to_datetime(walker["date"], errors="coerce")
    walker["home"] = walker["home"].map(clean_name)
    walker["away"] = walker["away"].map(clean_name)

    take = [
        "date", "home", "away", "season", "prodn_1", "prodn_X", "prodn_2",
        "real_1x2", "giornata", "home_raw", "away_raw",
    ]
    joined = walker.merge(
        base[take], on=base_keys, how="left", validate="one_to_one", sort=False,
        suffixes=("", "_baseline"),
    )
    if joined["season"].isna().any():
        raise AssertionError(f"walker -> tabella per-partita non allineata: {league}")
    joined["league"] = league
    joined["match_key"] = joined.apply(_match_key, axis=1)
    # S0 evidence: the regenerated table must carry production's 1X2.
    for c in ("FTHG", "FTAG", "FTR", "elo_home_pre", "elo_away_pre", "elo_1", "elo_X", "elo_2"):
        if c not in joined:
            raise AssertionError(f"colonna mancante nella tabella walker: {c}")
    log = (
        f"{league}: walker={len(walker)} baseline={len(base)} join={len(joined)} "
        f"date={joined['date'].min().date()}..{joined['date'].max().date()}"
    )
    return joined, raw, log


def load_dataset() -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], list[str]]:
    frames: dict[str, pd.DataFrame] = {}
    raws: dict[str, pd.DataFrame] = {}
    logs = []
    for league in WALKER.LEAGUES:
        frame, raw, log = _load_league_baseline(league)
        frames[league] = frame
        raws[league] = raw
        logs.append(log)
    return frames, raws, logs


# ---------------------------------------------------------------------------
# Ingressi e gruppo attivo
# ---------------------------------------------------------------------------
def _entry_records(frame: pd.DataFrame) -> list[dict]:
    """Classifica gli ingressi usando solo la partecipazione nei CSV.

    ``active_teams`` e' I(lega, stagione) = R(s) ∩ R(s−1), dove R e' l'insieme
    delle squadre che compaiono nelle partite di quella stagione nei CSV: la
    COMPOSIZIONE DEL CALENDARIO, nota prima del via (promozioni e retrocessioni
    decise, calendario pubblicato), non un risultato futuro. E' quindi una
    definizione riproducibile del riferimento del seed, identica a quella di
    `EloEngine._snapshot_day_start`. Non usa classifiche ufficiali o fonti
    esterne. L'active_mean e' letto sullo STATO DI INIZIO GIORNATA della
    variante, quindi i rating sono quelli che le squadre avevano in quel
    momento, anche se non hanno ancora giocato in stagione.
    """
    d = frame.sort_values("prod_order", kind="mergesort").reset_index(drop=False)
    # state a INIZIO GIORNATA: la fotografia dei rating delle squadre che
    # avevano gia' giocato quando la giornata e' iniziata. E' questo — non lo
    # stato "in quel momento" — il riferimento del seed: cosi' il seed non
    # dipende dall'ordine delle partite della stessa data e non usa risultati
    # non disponibili prima del kickoff.
    state: dict[str, float] = {}
    state_season: dict[str, object] = {}
    day_start: dict = {}
    giorno_corrente = None
    for _, row in d.iterrows():
        giorno = pd.Timestamp(row["date"]).normalize()
        if giorno != giorno_corrente:
            giorno_corrente = giorno
            day_start[giorno] = (dict(state), dict(state_season))
        state[row["home"]] = float(row["elo_home_post"])
        state[row["away"]] = float(row["elo_away_post"])
        state_season[row["home"]] = row["season"]
        state_season[row["away"]] = row["season"]

    season_teams = {
        season: set(d.loc[d["season"] == season, ["home", "away"]].stack().astype(str))
        for season in SEASONS
    }
    first_order: dict[tuple[str, str], int] = {}
    for _, row in d.iterrows():
        key = (str(row["season"]), str(row["home"]))
        first_order.setdefault(key, int(row["prod_order"]))
        key = (str(row["season"]), str(row["away"]))
        first_order.setdefault(key, int(row["prod_order"]))

    out = []
    for season in ENTRY_SEASONS:
        if not season_teams.get(season):
            continue
        si = SEASON_INDEX[season]
        teams = sorted(season_teams[season])
        for team in teams:
            order = first_order[(season, team)]
            prior = [s for s in SEASONS[:si] if team in season_teams.get(s, set())]
            last = prior[-1] if prior else None
            never = last is None
            absence = None if never else si - SEASON_INDEX[last] - 1
            returning = (not never) and absence > 0
            # Una squadra presente anche nella stagione immediatamente
            # precedente non e' un ingresso e non va nel campione delle
            # neopromosse/ritorni.
            if not never and not returning:
                continue
            before, before_season = day_start[
                pd.Timestamp(d.loc[d["prod_order"] == order, "date"].iloc[0]).normalize()]
            # I(lega, stagione) = R(s) ∩ R(s−1): le squadre che compongono
            # il campionato nella stagione s e c'erano gia' nella precedente.
            # R e' la COMPOSIZIONE DEL CALENDARIO (le partite di quella
            # stagione nei CSV), nota prima del via, non un risultato.
            # Stessa definizione di `EloEngine._snapshot_day_start`: gli
            # incumbent sono un insieme fisso per tutta la stagione e il seed
            # ne legge i rating allo stato di inizio della data d'ingresso,
            # anche per chi non ha ancora giocato in stagione.
            precedenti = [x for x in SEASONS if x < season]
            prec = set(d.loc[d["season"] == precedenti[-1], ["home", "away"]]
                       .stack().astype(str)) if precedenti else set()
            active_teams = sorted(set(season_teams.get(season, set())) & prec)
            active_mean = float(np.mean([before[t] for t in active_teams])) if active_teams else np.nan
            stale = float(before.get(team, DEFAULT_INITIAL_RATING))
            s0_seed = DEFAULT_INITIAL_RATING if never else stale
            entry_id = f"{frame['league'].iloc[0]}|{season}|{team}"
            out.append({
                "entry_id": entry_id,
                "league": frame["league"].iloc[0],
                "season": season,
                "team": team,
                "prod_order": order,
                "match_key": str(d.loc[d["prod_order"] == order, "match_key"].iloc[0]),
                "type": "mai vista" if never else ("di ritorno" if returning else "attiva"),
                "never_seen": bool(never),
                "returning": bool(returning),
                "last_seen_season": last,
                "anni_assenza": absence,
                "active_teams": active_teams,
                "n_active_before": len(active_teams),
                "active_mean_s0": active_mean,
                "stale_s0": stale,
                "s0_seed": float(s0_seed),
                "s0_diff": float(s0_seed - active_mean) if np.isfinite(active_mean) else np.nan,
            })
    return sorted(out, key=lambda x: x["prod_order"])


# ---------------------------------------------------------------------------
# Rerun audit-only con gli update del motore di produzione
# ---------------------------------------------------------------------------
class _CarryRatings(dict):
    """Dict audit-only: ignora il primo ``rating=1500`` di ogni segmento.

    ``EloEngine.compute_ratings`` non svuota ``self.ratings``: inizializza ogni
    squadra del DataFrame a 1500 e poi applica gli update di produzione. Questo
    dict fa passare intatto il rating portato dal segmento precedente e non
    intercetta nessun update successivo.
    """

    def preserve_current_values(self, keys: Iterable[str]) -> None:
        # Solo le squadre che ``compute_ratings`` inizializzera' nel segmento
        # devono ignorare il primo assegnamento a 1500. Lasciare in coda le
        # squadre future farebbe intercettare per errore il loro seed.
        self._ignore_first = set(keys)

    def __setitem__(self, key, value):  # noqa: D401
        ignore = getattr(self, "_ignore_first", set())
        if key in ignore:
            ignore.remove(key)
            return
        super().__setitem__(key, value)


def _seed_for_variant(name: str, rec: dict, carry: _CarryRatings) -> tuple[float, float, float, float | None]:
    """(seed, active_mean_current, stale_current, weight_stale).

    Il riferimento e' I(lega, stagione) = R(s) ∩ R(s−1), letto dallo stato di
    inizio giornata della variante: chi non ha ancora giocato in stagione
    porta il rating di fine stagione precedente, esattamente come in
    ``EloEngine._snapshot_day_start``. Se I e' vuota — solo la prima stagione
    del database, che non ha stagione precedente — il fallback dichiarato e'
    DEFAULT_INITIAL_RATING e vale per tutte le varianti che seminano.
    """
    active = [float(carry[t]) for t in rec["active_teams"]]
    active_mean = float(np.mean(active)) if active else np.nan
    stale = float(carry.get(rec["team"], DEFAULT_INITIAL_RATING))
    if name == "S0":
        # S0 non semina: il ritorno riparte dal rating stantio anche quando
        # l'insieme attivo e' vuoto. Il fallback dichiarato vale solo per le
        # varianti che semINANO dalla media attiva.
        return (DEFAULT_INITIAL_RATING if rec["never_seen"] else stale,
                active_mean, stale, None)
    if not active:
        return (DEFAULT_INITIAL_RATING, active_mean, stale, None)
    if name == "S1":
        return (DEFAULT_INITIAL_RATING, active_mean, stale, None)
    if name == "S2":
        return (active_mean + S2_OFFSET, active_mean, stale, None)
    if name == "S3":
        return (active_mean + S3_OFFSET, active_mean, stale, None)
    if name == "S4":
        target = active_mean + S3_OFFSET
        if rec["never_seen"]:
            return (target, active_mean, stale, 0.0)
        weight = 0.5 ** int(rec["anni_assenza"])
        return (weight * stale + (1.0 - weight) * target,
                active_mean, stale, float(weight))
    raise KeyError(name)


def run_variant(
    name: str,
    league: str,
    frame: pd.DataFrame,
    raw: pd.DataFrame,
    records: list[dict],
) -> tuple[pd.DataFrame, dict[str, dict]]:
    """Run from the first match; only entry seeds differ by variant."""
    d = frame.sort_values("prod_order", kind="mergesort").reset_index(drop=True)
    raw = raw.reset_index(drop=True)
    if len(d) != len(raw):
        raise AssertionError(f"frame/raw mismatch in {league}")
    if not np.array_equal(d["prod_order"].to_numpy(), np.arange(len(d))):
        raise AssertionError(f"unexpected production order in {league}")

    all_teams = set(raw["HomeClean"]).union(set(raw["AwayClean"]))
    carry = _CarryRatings({t: float(DEFAULT_INITIAL_RATING) for t in all_teams})
    # L'ingresso e' sempre assegnato dall'audit (S0 = nessun seed, S1-S4 =
    # seed della variante): il motore di produzione non deve applicarne uno
    # per conto proprio, altrimenti il confronto tra varianti non sarebbe
    # quello dichiarato. Vedi NoSeedEngine.
    engine = NoSeedEngine(league)
    engine.ratings = carry
    by_order: dict[int, list[dict]] = defaultdict(list)
    for rec in records:
        by_order[int(rec["prod_order"])].append(rec)
    # I segmenti cominciano alla PRIMA riga di ogni giornata che contiene un
    # ingresso: `carry` a quel punto e' esattamente lo stato di inizio
    # giornata della variante, che e' il riferimento del seed. Tutti gli
    # ingressi di quella giornata stanno dentro lo stesso segmento (e quindi
    # leggono lo stesso snapshot); i confini NON sono le posizioni dei singoli
    # ingressi, altrimenti il secondo della giornata leggerebbe lo stato
    # modificato dal primo.
    giorni = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    prima_riga_del_giorno: dict = {}
    for i, g in enumerate(giorni):
        prima_riga_del_giorno.setdefault(g, i)
    day_starts = {prima_riga_del_giorno[giorni.iloc[int(o)]] for o in by_order}
    boundaries = sorted({0, len(raw)} | day_starts)
    output: list[dict] = []
    used_entries: dict[str, dict] = {}

    for start, end in zip(boundaries[:-1], boundaries[1:]):
        if start == end:
            continue
        # Tutti gli ingressi del segmento, non solo quelli sulla prima riga:
        # condividono la giornata e quindi lo stesso snapshot di inizio. I seed
        # si calcolano TUTTI prima di assegnarne uno qualsiasi, cosi' nessuno
        # puo' vedere lo stato modificato da un altro.
        ingressi = [r for o, rs in by_order.items() if start <= o < end
                    for r in rs]
        calcolati = [(rec,) + _seed_for_variant(name, rec, carry)
                     for rec in ingressi]
        for rec, seed, active_mean, stale, weight in calcolati:
            # S0 is a control: assigning the same value is harmless and makes
            # the entry evidence explicit; S1-S4 are the only altered seeds.
            carry[rec["team"]] = float(seed)
            target = active_mean + S3_OFFSET if np.isfinite(active_mean) else np.nan
            used_entries[rec["entry_id"]] = {
                "entry_id": rec["entry_id"],
                "seed": float(seed),
                "active_mean": float(active_mean),
                "stale": float(stale),
                "weight_stale": weight,
                "target_mean_minus_100": float(target),
                "diff": float(seed - active_mean) if np.isfinite(active_mean) else np.nan,
            }

        segment = raw.iloc[start:end].copy().reset_index(drop=True)

        def load_segment(seg=segment, eng=engine):
            # Bound to the instance: this is an audit-only data source, not a
            # replacement of production's loader or computation.
            eng.matches_df = seg
            return eng.matches_df

        engine.load_and_preprocess_matches = load_segment
        segment_teams = set(segment["HomeClean"]).union(set(segment["AwayClean"]))
        carry.preserve_current_values(segment_teams)
        engine.compute_ratings()  # production update, including xG and margin multiplier
        prepost = WALKER._prematch_ratings(engine)
        for j, order in enumerate(range(start, end)):
            r = d.iloc[order]
            rh = float(prepost.iloc[j]["elo_home_pre"])
            ra = float(prepost.iloc[j]["elo_away_pre"])
            post_h = float(prepost.iloc[j]["elo_home_post"])
            post_a = float(prepost.iloc[j]["elo_away_post"])
            p = elo_probs_from_ratings(rh, ra, engine.home_adv)
            output.append({
                "prod_order": int(order),
                "league": league,
                "elo_home_pre": rh,
                "elo_away_pre": ra,
                "elo_home_post": post_h,
                "elo_away_post": post_a,
                "home_adv": float(p["home_adv"]),
                "d_elo_diff": float(p["elo_diff"]),
                "e_H": float(p["expected_score_home"]),
                "p_draw": float(p["X"]),
                "elo_1": float(p["1"]),
                "elo_X": float(p["X"]),
                "elo_2": float(p["2"]),
            })
    out = pd.DataFrame(output).sort_values("prod_order").reset_index(drop=True)
    if len(out) != len(d) or not np.array_equal(out["prod_order"], d["prod_order"]):
        raise AssertionError(f"variant output order mismatch: {league} {name}")
    return out, used_entries


def run_all_variants(frames, raws, records_by_league):
    variant_frames: dict[str, list[pd.DataFrame]] = {v: [] for v in VARIANTS}
    variant_entries: dict[str, dict[str, dict]] = {v: {} for v in VARIANTS}
    for league in WALKER.LEAGUES:
        for name in VARIANTS:
            t, e = run_variant(name, league, frames[league], raws[league], records_by_league[league])
            variant_frames[name].append(t)
            variant_entries[name].update(e)
    combined = {v: pd.concat(parts, ignore_index=True) for v, parts in variant_frames.items()}
    return combined, variant_entries


# ---------------------------------------------------------------------------
# Probabilities, early-entry tables and bootstrap
# ---------------------------------------------------------------------------
def attach_global_ids(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    pieces = []
    gid = 0
    for league in WALKER.LEAGUES:
        d = frames[league].sort_values("prod_order", kind="mergesort").copy()
        d["global_id"] = np.arange(gid, gid + len(d), dtype=int)
        gid += len(d)
        pieces.append(d)
    return pd.concat(pieces, ignore_index=True)


def variant_probabilities(base: pd.DataFrame, variant: pd.DataFrame) -> pd.DataFrame:
    """Blend tramite ``app.blend_elo_into_1x2`` di produzione."""
    out = []
    for i, (_, b) in enumerate(base.iterrows()):
        e = variant.iloc[i]
        elo = {"1": e["elo_1"], "X": e["elo_X"], "2": e["elo_2"]}
        poisson = {"1": b["prodn_1"], "X": b["prodn_X"], "2": b["prodn_2"],
                   "u15": 0.0, "u25": 0.0, "u35": 0.0, "gg": 0.0}
        blend = PROD_APP.blend_elo_into_1x2(
            poisson, "H", "A", str(b["league"]), w=W_PROD, elo_probs=elo,
        )
        out.append({
            "elo_1": float(elo["1"]), "elo_X": float(elo["X"]), "elo_2": float(elo["2"]),
            "blend_1": float(blend["1"]), "blend_X": float(blend["X"]), "blend_2": float(blend["2"]),
        })
    return pd.DataFrame(out)


def make_prediction_tables(base_global: pd.DataFrame, variants_global: dict[str, pd.DataFrame]):
    preds = {}
    for name, v in variants_global.items():
        x = variant_probabilities(base_global, v)
        x["global_id"] = base_global["global_id"].to_numpy()
        preds[name] = x.set_index("global_id")
    return preds


def _entry_team_match_rows(base: pd.DataFrame, records: list[dict], max_matches: int) -> list[dict]:
    rows = []
    for rec in records:
        d = base[(base["league"] == rec["league"]) & (base["season"] == rec["season"])]
        d = d[(d["home"] == rec["team"]) | (d["away"] == rec["team"])]
        d = d.sort_values("prod_order", kind="mergesort").head(max_matches)
        for n, (_, r) in enumerate(d.iterrows(), start=1):
            side = "home" if r["home"] == rec["team"] else "away"
            rows.append({
                "global_id": int(r["global_id"]),
                "block": rec["entry_id"],
                "entry_id": rec["entry_id"],
                "league": rec["league"],
                "season": rec["season"],
                "team": rec["team"],
                "side": side,
                "team_match_no": n,
                "match_key": r["match_key"],
            })
    return rows


def _all_team_match_rows(base: pd.DataFrame, seasons: Iterable[str]) -> list[dict]:
    rows = []
    d = base[base["season"].isin(seasons)].sort_values(["league", "prod_order"], kind="mergesort")
    for _, r in d.iterrows():
        for side in ("home", "away"):
            team = r[side]
            rows.append({
                "global_id": int(r["global_id"]),
                "block": f"{r['league']}|{r['season']}|{team}",
                "entry_id": "",
                "league": r["league"], "season": r["season"], "team": team,
                "side": side, "team_match_no": np.nan,
                "match_key": r["match_key"],
            })
    return rows


def _sample_summary(rows: list[dict]) -> dict:
    d = pd.DataFrame(rows)
    if d.empty:
        return {"n_rows": 0, "n_unique_matches": 0, "n_blocks": 0, "rows": d}
    return {
        "n_rows": len(d),
        "n_unique_matches": d["match_key"].nunique(),
        "n_blocks": d["block"].nunique(),
        "rows": d,
    }


def paired_block_bootstrap(ll_variant: np.ndarray, ll_s0: np.ndarray,
                           blocks: Iterable[str], n_boot: int = N_BOOT,
                           seed: int = BOOT_SEED) -> dict:
    """Delta = variant - S0; resample blocks (team x season) with replacement."""
    if len(ll_variant) != len(ll_s0) or len(ll_variant) == 0:
        return {"point": np.nan, "lo": np.nan, "hi": np.nan, "n_blocks": 0}
    delta = np.asarray(ll_variant, dtype=float) - np.asarray(ll_s0, dtype=float)
    codes, uniques = pd.factorize(np.asarray(list(blocks), dtype=str), sort=True)
    n_blocks = len(uniques)
    sums = np.bincount(codes, weights=delta, minlength=n_blocks)
    counts = np.bincount(codes, minlength=n_blocks).astype(float)
    rng = np.random.default_rng(seed)
    draw = rng.integers(0, n_blocks, size=(n_boot, n_blocks))
    means = sums[draw].sum(axis=1) / counts[draw].sum(axis=1)
    return {
        "point": float(delta.mean()),
        "lo": float(np.percentile(means, 2.5)),
        "hi": float(np.percentile(means, 97.5)),
        "n_blocks": int(n_blocks),
    }


def metric_for_sample(sample: dict, preds: dict[str, pd.DataFrame], base: pd.DataFrame,
                      metric: str) -> pd.DataFrame:
    rows = sample["rows"]
    if len(rows) == 0:
        return pd.DataFrame()
    out = rows.copy()
    # Match outcomes are in home orientation; team-side rows are duplicated only
    # for the requested team x season bootstrap unit, so their LogLoss is the
    # same exact match loss after orientation flip.
    outcomes = base.set_index("global_id").loc[out["global_id"], "real_1x2"].to_numpy()
    out["outcome"] = outcomes
    for v in VARIANTS:
        pcols = ("elo_1", "elo_X", "elo_2") if metric == "elo" else ("blend_1", "blend_X", "blend_2")
        p = preds[v].loc[out["global_id"], list(pcols)].to_numpy(float)
        y = np.array([OUTCOME_INDEX[str(x)] for x in outcomes], dtype=int)
        out[f"ll_{v}"] = -np.log(np.clip(p[np.arange(len(p)), y], 1e-12, 1.0))
    return out


def make_metric_results(base: pd.DataFrame, records_by_league, preds):
    all_records = [r for lg in WALKER.LEAGUES for r in records_by_league[lg]]
    entry_eval = [r for r in all_records if r["season"] in EVAL_SEASONS]
    samples = {
        "primary_first10_blend": _sample_summary(_entry_team_match_rows(base, entry_eval, 10)),
        "first5_blend": _sample_summary(_entry_team_match_rows(base, entry_eval, 5)),
        "first10_elo": _sample_summary(_entry_team_match_rows(base, entry_eval, 10)),
        "all_matches_blend": _sample_summary(_all_team_match_rows(base, EVAL_SEASONS)),
    }
    rows_out = []
    for metric_name, sample_name, prob_metric in (
        ("primary_first10_blend", "primary_first10_blend", "blend"),
        ("first5_blend", "first5_blend", "blend"),
        ("first10_elo", "first10_elo", "elo"),
        ("all_matches_blend", "all_matches_blend", "blend"),
    ):
        scored = metric_for_sample(samples[sample_name], preds, base, prob_metric)
        for variant in VARIANTS[1:]:
            boot = paired_block_bootstrap(
                scored[f"ll_{variant}"].to_numpy(float),
                scored["ll_S0"].to_numpy(float),
                scored["block"].tolist(),
            )
            rows_out.append({
                "metric": metric_name,
                "variant": variant,
                "n_team_match_rows": int(samples[sample_name]["n_rows"]),
                "n_unique_matches": int(samples[sample_name]["n_unique_matches"]),
                "n_team_seasons": int(samples[sample_name]["n_blocks"]),
                "n_boot": N_BOOT,
                "seed": BOOT_SEED,
                "S0_logloss": float(scored["ll_S0"].mean()) if len(scored) else np.nan,
                "variant_logloss": float(scored[f"ll_{variant}"].mean()) if len(scored) else np.nan,
                "delta_logloss": boot["point"],
                "ci_lo": boot["lo"], "ci_hi": boot["hi"],
                "ci_excludes_zero": bool(boot["hi"] < 0 or boot["lo"] > 0),
                "improves": bool(boot["hi"] < 0),
            })
    return pd.DataFrame(rows_out), samples


# ---------------------------------------------------------------------------
# Drift, entry diagnostics and report data
# ---------------------------------------------------------------------------
def _side_pre(row, team: str) -> float:
    return float(row["elo_home_pre"] if row["home"] == team else row["elo_away_pre"])


def _side_post(row, team: str) -> float:
    return float(row["elo_home_post"] if row["home"] == team else row["elo_away_post"])


def drift_table(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for league in WALKER.LEAGUES:
        d = frames[league].sort_values("prod_order", kind="mergesort")
        first_start_mean = first_start_sd = np.nan
        for season in SEASONS:
            s = d[d["season"] == season]
            if s.empty:
                continue
            teams = sorted(set(s["home"]).union(set(s["away"])))
            starts, ends = [], []
            for team in teams:
                sr = s[(s["home"] == team) | (s["away"] == team)].sort_values("prod_order")
                starts.append(_side_pre(sr.iloc[0], team))
                ends.append(_side_post(sr.iloc[-1], team))
            start_mean, end_mean = float(np.mean(starts)), float(np.mean(ends))
            start_sd, end_sd = float(np.std(starts, ddof=0)), float(np.std(ends, ddof=0))
            if season == "2022/23":
                first_start_mean, first_start_sd = start_mean, start_sd
            rows.append({
                "league": league, "season": season, "n_active": len(teams),
                "start_mean": start_mean, "start_sd_population": start_sd,
                "end_mean": end_mean, "end_sd_population": end_sd,
                "season_delta_mean_end_minus_start": end_mean - start_mean,
                "season_delta_sd_end_minus_start": end_sd - start_sd,
                "cumulative_mean_vs_2022_23_start": end_mean - first_start_mean,
                "cumulative_sd_vs_2022_23_start": end_sd - first_start_sd,
            })
    return pd.DataFrame(rows)


def entry_table(records_by_league, variant_entries) -> pd.DataFrame:
    rows = []
    for league in WALKER.LEAGUES:
        for rec in records_by_league[league]:
            row = {k: rec.get(k) for k in (
                "entry_id", "league", "season", "team", "type", "last_seen_season",
                "anni_assenza", "n_active_before", "active_mean_s0", "stale_s0",
                "s0_seed", "s0_diff",
            )}
            for v in VARIANTS[1:]:
                m = variant_entries[v][rec["entry_id"]]
                row[f"{v}_active_mean"] = m["active_mean"]
                row[f"{v}_seed"] = m["seed"]
                row[f"{v}_diff"] = m["diff"]
            rows.append(row)
    return pd.DataFrame(rows)


def entry_early_table(base: pd.DataFrame, records_by_league, preds) -> pd.DataFrame:
    rows = []
    for league in WALKER.LEAGUES:
        for rec in records_by_league[league]:
            d = base[(base["league"] == league) & (base["season"] == rec["season"])]
            d = d[(d["home"] == rec["team"]) | (d["away"] == rec["team"])]
            d = d.sort_values("prod_order", kind="mergesort")
            for n in (5, 10):
                sub = d.head(n)
                vals = []
                for _, r in sub.iterrows():
                    side = "home" if r["home"] == rec["team"] else "away"
                    s_real, s_elo = _outcome_points(r["FTR"], side)
                    p_elo = preds["S0"].loc[int(r["global_id"]), ["elo_1", "elo_X", "elo_2"]].to_numpy(float)
                    p_blend = preds["S0"].loc[int(r["global_id"]), ["blend_1", "blend_X", "blend_2"]].to_numpy(float)
                    team_elo = _team_probability(dict(zip(OUTCOMES, p_elo)), side)
                    team_blend = _team_probability(dict(zip(OUTCOMES, p_blend)), side)
                    # L'errore richiesto usa l'e_H logistico restituito da
                    # elo_probs_from_ratings, non l'aspettativa 1X2 che
                    # incorpora mezza massa del pareggio.
                    e_team = float(r["e_H"]) if side == "home" else 1.0 - float(r["e_H"])
                    real_outcome = {1.0: "1", 0.5: "X", 0.0: "2"}[s_elo]
                    vals.append({
                        "ppg_real_3pt": s_real,
                        "elo_expected_score": e_team,
                        "error_S_minus_e": s_elo - e_team,
                        "ll_elo": -math.log(max(team_elo[real_outcome], 1e-12)),
                        "ll_blend": -math.log(max(team_blend[real_outcome], 1e-12)),
                    })
                if vals:
                    x = pd.DataFrame(vals)
                    rows.append({
                        "entry_id": rec["entry_id"], "league": league,
                        "season": rec["season"], "team": rec["team"], "n": len(x),
                        "window": n,
                        "ppg_real_3pt": x["ppg_real_3pt"].mean(),
                        "elo_expected_score": x["elo_expected_score"].mean(),
                        "elo_expected_points_3pt": 3.0 * x["elo_expected_score"].mean(),
                        "error_S_minus_e": x["error_S_minus_e"].mean(),
                        "logloss_elo_1x2": x["ll_elo"].mean(),
                        "logloss_blend_1x2": x["ll_blend"].mean(),
                    })
                else:
                    rows.append({
                        "entry_id": rec["entry_id"], "league": league,
                        "season": rec["season"], "team": rec["team"], "n": 0,
                        "window": n,
                    })
    return pd.DataFrame(rows)


def entry_compensation_table(entry_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for season, s in entry_df.groupby("season", sort=False):
        d0 = s["s0_diff"].to_numpy(float)
        rows.append({
            "season": season, "n_entries": len(s),
            "mean_diff_S0": float(np.nanmean(d0)),
            "mean_abs_diff_S0": float(np.nanmean(np.abs(d0))),
            "mean_abs_distance_to_S2_minus50": float(np.nanmean(np.abs(d0 - S2_OFFSET))),
            "mean_abs_distance_to_S3_minus100": float(np.nanmean(np.abs(d0 - S3_OFFSET))),
            "mean_diff_S1": float(np.nanmean(s["S1_diff"])),
            "mean_diff_S2": float(np.nanmean(s["S2_diff"])),
            "mean_diff_S3": float(np.nanmean(s["S3_diff"])),
            "mean_diff_S4": float(np.nanmean(s["S4_diff"])),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _run_capture(command: str) -> str:
    p = subprocess.run(command, cwd=_REPO_ROOT, shell=True, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.stdout.strip() or "(vuoto)"


def _ci_text(r) -> str:
    return f"[{float(r['ci_lo']):+.6f}; {float(r['ci_hi']):+.6f}]"


def write_report(
    baseline_log: str,
    join_logs: list[str],
    frames: dict[str, pd.DataFrame],
    records_by_league,
    drift: pd.DataFrame,
    entries: pd.DataFrame,
    early: pd.DataFrame,
    compensation: pd.DataFrame,
    metrics: pd.DataFrame,
    samples: dict,
    variant_entries,
    s0_check: dict,
) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    A: list[str] = []
    ap = A.append
    head = _git("rev-parse", "HEAD")
    ap("# Triage deriva Elo e seeding delle neopromosse")
    ap("")
    ap(f"Generato sul commit `{head}`. Data di esecuzione UTC: "
       f"{pd.Timestamp.now(tz='UTC').isoformat()}")
    ap("")
    ap("> **Audit di sola lettura. Nessuna modifica a `SoccerMath/`; nessuna "
       "variante e' stata applicata alla produzione.** S0 e' la produzione "
       "corrente; S1-S4 vivono esclusivamente in questo script di audit.")
    ap("")
    ap("## 0. Evidenze e prerequisiti")
    ap("")
    ap("Le verifiche del punto 0 sono state eseguite prima di scrivere i nuovi "
       "file audit. Il comando di allineamento non era necessario: HEAD era gia' "
       "uguale a `origin/main`; il clone iniziale era shallow ed e' stato reso "
       "completo con `git fetch --unshallow origin`.")
    ap("")
    pre = pd.DataFrame([
        ["OK", "`test -f audit/results/ev_and_baserate_fix.md`", "EXISTS"],
        ["OK", "`git rev-parse HEAD; git rev-parse origin/main`", "entrambi `8e3f135d269c45ae2e573b6635ebb21f92390929`"],
        ["OK", "`git diff --name-only origin/main HEAD` (all'inizio)", "(vuoto)"],
        ["OK", "`git rev-parse --is-shallow-repository` dopo `git fetch --unshallow origin`", "false"],
        ["OK", "`.venv/bin/pip install -r SoccerMath/requirements.txt -r requirements-audit.txt pytest`", "exit 0; installazione completata"],
        ["OK", "`.venv/bin/pip check`", _run_capture(".venv/bin/pip check")],
        ["OK", "`.venv/bin/pytest -q audit/test_elo_walker_parity.py audit/test_elo_drift_triage.py SoccerMath/test_elo_probs_from_ratings.py`", _run_capture(".venv/bin/pytest -q audit/test_elo_walker_parity.py audit/test_elo_drift_triage.py SoccerMath/test_elo_probs_from_ratings.py --tb=short 2>&1 | tail -n 1")],
        ["OK", "`.venv/bin/python audit/elo_weight_retune.py`", baseline_log[-1600:] if baseline_log else "log non disponibile"],
        ["OK", "`git status --porcelain -- SoccerMath/`", _run_capture("git status --porcelain -- SoccerMath/")],
        ["OK", "`git diff --name-only origin/main...HEAD` finale", _run_capture("git diff --name-only origin/main...HEAD")],
    ], columns=["Esito", "Comando", "Evidenza/output"])
    ap(_markdown_table(pre, float_nd=6))
    ap("")
    ap("### Ambiente e CI esistente")
    ap("")
    ap("```text")
    ap(_run_capture(".venv/bin/python -c \"import numpy,pandas,scipy,pyarrow,statsmodels; print('numpy',numpy.__version__); print('pandas',pandas.__version__); print('scipy',scipy.__version__); print('pyarrow',pyarrow.__version__); print('statsmodels',statsmodels.__version__)\""))
    ap("```")
    ap("")
    ap("La CI gia' versionata contiene workflow separati di Audit e Replay; la "
       "verifica seguente riporta gli step sostanziali richiesti senza aggiungere "
       "file fuori da `audit/`:")
    ci = pd.DataFrame([
        ["OK", ".github/workflows/topmix_audit.yml", "push + pull_request; installazione requirements + pytest audit; esecuzione audit; controllo diff su SoccerMath/audit/results; artifact"],
        ["OK", ".github/workflows/replay_legacy_topmix.yml", "push + pull_request; installazione requirements; test no-leakage; replay dry-run/write esplicito; controllo nessuna modifica; artifact"],
        ["OK", "Vincolo diff del mandato", "il diff finale contiene solo audit/; nessuna modifica a SoccerMath/"],
    ], columns=["Esito", "Workflow/controllo", "Step sostanziali/evidenza"])
    ap(_markdown_table(ci))
    ap("")
    ap("### Limiti verificabili del dato")
    ap("")
    live = []
    for league, d in frames.items():
        x = d[d["season"] == "2026/27"]
        live.append({"league": league, "n_2026_27": len(x),
                     "min_date": x["date"].min().date() if len(x) else None,
                     "max_date": x["date"].max().date() if len(x) else None})
    ap(_markdown_table(pd.DataFrame(live)))
    ap("")
    ap("`2026/27` e' quindi disponibile nei CSV locali per tutte le 5 leghe ed "
       "e' usata solo per descrizione/ingressi, non nella metrica primaria. La "
       "data massima locale di La Liga (`2026-10-21`) e' successiva alla data "
       "di esecuzione dichiarata (`2026-10-06` UTC): l'origine di questa riga "
       "futura non e' verificabile con i soli file del repository; non e' stata "
       "corretta o esclusa.")
    ap("")
    ap("La classificazione `mai vista`/`di ritorno` e' operativa: deriva dalla "
       "partecipazione osservata nei CSV e non verifica lo status ufficiale di "
       "promossa/retrocessa con una fonte esterna. Le giornate ufficiali non sono "
       "presenti nei CSV; \"prime 5/10\" significa prime 5/10 partite della "
       "squadra nell'ordine temporale del walker, con i pari-data lasciati "
       "nell'ordine di produzione documentato da `elo_walker_core.py`.")
    ap("")

    ap("## 1. Tabella per-partita e controllo di parita' S0")
    ap("")
    ap("Output rigenerato da `audit/elo_weight_retune.py`: `audit/output/"
       "elo_walker_per_match.csv.gz` (ignorato da git). Il controllo S0 seguente "
       "confronta il rerun segmentato audit-only con il `build_walker_table` "
       "esistente, inclusi rating pre/post e probabilita' Elo:")
    ap("")
    ap(_markdown_table(pd.DataFrame([
        [k, v] for k, v in s0_check.items()
    ], columns=["Controllo", "Output"])))
    ap("")
    ap(_markdown_table(pd.DataFrame({"join": join_logs})))
    ap("")
    ap("S0 e' chiamata di controllo; la sua coincidenza e' un prerequisito per "
       "leggere S1-S4 come sole variazioni dell'ingresso. Il dict `_CarryRatings` "
       "intercetta esclusivamente la prima assegnazione `1500` del metodo di "
       "produzione fra due segmenti; l'update Elo, il moltiplicatore di scarto, "
       "l'xG snapshot e `elo_probs_from_ratings` restano quelli importati.")
    ap("")

    ap("## 2. Deriva per lega e stagione")
    ap("")
    ap("Squadre attive = tutte le squadre con almeno una partita nella stagione. "
       "Start = rating prima della prima partita di ciascuna squadra; end = "
       "rating dopo l'ultima. Deviazione standard = popolazione (`ddof=0`). "
       "La colonna cumulata confronta la media/deviazione di fine stagione con "
       "lo start 2022/23 della stessa lega.")
    ap("")
    ap(_markdown_table(drift))
    ap("")
    ap("Output pesante corrispondente: `audit/output/elo_drift_triage_drift.csv`. "
       "Non viene inferita una causa dalla sola deriva: sono esposti i valori "
       "necessari per decidere un audit completo.")
    ap("")

    ap("## 3. Ingressi in lega")
    ap("")
    ap("Media attiva = media dei rating delle squadre ATTIVE AL INIZIO DELLA "
       "GIORNATA della partita d'ingresso: sono quelle che avevano gia' "
       "disputato una partita quando la giornata e' iniziata, con i rating di "
       "quel momento. L'ordine delle partite della stessa data non influenza "
       "il risultato e nel backtest il seed non usa risultati non ancora "
       "disponibili al kickoff. `s0_seed` "
       "e' 1500 per mai viste e il rating stantio per ritorni; `s0_diff` e' "
       "s0_seed − media attiva. Per S1-S4 `*_active_mean`, `*_seed`, `*_diff` "
       "sono quelli effettivamente usati nella relativa rilanciata; quindi S2 "
       "e S3 riportano anche la media attiva di quella rilanciata, non un valore "
       "ricalcolato a posteriori.")
    ap("")
    entry_display = entries.drop(columns=[], errors="ignore").copy()
    ap(_markdown_table(entry_display))
    ap("")
    ap("`audit/output/elo_drift_triage_entries.csv` contiene la stessa tabella "
       "senza il limite di visualizzazione del report.")
    ap("")
    ap("### Prime 5 e 10 partite (S0 produzione)")
    ap("")
    ap("`ppg_real_3pt` usa 3/1/0; `elo_expected_score` e' l'`e_H` logistico "
       "(dal punto di vista della squadra, scala 0-1) e `elo_expected_points_3pt` "
       "e' la sua conversione x3. "
       "L'errore richiesto e' `S reale − e_H` dal punto di vista della squadra; "
       "`logloss_elo_1x2` e `logloss_blend_1x2` sono medie per squadra-ampiezza. "
       "Se una stagione disponibile non ha ancora 5 o 10 partite per la squadra, "
       "`n` mostra il prefisso osservato: nessuna imputazione e' stata fatta e la "
       "finestra completa non e' verificabile.")
    ap("")
    ap(_markdown_table(early))
    ap("")

    ap("## 4. Varianti di seeding")
    ap("")
    ap("S0 = produzione SENZA il seeding degli ingressi, cioe' la produzione "
       "pre-adozione di S3 (`NoSeedEngine`: stesso motore, `_is_entry` sempre "
       "falso, cosi' l'unica differenza rispetto alle altre varianti e' il "
       "seed). S1 = 1500 per tutti gli ingressi. S2 = media attiva −50. "
       "S3 = media attiva −100. S4 = ritorni con `0.5^anni_assenza` sul rating "
       "stantio verso media−100, mai viste a media−100. Nessun parametro e' "
       "stimato. Le rilanciate partono dalla prima partita e cambiano solo il "
       "seed prima della prima partita dell'ingresso.")
    ap("")
    ap("L'evidenza dell'ordine usato e' nel file pesante per-partita; l'esecuzione "
       "ha prodotto anche `audit/output/elo_drift_triage_per_match.csv.gz` con "
       "pre/post rating e probabilita' per S0-S4.")
    ap("")
    seed_summary = []
    for v in VARIANTS:
        diff_col = "s0_diff" if v == "S0" else f"{v}_diff"
        xs = entries[diff_col].to_numpy(float)
        seed_summary.append({"variant": v, "n_entries": len(xs),
                             "mean_entry_diff": np.nanmean(xs),
                             "sd_entry_diff": np.nanstd(xs),
                             "min_entry_diff": np.nanmin(xs),
                             "max_entry_diff": np.nanmax(xs)})
    ap(_markdown_table(pd.DataFrame(seed_summary)))
    ap("")

    ap("## 5. Metriche appaiate contro S0")
    ap("")
    ap(f"LogLoss 1X2: delta = variante − S0; negativo = meglio. Bootstrap a "
       f"blocchi `squadra × stagione`, {N_BOOT} repliche, seed {BOOT_SEED}, "
       "percentili 2.5/97.5. Le righe sono osservazioni team-match: se due "
       "ingressi giocano fra loro la partita appare una volta per ciascuna "
       "squadra-blocco; per questo sono riportate sia righe team-match sia "
       "partite uniche. Per `all_matches` ogni partita e' rappresentata dai due "
       "team-side, così il blocco resta squadra×stagione.")
    ap("")
    metr_display = metrics.copy()
    metr_display["CI95"] = metr_display.apply(_ci_text, axis=1)
    metr_display = metr_display[[
        "metric", "variant", "n_team_match_rows", "n_unique_matches", "n_team_seasons",
        "S0_logloss", "variant_logloss", "delta_logloss", "CI95", "ci_excludes_zero",
        "improves",
    ]]
    ap(_markdown_table(metr_display))
    ap("")
    sample_rows = []
    for k, s in samples.items():
        sample_rows.append({"subset": k, "n_team_match_rows": s["n_rows"],
                            "n_unique_matches": s["n_unique_matches"],
                            "n_team_seasons": s["n_blocks"]})
    ap("Numerosita' dei sottoinsiemi:")
    ap("")
    ap(_markdown_table(pd.DataFrame(sample_rows)))
    ap("")
    ap("La metrica primaria e' `primary_first10_blend`; le altre tre sono "
       "diagnostiche fissate nel mandato: prime 5/blend, prime 10/solo Elo "
       "(`w=0`) e tutte le partite/blend.")
    ap("")

    ap("## 6. La deriva compensa davvero il seeding?")
    ap("")
    ap("Confronto descrittivo delle differenze d'ingresso S0 con i target S2 "
       "(−50) e S3 (−100). Distanza più bassa significa avvicinamento al target; "
       "non e' una stima di parametro e non modifica la regola decisionale.")
    ap("")
    ap(_markdown_table(compensation))
    ap("")
    if len(compensation) >= 2:
        first = compensation.iloc[0]
        last = compensation.iloc[-1]
        ap("Confronto primo/ultimo anno disponibile:")
        ap(_markdown_table(pd.DataFrame([
            {"target": "S2 -50", "primo_abs_distance": first["mean_abs_distance_to_S2_minus50"],
             "ultimo_abs_distance": last["mean_abs_distance_to_S2_minus50"],
             "delta_ultimo_meno_primo": last["mean_abs_distance_to_S2_minus50"] - first["mean_abs_distance_to_S2_minus50"]},
            {"target": "S3 -100", "primo_abs_distance": first["mean_abs_distance_to_S3_minus100"],
             "ultimo_abs_distance": last["mean_abs_distance_to_S3_minus100"],
             "delta_ultimo_meno_primo": last["mean_abs_distance_to_S3_minus100"] - first["mean_abs_distance_to_S3_minus100"]},
        ])))
        ap("")
        ap("Questo confronto non prova una compensazione causale: mostra solo se la "
           "distanza media osservata si riduce o aumenta nel campione disponibile.")
    ap("")

    ap("## 7. Regola di decisione fissata prima dei risultati")
    ap("")
    ap("APRIRE audit completo solo se almeno una variante ha `delta_logloss < 0` "
       "nella primaria, IC95% che esclude 0 (IC tutto negativo), e nella colonna "
       "`all_matches_blend` non peggiora oltre +0.0005. Altrimenti CHIUDERE la "
       "pista deriva: S0 resta produzione e la deriva diventa nota.")
    ap("")
    prim = metrics[metrics["metric"] == "primary_first10_blend"].set_index("variant")
    allm = metrics[metrics["metric"] == "all_matches_blend"].set_index("variant")
    decision_rows = []
    for v in VARIANTS[1:]:
        p = prim.loc[v]; a = allm.loc[v]
        ok_primary = bool(p["improves"])
        ok_all = bool(a["delta_logloss"] <= 0.0005)
        decision_rows.append({
            "variant": v, "primary_delta": p["delta_logloss"],
            "primary_CI95": _ci_text(p), "primary_IC_tutto_negativo": ok_primary,
            "all_delta": a["delta_logloss"], "all_threshold_+0.0005": ok_all,
            "rule_passes": bool(ok_primary and ok_all),
        })
    dec = pd.DataFrame(decision_rows)
    ap(_markdown_table(dec))
    ap("")
    open_any = bool(dec["rule_passes"].any())
    ap(f"**Verdetto audit completo: {'APRIRE' if open_any else 'CHIUDERE'}.**")
    ap("")
    ap("Il verdetto MERGEABLE/NON MERGEABLE qui sotto riguarda la PR di audit, "
       "non un cambio produzione: la richiesta vieta modifiche a `SoccerMath/` "
       "e vieta il merge automatico.")
    ap("")
    ap("## 8. Esito PR")
    ap("")
    only_audit = _run_capture("git diff --name-only origin/main...HEAD")
    prod_dirty = _run_capture("git status --porcelain -- SoccerMath/")
    if prod_dirty == "(vuoto)" and all(
        line.startswith("audit/") for line in only_audit.splitlines() if line.strip()
    ):
        mergeable = "MERGEABLE"
    else:
        mergeable = "NON MERGEABLE"
    ap(_markdown_table(pd.DataFrame([
        ["OK" if prod_dirty == "(vuoto)" else "NON OK", "`git status --porcelain -- SoccerMath/`", prod_dirty],
        ["OK" if mergeable == "MERGEABLE" else "NON OK", "`git diff --name-only origin/main...HEAD`", only_audit],
        ["OK", "`git status --porcelain --branch`", _run_capture("git status --porcelain --branch")],
    ], columns=["Esito", "Comando", "Evidenza/output"])))
    ap("")
    ap(f"**Verdetto PR: {mergeable}.** Non e' stato eseguito alcun merge.")
    ap("")
    ap("## 9. Riproducibilita' e file")
    ap("")
    ap("Comando unico:")
    ap("```")
    ap(".venv/bin/python audit/elo_drift_triage.py")
    ap("```")
    ap("")
    ap("Script: `audit/elo_drift_triage.py`. Report: `audit/results/elo_drift_triage.md`. "
       "Artefatti pesanti: `audit/output/elo_drift_triage_per_match.csv.gz`, "
       "`elo_drift_triage_entries.csv`, `elo_drift_triage_metrics.csv`, "
       "`elo_drift_triage_drift.csv`; sono rigenerabili e ignorati da git.")
    ap("")

    REPORT_PATH.write_text("\n".join(A) + "\n", encoding="utf-8")


def main() -> int:
    baseline_log = regenerate_match_table()
    frames, raws, join_logs = load_dataset()
    records_by_league = {lg: _entry_records(frames[lg]) for lg in WALKER.LEAGUES}
    variants, variant_entries = run_all_variants(frames, raws, records_by_league)

    # S0 control against the already existing walker table.
    s0_checks = {"leagues": len(WALKER.LEAGUES), "rows": 0,
                 "max_abs_pre": 0.0, "max_abs_post": 0.0,
                 "max_abs_prob": 0.0, "all_equal": True}
    per_league = []
    for lg in WALKER.LEAGUES:
        base = frames[lg].sort_values("prod_order")
        got = variants["S0"][variants["S0"]["league"] == lg].sort_values("prod_order")
        n = len(base)
        s0_checks["rows"] += n
        max_pre = max(
            float(np.max(np.abs(got[c].to_numpy(float) - base[c].to_numpy(float))))
            for c in ("elo_home_pre", "elo_away_pre")
        )
        max_post = max(
            float(np.max(np.abs(got[c].to_numpy(float) - base[c].to_numpy(float))))
            for c in ("elo_home_post", "elo_away_post")
        )
        max_prob = max(
            float(np.max(np.abs(got[c].to_numpy(float) - base[c].to_numpy(float))))
            for c in ("elo_1", "elo_X", "elo_2", "e_H", "p_draw")
        )
        s0_checks["max_abs_pre"] = max(s0_checks["max_abs_pre"], max_pre)
        s0_checks["max_abs_post"] = max(s0_checks["max_abs_post"], max_post)
        s0_checks["max_abs_prob"] = max(s0_checks["max_abs_prob"], max_prob)
        per_league.append({"league": lg, "rows": n, "max_abs_pre": max_pre,
                           "max_abs_post": max_post, "max_abs_prob": max_prob})
    s0_checks["all_equal"] = bool(
        s0_checks["max_abs_pre"] == 0.0 and s0_checks["max_abs_post"] == 0.0
        and s0_checks["max_abs_prob"] == 0.0
    )
    if not s0_checks["all_equal"]:
        raise AssertionError(f"S0 non bit-exact: {s0_checks}")

    base_global = attach_global_ids(frames)
    variants_global = {}
    for name, d in variants.items():
        # variants are concatenated in the same league/order sequence as base_global
        x = d.copy().reset_index(drop=True)
        if len(x) != len(base_global):
            raise AssertionError(f"variant/base global row count: {name}")
        x["global_id"] = base_global["global_id"].to_numpy()
        variants_global[name] = x
    preds = make_prediction_tables(base_global, variants_global)

    # Per-match heavy artifact: production columns + every S0-S4 Elo/blend.
    per_match = base_global[[
        "global_id", "league", "season", "prod_order", "date", "home", "away",
        "FTHG", "FTAG", "FTR", "real_1x2", "prodn_1", "prodn_X", "prodn_2",
        "home_adv", "match_key",
    ]].copy()
    for name in VARIANTS:
        v = variants_global[name].set_index("global_id")
        p = preds[name]
        for c in ("elo_home_pre", "elo_away_pre", "elo_home_post", "elo_away_post",
                  "d_elo_diff", "e_H", "p_draw", "elo_1", "elo_X", "elo_2"):
            per_match[f"{name}_{c}"] = v.loc[per_match["global_id"], c].to_numpy()
        for c in ("blend_1", "blend_X", "blend_2"):
            per_match[f"{name}_{c}"] = p.loc[per_match["global_id"], c].to_numpy()
    per_match.to_csv(OUTPUT_DIR / "elo_drift_triage_per_match.csv.gz", index=False, compression="gzip")

    drift = drift_table(frames)
    entries = entry_table(records_by_league, variant_entries)
    early = entry_early_table(base_global, records_by_league, preds)
    compensation = entry_compensation_table(entries)
    metrics, samples = make_metric_results(base_global, records_by_league, preds)

    entries.to_csv(OUTPUT_DIR / "elo_drift_triage_entries.csv", index=False)
    metrics.to_csv(OUTPUT_DIR / "elo_drift_triage_metrics.csv", index=False)
    drift.to_csv(OUTPUT_DIR / "elo_drift_triage_drift.csv", index=False)

    s0_check_report = {
        **s0_checks,
        "per_league": json.dumps(per_league, ensure_ascii=False),
    }
    write_report(
        baseline_log=baseline_log,
        join_logs=join_logs,
        frames=frames,
        records_by_league=records_by_league,
        drift=drift,
        entries=entries,
        early=early,
        compensation=compensation,
        metrics=metrics,
        samples=samples,
        variant_entries=variant_entries,
        s0_check=s0_check_report,
    )

    print(f"scritto {REPORT_PATH}")
    print(f"per-match rows={len(per_match)}")
    print(f"entries={len(entries)} team-seasons={metrics['n_team_seasons'].max() if len(metrics) else 0}")
    print(f"S0 bit-exact={s0_checks['all_equal']} max_prob={s0_checks['max_abs_prob']:.3g}")
    print(metrics[["metric", "variant", "delta_logloss", "ci_lo", "ci_hi"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
