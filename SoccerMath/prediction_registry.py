"""
prediction_registry.py - Versionamento del motore predittivo e helper del
Registro Predizioni & Tracking.

Questo modulo e' la fonte UNICA delle costanti di versione del prediction
engine. Non dipende da Streamlit, pandas o da altri moduli applicativi:
puo' essere importato da app.py, dagli script di audit e dai test.

Motivazione
------------
Il 2026-09-04 il motore e' stato corretto per il bug "NG ~99.8%" causato da
lambda ~0 per neopromosse senza dati. Il fix ha introdotto:

  - PRIOR_MATCHES=6 e _shrunk_ratio() (shrinkage empirico-bayesiano verso la
    media di lega) nel percorso xG e nel fallback gol;
  - _clip_lambda() NaN/inf-safe;
  - campo "matches" nei file xG.

Per distinguere le predizioni generate prima di questo fix da quelle generate
dopo, ogni nuova predizione deve essere persistita con un campo esplicito
``model_version``. I record storici senza ``model_version`` NON vengono
considerati automaticamente post-fix: sono classificati come legacy/ambiguo.

Cutoff temporale
----------------
Derivato dal repository git (non inventato):

  - commit del fix:  ae8784d643575593f77241c54a1930e7bd48145f
    (fix(top-mix): elimina NG ~99.8% causato da lambda ~0 per neopromosse senza dati)
  - merge in main:   dc192d5eaa36968380f8bde823ca1abe9792e65d
    (Merge pull request #10)

Una predizione salvata prima dell'author timestamp del commit di fix e'
certamente pre-fix. Una predizione salvata dopo il merge in main e'
certamente post-fix. L'intervallo tra le due date e' trattato come
AMBIGUO e non viene classificato automaticamente.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    TZ_ITALY = ZoneInfo("Europe/Rome")
except Exception:  # pragma: no cover - fallback rarissimo
    from datetime import timedelta
    TZ_ITALY = timezone(timedelta(hours=2))


# ---------------------------------------------------------------------------
# Costanti di versione (unico punto di definizione)
# ---------------------------------------------------------------------------
MODEL_VERSION_FIELD = "model_version"
EXCLUDED_FROM_CURRENT_STATS_FIELD = "excluded_from_current_model_stats"
SALVATO_IL_FIELD = "salvato_il"
DATA_FIELD = "data"
SEASON_FIELD = "stagione"

MODEL_VERSION_CURRENT = "post_shrinkage_v1"
MODEL_VERSION_PRE_FIX = "pre_shrinkage"
MODEL_VERSION_LEGACY = "legacy"
MODEL_VERSION_AMBIGUOUS = "ambiguous"

# Stagione 2026/27 (anno di riferimento usato dal cutoff).
TARGET_SEASON = "2026/2027"

# Cutoff documentato dal repository git.
CUTOFF_COMMIT = "ae8784d643575593f77241c54a1930e7bd48145f"
CUTOFF_COMMIT_SHORT = "ae8784d"
CUTOFF_COMMIT_MESSAGE = (
    "fix(top-mix): elimina NG ~99.8% causato da lambda ~0 per neopromosse senza dati"
)
CUTOFF_MERGE_COMMIT = "dc192d5eaa36968380f8bde823ca1abe9792e65d"
CUTOFF_MERGE_COMMIT_SHORT = "dc192d5"
CUTOFF_MERGE_COMMIT_MESSAGE = "Merge pull request #10 from iFelice/arena/01a06d00-soccermath2-0"

# Author timestamp del commit di fix (UTC).
CUTOFF_COMMIT_TIME = datetime(2026, 9, 4, 15, 40, 10, tzinfo=timezone.utc)
# Timestamp del merge in main (UTC).
CUTOFF_MERGE_TIME = datetime(2026, 9, 4, 16, 50, 17, tzinfo=timezone.utc)

# Etichette UI.
MODEL_LABEL_CURRENT = "✓ Modello attuale"
MODEL_LABEL_PRE_FIX = "⚠️ Pre-fix"
MODEL_LABEL_LEGACY = "Legacy"
MODEL_LABEL_AMBIGUOUS = "⚠️ Ambiguo"
MODEL_LABEL_UNKNOWN = "N/D"

PRE_FIX_TOOLTIP = (
    "Predizione generata prima del fix di regolarizzazione dei piccoli campioni. "
    "Conservata per audit e non inclusa nelle statistiche del modello attuale."
)
CURRENT_MODEL_TOOLTIP = (
    f"Predizione generata con il motore corrente ({MODEL_VERSION_CURRENT}). "
    "Inclusa nelle statistiche del modello attuale."
)


# ---------------------------------------------------------------------------
# Utility base
# ---------------------------------------------------------------------------
def is_dict(obj: Any) -> bool:
    return isinstance(obj, dict)


def get_model_version(entry: Any) -> str:
    """Restituisce la versione esplicita del record, oppure ``legacy``.

    Un record senza ``model_version`` NON viene mai promosso a
    ``post_shrinkage_v1``: resta legacy finche' un processo di migrazione
    esplicita non lo classifica.
    """
    if not is_dict(entry):
        return MODEL_VERSION_LEGACY
    mv = entry.get(MODEL_VERSION_FIELD)
    if mv is None:
        return MODEL_VERSION_LEGACY
    mv = str(mv).strip().lower()
    if not mv:
        return MODEL_VERSION_LEGACY
    if mv in {MODEL_VERSION_CURRENT, MODEL_VERSION_PRE_FIX, MODEL_VERSION_LEGACY, MODEL_VERSION_AMBIGUOUS}:
        return mv
    return MODEL_VERSION_LEGACY


def model_category(entry: Any) -> str:
    """Categoria semantica usata dalla UI (non e' un campo persistito)."""
    mv = get_model_version(entry)
    if mv == MODEL_VERSION_CURRENT:
        return "current"
    if mv == MODEL_VERSION_PRE_FIX:
        return "pre_fix"
    if mv == MODEL_VERSION_AMBIGUOUS:
        return "ambiguous"
    return "legacy"


def model_label(entry: Any) -> str:
    cat = model_category(entry)
    return {
        "current": MODEL_LABEL_CURRENT,
        "pre_fix": MODEL_LABEL_PRE_FIX,
        "ambiguous": MODEL_LABEL_AMBIGUOUS,
        "legacy": MODEL_LABEL_LEGACY,
    }.get(cat, MODEL_LABEL_UNKNOWN)


def is_current_model(entry: Any) -> bool:
    """True solo per ``model_version == post_shrinkage_v1``.

    Non considera automaticamente post-fix i record legacy/ambiguo.
    """
    return get_model_version(entry) == MODEL_VERSION_CURRENT


def is_excluded_from_stats(entry: Any) -> bool:
    """Indica se il record deve essere escluso dalle metriche del modello attuale."""
    if not is_dict(entry):
        return True
    return not is_current_model(entry) or bool(entry.get(EXCLUDED_FROM_CURRENT_STATS_FIELD))


def new_prediction_metadata() -> Dict[str, Any]:
    """Metadati assegnati alle NUOVE predizioni al momento del salvataggio."""
    return {
        MODEL_VERSION_FIELD: MODEL_VERSION_CURRENT,
        EXCLUDED_FROM_CURRENT_STATS_FIELD: False,
    }


# ---------------------------------------------------------------------------
# Parsing date / stagione
# ---------------------------------------------------------------------------
def _as_aware(dt: Optional[datetime], tz: Any = TZ_ITALY) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def parse_datetime(value: Any, default_tz: Any = TZ_ITALY) -> Optional[datetime]:
    """Parser tollerante dei timestamp salvati nel registro.

    Supporta i formati usati da save_prediction_entry() e dai record legacy:
    dd/mm/yyyy HH:MM[:SS], ISO 8601 con/without timezone, dd/mm/yyyy (solo data).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_aware(value, default_tz)
    text = str(value).strip()
    if not text:
        return None
    for fmt in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return _as_aware(datetime.strptime(text, fmt), default_tz)
        except (ValueError, TypeError):
            continue
    return None


# Formati accettati dal parser di visualizzazione del Registro. L'italiano
# "DD/MM/YYYY [HH:MM[:SS]]" e' il formato scritto da save_prediction_entry
# (format_date_italy + strftime "%d/%m/%Y %H:%M"); i formati ISO sono presenti
# nei record legacy e NON vengono migrati: vengono solo interpretati in lettura.
REGISTRY_DATE_FORMATS = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def _to_rome_naive(dt: datetime) -> datetime:
    """Riporta un datetime a wall-clock Europe/Rome SENZA tzinfo.

    - aware (es. ISO legacy ``...Z`` / ``...+00:00``): conversione reale in
      Europe/Rome, poi rimozione del tzinfo;
    - naive (formato italiano salvato dall'app): il valore e' gia' l'ora
      legale italiana, quindi viene conservato cosi' com'e'.

    Il risultato naive e' il tipo corretto per la colonna datetime di
    ``st.dataframe``: le colonne naive vengono renderizzate esattamente col
    loro wall-clock (nessuno shift sul fuso del browser) e l'ordinamento
    manuale sull'intestazione resta cronologico.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(TZ_ITALY)
    return dt.replace(tzinfo=None)


def parse_registry_display_datetime(value: Any) -> Optional[datetime]:
    """Parser del campo ``data`` per la UI del Registro Predizioni.

    Converte in un vero ``datetime`` naive espresso come wall-clock di
    Europe/Rome, senza toccare i dati persistiti. Restituisce ``None`` per
    valori mancanti o non validi (che diventano ``NaT`` nel dataframe).

    Formati supportati:
      - ``DD/MM/YYYY HH:MM`` e ``DD/MM/YYYY HH:MM:SS`` (formato standard del registro);
      - ``DD/MM/YYYY`` (solo data -> mezzanotte);
      - ISO 8601 legacy con o senza timezone (aware -> convertito in Europe/Rome);
      - oggetti ``datetime`` / ``pandas.Timestamp`` gia' pronti;
      - ``None`` / stringhe vuote / valori non parsabili -> ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return _to_rome_naive(value)
    if not isinstance(value, str):
        # pd.Timestamp e' un sottoclass di datetime (gia' gestito sopra);
        # qui si catturano al massimo wrapper esotici, altrimenti e' NaN/NaN-like.
        to_py = getattr(value, "to_pydatetime", None)
        if callable(to_py):
            try:
                dt = to_py()
                if isinstance(dt, datetime):
                    return _to_rome_naive(dt)
            except Exception:
                return None
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in REGISTRY_DATE_FORMATS:
        try:
            return _to_rome_naive(datetime.strptime(text, fmt))
        except (ValueError, TypeError):
            continue
    # Ultimo tentativo: ISO con varianti che strptime non copre
    # (frazioni di secondo senza tz, offset ``Z``, ...).
    try:
        return _to_rome_naive(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except (ValueError, TypeError):
        return None


def build_registry_datetime_column(values: Any) -> Any:
    """Converte la colonna ``data`` del Registro in una Series ``datetime64`` reale.

    Gli elementi non validi diventano ``NaT``. pandas viene importato qui in
    modo pigro per mantenere il resto del modulo importabile senza dipendenze
    (il parser puro resta la fonte unica della logica di parsing).
    """
    import pandas as pd

    # Nessun parse diretto di pd.to_datetime sulle stringhe: il parsing passa
    # SOLO da parse_registry_display_datetime (giorno-prima, italiano) per non
    # far inferire a pandas formati ambigui (es. 05/09 come maggio/settembre).
    series = values if isinstance(values, pd.Series) else pd.Series(list(values), dtype=object)
    return pd.to_datetime(series.map(parse_registry_display_datetime))


def normalize_season(season: Any) -> str:
    """Normalizza le stringhe di stagione (2026/2027, 2026/27, 26/27 etc.)."""
    if season is None:
        return ""
    text = str(season).strip()
    # 4 cifre / 4 cifre oppure 4 cifre / 2 cifre
    m = re.match(r"^(\d{4})\s*/\s*(\d{2,4})$", text)
    if m:
        y1 = int(m.group(1))
        y2 = int(m.group(2))
        if y2 < 100:
            y2 += y1 // 100 * 100
            if y2 <= y1:
                y2 += 100
        return f"{y1}/{y2}"
    # 2 cifre / 2 cifre
    m = re.match(r"^(\d{2})\s*/\s*(\d{2})$", text)
    if m:
        y1 = 2000 + int(m.group(1))
        y2 = 2000 + int(m.group(2))
        return f"{y1}/{y2}"
    return text


def season_from_entry(entry: Any) -> str:
    """Deriva la stagione dal campo esplicito o dalla data della partita."""
    if not is_dict(entry):
        return ""
    explicit = entry.get(SEASON_FIELD)
    if explicit is not None and str(explicit).strip():
        return normalize_season(explicit)
    dt = parse_datetime(entry.get(DATA_FIELD))
    if dt is not None:
        dt_local = dt.astimezone(TZ_ITALY)
        if dt_local.month >= 8:
            return f"{dt_local.year}/{dt_local.year + 1}"
        return f"{dt_local.year - 1}/{dt_local.year}"
    return ""


def entry_generation_time(entry: Any) -> Tuple[Optional[datetime], Optional[str]]:
    """Restituisce (timestamp UTC, campo sorgente).

    La fonte privilegiata e' ``salvato_il`` (momento in cui la predizione e'
    stata generata/salvata). Se manca, non usiamo automaticamente la data
    della partita come prova di generazione: il chiamante decidera' se
    considerare il record ambiguo.
    """
    if not is_dict(entry):
        return None, None
    dt = parse_datetime(entry.get(SALVATO_IL_FIELD))
    if dt is not None:
        return dt, SALVATO_IL_FIELD
    return None, None


def entry_era_by_time(entry: Any) -> str:
    """Era temporale certa/ambigua del record: pre, ambiguous, post o unknown."""
    dt, _ = entry_generation_time(entry)
    if dt is None:
        return "unknown"
    if dt < CUTOFF_COMMIT_TIME:
        return "pre"
    if dt >= CUTOFF_MERGE_TIME:
        return "post"
    return "ambiguous"


def should_tag_pre_fix(entry: Any) -> bool:
    """Criterio esclusivamente temporale per la stagione 2026/27.

    Non usa esito, mercato, probabilita' o risultato.

    Ritorna True solo quando:
      - il record non ha gia' model_version (o e' legacy/ambiguo esplicito);
      - la stagione e' 2026/2027;
      - l'orario di salvataggio e' CERTAMENTE prima del commit di fix.
    """
    if not is_dict(entry):
        return False
    if get_model_version(entry) == MODEL_VERSION_CURRENT:
        return False
    if get_model_version(entry) == MODEL_VERSION_PRE_FIX:
        return False
    # Se esiste gia' un model_version esplicito diverso da "legacy", non
    # sovrascrivo la classificazione (in particolare "ambiguous" o versioni
    # future sconosciute).
    raw = entry.get(MODEL_VERSION_FIELD)
    if raw is not None and str(raw).strip():
        if str(raw).strip().lower() != MODEL_VERSION_LEGACY:
            return False
    if normalize_season(season_from_entry(entry)) != TARGET_SEASON:
        return False
    return entry_era_by_time(entry) == "pre"


def classify_entry(entry: Any) -> Dict[str, Any]:
    """Classificazione usata dal report di migrazione.

    Categorie:
      - already_pre_shrinkage
      - to_tag_pre_shrinkage
      - already_post_shrinkage_v1
      - ambiguous
      - legacy
    """
    if not is_dict(entry):
        return {"status": "legacy", "category": "legacy", "model_version": MODEL_VERSION_LEGACY,
                "season": "", "era": "unknown", "will_tag": False}
    mv = get_model_version(entry)
    season = normalize_season(season_from_entry(entry))
    era = entry_era_by_time(entry)
    raw_mv = entry.get(MODEL_VERSION_FIELD)
    has_explicit_mv = raw_mv is not None and str(raw_mv).strip()
    # Una classificazione esplicita diversa da legacy/current/pre non viene
    # sovrascritta automaticamente dal criterio temporale.
    explicit_other = has_explicit_mv and str(raw_mv).strip().lower() not in {
        MODEL_VERSION_LEGACY, MODEL_VERSION_CURRENT, MODEL_VERSION_PRE_FIX,
    }
    if mv == MODEL_VERSION_CURRENT:
        status = "already_post_shrinkage_v1"
    elif mv == MODEL_VERSION_PRE_FIX:
        status = "already_pre_shrinkage"
    elif explicit_other:
        status = "ambiguous" if mv == MODEL_VERSION_AMBIGUOUS else "legacy"
    elif season == TARGET_SEASON and era == "pre":
        status = "to_tag_pre_shrinkage"
    elif season == TARGET_SEASON and era == "ambiguous":
        status = "ambiguous"
    elif season == TARGET_SEASON and era == "unknown":
        status = "ambiguous"
    elif season == TARGET_SEASON and era == "post":
        # Dopo il fix ma senza versionamento: resta ambiguo/legacy. Non viene
        # promosso automaticamente a post_shrinkage_v1.
        status = "ambiguous"
    else:
        status = "legacy"
    return {
        "status": status,
        "category": status,
        "model_version": mv,
        "season": season,
        "era": era,
        "will_tag": status == "to_tag_pre_shrinkage",
    }


# ---------------------------------------------------------------------------
# Persistenza file / backup
# ---------------------------------------------------------------------------
def load_predictions_file(path: str | Path) -> List[Dict[str, Any]]:
    """Carica un file nel formato {data: [...]} oppure una lista diretta."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    if isinstance(data, list):
        return data
    raise ValueError(f"Formato non riconosciuto in {p}")


def write_predictions_file(path: str | Path, preds: Iterable[Dict[str, Any]],
                           ensure_ascii: bool = False, indent: int = 2) -> Path:
    """Scrive il registro mantenendo il formato {data: [...]}."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"data": list(preds)}, f, ensure_ascii=ensure_ascii, indent=indent)
    return p


def backup_prediction_file(path: str | Path, timestamp: Optional[datetime] = None) -> Optional[Path]:
    """Crea un backup integrale del file se esiste.

    Il backup usa il suffisso ``.json.bak`` per rispettare la regola di
    ``SoccerMath/.gitignore`` (``database/*.json.bak``).
    """
    p = Path(path)
    if not p.exists():
        return None
    import shutil
    ts = timestamp or datetime.now(TZ_ITALY)
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    backup = p.with_name(f"{p.stem}_{stamp}{p.suffix}.bak")
    shutil.copy2(p, backup)
    return backup


# ---------------------------------------------------------------------------
# Statistiche
# ---------------------------------------------------------------------------
def compute_stats(entries: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    lst = list(entries)
    wins = 0
    losses = 0
    pending = 0
    for e in lst:
        esito = e.get("esito")
        if esito == "✅":
            wins += 1
        elif esito == "❌":
            losses += 1
        else:
            pending += 1
    decided = wins + losses
    win_rate = (wins / decided * 100.0) if decided else 0.0
    return {
        "total": len(lst),
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "decided": decided,
        "win_rate": win_rate,
        "entries": lst,
    }


def stats_current_model(entries: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return compute_stats([e for e in entries if is_current_model(e) and not is_excluded_from_stats(e)])


def stats_historical(entries: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Storico/audit per la UI: include pre-fix, legacy e ambiguo, esclude current."""
    return compute_stats([e for e in entries if not is_current_model(e)])


def stats_all(entries: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return compute_stats(entries)


def tag_pre_fix(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Restituisce una copia del record con i campi pre-fix, senza alterare
    pronostico, probabilita', risultato, esito, quota o timestamp."""
    updated = dict(entry)
    updated[MODEL_VERSION_FIELD] = MODEL_VERSION_PRE_FIX
    updated[EXCLUDED_FROM_CURRENT_STATS_FIELD] = True
    return updated
