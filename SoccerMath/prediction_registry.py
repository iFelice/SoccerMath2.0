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

  - commit del fix sul branch:  ae8784d643575593f77241c54a1930e7bd48145f
    (fix(top-mix): elimina NG ~99.8% causato da lambda ~0 per neopromosse senza dati)
  - merge in main:   dc192d5eaa36968380f8bde823ca1abe9792e65d
    (Merge pull request #10)

Il criterio corretto di classificazione usa il momento in cui il fix e'
entrato in ``main`` (merge commit), NON il timestamp del commit sul branch.
Solo dal merge in main il modello corretto era disponibile all'app di
produzione.

Quindi:
  - predizioni della stagione 2026/27 salvate PRIMA del merge -> pre_shrinkage
  - predizioni della stagione 2026/27 salvate DOPO il merge, senza
    model_version -> ambiguous (non promosse a post_shrinkage_v1)
  - predizioni di stagioni precedenti, senza model_version -> legacy
  - predizioni gia' dotate di model_version -> non riclassificate
"""

from __future__ import annotations

import hashlib
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
# Tracciamento dell'origine (audit/margini_migliorabili_topmix.md §7)
# ---------------------------------------------------------------------------
# I tre problemi "blocking" del Registro si riducono a uno: le righe generate da
# Top Mix / Analisi Rapida / Billy condividono una sola chiave (match_id) e un
# solo campo (tipo) derivato dal testo libero del pronostico. Qui stanno le
# chiavi esplicite: ``origin`` (chi ha generato la previsione) e
# ``selector_version`` (QUALE selettore l'ha generata).
ORIGIN_FIELD = "origin"
ORIGIN_TOP_MIX = "top_mix"
ORIGIN_ANALISI_RAPIDA = "analisi_rapida"
ORIGIN_BILLY = "billy"
ORIGIN_UNKNOWN = "unknown"
ORIGINI_NOTE = (ORIGIN_TOP_MIX, ORIGIN_ANALISI_RAPIDA, ORIGIN_BILLY, ORIGIN_UNKNOWN)

# Etichetta mostrata nel Registro: sostituisce il test ``"Top Mix" in pronostico``.
TIPO_BY_ORIGIN = {
    ORIGIN_TOP_MIX: "Top Mix",
    ORIGIN_ANALISI_RAPIDA: "Analisi Rapida",
    ORIGIN_BILLY: "Billy",
    ORIGIN_UNKNOWN: "Analisi",
}

# Versione del SELETTORE (non del modello): va alzata OGNI volta che cambiano
# argmax sui mercati, soglie 0,55/0,60, peso del blend o il filtro di
# disaccordo, perche' e' parte della chiave di dedup e dell'aggregazione.
SELECTOR_VERSION_FIELD = "selector_version"
SELECTOR_VERSION_CURRENT = "topmix_gate025_ens06_v1"

# ---------------------------------------------------------------------------
# Gate shadow (audit/margini_migliorabili_topmix.md §11quater, piano §9 punto 4)
# ---------------------------------------------------------------------------
# Modalita' OMBRA del veto di disaccordo ``abs(poisson - elo) < 0.25``: il gate
# non scarta piu' la partita, ma applica una penalita' CONTINUA alla confidence
# (mai un secondo taglio secco a un'altra soglia). Nessuna di queste costanti
# tocca il selettore reale (``seleziona_riga_top_mix`` resta esattamente come
# in 32e3eda): servono solo ai campi shadow persistiti nel registro e agli
# strumenti di audit che li leggono.
GATE_SHADOW_CONFIDENCE_FIELD = "gate_shadow_confidence"
GATE_SHADOW_AMMESSA_FIELD = "gate_shadow_ammessa"
# Tolleranza del veto di produzione |P-E| < 0.25: la penalita' ombra ci si
# ancora. A d = 0.25 la confidence si DIMEZZA invece di azzerarsi
# (fattore 0.25/(0.25+0.25) = 1/2); a d = 0 resta identica (fattore 1).
GATE_SHADOW_TOLLERANZA = 0.25
# Soglie minime di ammissione della variante ombra: STESSI valori letterali
# del selettore (0.55 blend 1X2 con Elo, 0.60 altrimenti). L'ammissione ombra
# e' un solo confronto ``conf_shadow >= min_conf``: la penalita' ha gia'
# assorbito il veto, quindi i due filtri di oggi collassano in uno.
GATE_SHADOW_MIN_CONF_1X2 = 0.55
GATE_SHADOW_MIN_CONF_TOTALI = 0.60
# Mercati su cui l'Elo non viene mai letto (O/U, GG/NG): li' il disaccordo e'
# zero per costruzione e la variante ombra coincide con la confidence reale.
MERCATI_SENZA_ELO = ("Over 2.5", "Under 2.5", "GG", "NG")

CALCULATION_ID_FIELD = "calculation_id"
RANK_FIELD = "rank"
KICKOFF_UTC_FIELD = "kickoff_utc"
SNAPSHOT_SHA_FIELD = "data_snapshot_sha"
# Nomi identici alle chiavi gia' usate dalle righe del Top Mix
# (``fetch_and_calc_top_mix`` ritorna "poisson"/"elo" in percentuale).
POISSON_FIELD = "poisson"
ELO_FIELD = "elo"
ELO_DISPONIBILE_FIELD = "elo_disponibile"
PROB_FIELD = "prob_sicuro"
ESITO_FIELD = "esito"
MERCATO_FIELD = "mercato_standard"
ESITO_VINTO = "\u2705"
ESITO_PERSO = "\u274c"
ESITO_ATTESA = "\u23f3"


# ---------------------------------------------------------------------------
# Formula del gate shadow (funzioni pure, importabili anche senza app.py)
# ---------------------------------------------------------------------------
def _in_frazione(valore: Any) -> Optional[float]:
    """Riconduce un valore salvato nel registro a una frazione in [0, 1].

    Stessa convenzione di ``prob_of_entry``: i campi ``poisson``/``elo`` sono
    persistiti in percentuale (es. 70.0), ``prob_sicuro`` come frazione.
    """
    if isinstance(valore, bool) or not isinstance(valore, (int, float)):
        return None
    v = float(valore)
    return v / 100.0 if v > 1.0 else v


def gate_shadow_confidence(confidence: Any, disaccordo: Any) -> Optional[float]:
    """Confidence della variante OMBRA: ``conf * 0.25 / (0.25 + d)``.

    Definizione esatta (referto ``audit/margini_migliorabili_topmix.md``
    §11quater). ``d = |poisson - elo|`` e' il disaccordo fra i due modelli; la
    tolleranza 0.25 e' quella del veto di produzione. Proprieta':

    - moltiplicativa e mai negativa: resta in (0, 1] per ogni ``d`` finito,
      senza clamp (una penalita' sottrattiva richiederebbe un secondo taglio
      secco a zero per ``d`` grande: qui non esiste);
    - monotona decrescente in ``d`` (piu' i modelli divergono, meno fiducia);
    - continua anche al punto di veto: ``g(0)=1``, ``g(0.25)=1/2``, ``g(d)``
      non ha salti, quindi non e' un secondo taglio a un'altra soglia;
    - per i mercati senza Elo (O/U, GG/NG) o a Elo assente ``d = 0`` per
      costruzione: la confidence ombra coincide con quella reale.

    ``None`` se gli ingressi non sono numerici (il chiamante omette i campi
    shadow: il salvataggio reale non viene toccato).
    """
    conf = _in_frazione(confidence)
    if conf is None:
        return None
    if isinstance(disaccordo, bool) or not isinstance(disaccordo, (int, float)):
        d = 0.0
    else:
        d = float(disaccordo)
        if d < 0.0 or d != d:          # disaccordo negativo o NaN: nessun disaccordo
            d = 0.0
    return conf * (GATE_SHADOW_TOLLERANZA / (GATE_SHADOW_TOLLERANZA + d))


def gate_shadow_min_conf(market: Any, elo_disponibile: Any) -> float:
    """Soglia della variante ombra per una riga: 0.55 solo per 1X2 con Elo.

    Ricalca il ramo del selettore reale: i totali (e l'1X2 a Elo assente)
    pretendono 0.60 perche' la confidence e' Poisson puro.
    """
    if market not in MERCATI_SENZA_ELO and elo_disponibile is True:
        return GATE_SHADOW_MIN_CONF_1X2
    return GATE_SHADOW_MIN_CONF_TOTALI


def gate_shadow_fields_from_row(market: Any, prob: Any, poisson: Any, elo: Any,
                                elo_disponibile: Any) -> Optional[Dict[str, Any]]:
    """Campi shadow calcolati sui VALORI PERSISTITI di una riga del registro.

    Ritorna ``{GATE_SHADOW_CONFIDENCE_FIELD: float, GATE_SHADOW_AMMESSA_FIELD:
    bool}`` oppure ``None`` se la riga non permette il calcolo (chiamante: il
    salvataggio reale resta identico, i campi semplicemente non vengono
    aggiunti).

    Il disaccordo e' ricavato dalle componenti ``poisson``/``elo`` della riga
    stessa, cosi' il valore persistito e' riproducibile dal solo record: le
    componenti sono arrotondate allo 0.1 pp dal selettore, quindi ``d`` (e di
    conseguenza ``gate_shadow_confidence``) coincide con il valore esatto a
    meno di <= 0.001 di disaccordo (<= ~0.005 sulla confidence nel caso
    peggiore). Dove l'Elo non e' stato letto il selettore salva ``elo ==
    poisson`` (o ``elo`` assente con ``elo_disponibile=False``): in entrambi i
    casi ``d = 0``.
    """
    if market is None:
        return None
    conf = _in_frazione(prob)
    p = _in_frazione(poisson)
    if conf is None or p is None:
        return None
    if elo_disponibile is True:
        e = _in_frazione(elo)
        if e is None:
            # Flag dice che l'Elo e' stato letto ma il valore manca: riga
            # anomala, meglio non inventare un numero -> campi assenti.
            return None
        d = abs(p - e)
    else:
        # L'Elo non e' stato letto: il selettore ha usato elo_prob =
        # poisson_prob, quindi per costruzione il disaccordo e' zero.
        d = 0.0
    min_conf = gate_shadow_min_conf(market, elo_disponibile)
    conf_shadow = gate_shadow_confidence(conf, d)
    if conf_shadow is None:
        return None
    return {
        GATE_SHADOW_CONFIDENCE_FIELD: conf_shadow,
        GATE_SHADOW_AMMESSA_FIELD: conf_shadow >= min_conf,
    }


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
    """Era temporale del record rispetto al merge del fix in main.

    Il cutoff di produzione e' il merge commit ``dc192d5`` in main
    (``CUTOFF_MERGE_TIME``), NON il timestamp del commit del fix sul branch.
    Solo dal merge il modello corretto era disponibile all'app.

    - ``salvato_il`` < merge time  -> "pre"
    - ``salvato_il`` >= merge time -> "post"
    - nessun timestamp disponibile -> "unknown"
    """
    dt, _ = entry_generation_time(entry)
    if dt is None:
        return "unknown"
    if dt < CUTOFF_MERGE_TIME:
        return "pre"
    return "post"


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
        # Prima del merge del fix in main: certamente pre-shrinkage.
        status = "to_tag_pre_shrinkage"
    elif season == TARGET_SEASON and era == "post":
        # Dopo il merge in main ma senza model_version: ambiguo.
        # Non viene promosso automaticamente a post_shrinkage_v1.
        status = "ambiguous"
    elif season == TARGET_SEASON and era == "unknown":
        # Nessun timestamp disponibile per la classificazione: ambiguo.
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


# ---------------------------------------------------------------------------
# Origine, chiavi di dedup, upsert
# ---------------------------------------------------------------------------
def origin_from_text(pronostico: Any) -> str:
    """Fallback storico: ricava l'origine dal testo libero del pronostico.

    Usato SOLO quando il chiamante non passa ``origin`` esplicito (record
    legacy o percorsi di scrittura vecchi). Il testo e' un'euristica: le
    scritture nuove devono sempre passare l'origine esplicita.
    """
    t = str(pronostico or "").lower()
    if "top mix" in t:
        return ORIGIN_TOP_MIX
    if "billy" in t or "fallback" in t:
        return ORIGIN_BILLY
    if "poisson auto" in t or "analisi" in t:
        return ORIGIN_ANALISI_RAPIDA
    return ORIGIN_UNKNOWN


def resolve_origin(origin: Any = None, pronostico: Any = None) -> str:
    """Origine normalizzata: quella esplicita vince, il testo e' il fallback."""
    if origin:
        o = str(origin).strip().lower()
        if o in ORIGINI_NOTE:
            return o
        return ORIGIN_UNKNOWN
    return origin_from_text(pronostico)


def tipo_for_origin(origin: Any) -> str:
    """Etichetta da mostrare nel Registro (sostituisce il test sul pronostico)."""
    return TIPO_BY_ORIGIN.get(str(origin or "").strip().lower(), TIPO_BY_ORIGIN[ORIGIN_UNKNOWN])


def origin_of(entry: Any) -> str:
    if not is_dict(entry):
        return ORIGIN_UNKNOWN
    o = str(entry.get(ORIGIN_FIELD) or "").strip().lower()
    if o in ORIGINI_NOTE:
        return o
    # Record scritti prima del campo origin: si risale dal tipo/ dal testo.
    tipo = str(entry.get("tipo") or "").strip().lower()
    if tipo == "top mix":
        return ORIGIN_TOP_MIX
    if tipo == "billy":
        return ORIGIN_BILLY
    if tipo == "analisi rapida":
        return ORIGIN_ANALISI_RAPIDA
    return origin_from_text(entry.get("pronostico_sicuro"))


def selector_version_of(entry: Any) -> str:
    if not is_dict(entry):
        return ""
    return str(entry.get(SELECTOR_VERSION_FIELD) or "")


def dedup_key(entry: Any) -> Tuple[Any, str, str]:
    """Chiave di unicita' di una previsione.

    Non piu' il solo ``match_id``: la stessa partita puo' legittimamente avere
    UNA riga per origine (Top Mix, Analisi Rapida, Billy) e una riga per versione
    del selettore. Il dedup per solo match_id faceva perdere la riga Top Mix
    quando Analisi Rapida aveva salvato per prima (problema ``dedup_match_id``,
    blocking, in results/topmix_registry_tracking.json).
    """
    if not is_dict(entry):
        return (None, ORIGIN_UNKNOWN, "")
    mid = entry.get("match_id")
    return (None if mid is None else str(mid), origin_of(entry), selector_version_of(entry))


def upsert_prediction_entry(preds: Iterable[Dict[str, Any]],
                            entry: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    """Inserisce o aggiorna una previsione, senza mai toccarne una gia' giudicata.

    Ritorna ``(lista_aggiornata, azione)`` con azione in
    ``{"aggiunta", "aggiornata", "gia_graduata", "senza_chiave"}``.

    - un ricalcolo della STESSA previsione (stesso match_id + origine +
      selector_version) la SOSTITUISCE: prima il record restava congelato alla
      prima scrittura, quindi il registro non descriveva piu' il modello live;
    - una previsione con esito gia' ``\\u2705``/``\\u274c`` NON viene mai
      sovrascritta: e' l'unica riga che costa denaro in prospettiva;
    - origini diverse sulla stessa partita coesistono (e' il dato che serve per
      confrontare Top Mix vs Analisi Rapida).
    """
    lst = list(preds or [])
    chiave = dedup_key(entry)
    if chiave[0] is None:
        lst.append(entry)
        return lst, "senza_chiave"
    for i, p in enumerate(lst):
        if dedup_key(p) != chiave:
            continue
        if is_dict(p) and p.get(ESITO_FIELD) in (ESITO_VINTO, ESITO_PERSO):
            return lst, "gia_graduata"
        aggiornato = dict(entry)
        # Conserva la prima scrittura: un ricalcolo non cancella quando la
        # previsione era stata presa.
        if is_dict(p) and p.get(SALVATO_IL_FIELD):
            aggiornato.setdefault("salvato_il_originario", p[SALVATO_IL_FIELD])
        lst[i] = aggiornato
        return lst, "aggiornata"
    lst.append(entry)
    return lst, "aggiunta"


# ---------------------------------------------------------------------------
# Identita' del calcolo e fingerprint dei dati
# ---------------------------------------------------------------------------
def build_calculation_id(match_id: Any, origin: Any, selector_version: Any,
                         kickoff_utc: Any = None, snapshot_sha: Any = None,
                         rank: Any = None) -> str:
    """Id deterministico di una scrittura: stesso input -> stesso id."""
    parti = [str(match_id), str(origin or ""), str(selector_version or ""),
             str(kickoff_utc or ""), str(snapshot_sha or ""), str(rank if rank is not None else "")]
    return hashlib.sha1("|".join(parti).encode("utf-8")).hexdigest()[:16]


# Il registro e' l'OUTPUT del calcolo: includerlo nel fingerprint dei dati di
# input lo farebbe cambiare a ogni scrittura (e il calculation_id di una stessa
# previsione non sarebbe piu' deterministico).
NOMI_ESCLUSI_DAI_DATI = ("predictions.json",)


def snapshot_fingerprint(directory: Any, estensioni: Tuple[str, ...] = (".csv", ".json"),
                         max_file: int = 500, escludi: Tuple[str, ...] = NOMI_ESCLUSI_DAI_DATI) -> str:
    """Hash breve dei file di dati usati dal calcolo (12 caratteri esadecimali).

    Solo il livello ``directory`` immediato (niente ricorsione negli archivi
    partita, che sono migliaia di file): una chiamata costa pochi ``stat()`` e
    basta a dire SE il database e' cambiato fra due salvataggi. Serve per
    distinguere un dato vecchio da un ricalcolo a dati invariati.
    """
    p = Path(str(directory)) if directory else None
    if p is None or not p.is_dir():
        return ""
    righe = []
    try:
        for child in sorted(p.iterdir(), key=lambda x: x.name):
            if len(righe) >= max_file:
                break
            if not child.is_file():
                continue
            if estensioni and child.suffix.lower() not in estensioni:
                continue
            if child.name in escludi:
                continue
            try:
                st = child.stat()
            except OSError:
                continue
            righe.append(f"{child.name}:{st.st_size}:{st.st_mtime_ns}")
    except OSError:
        return ""
    if not righe:
        return ""
    return hashlib.sha1("\n".join(righe).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Grading unico (elimina la divergenza fra i due rami di aggiorna_risultati_reali)
# ---------------------------------------------------------------------------
def _as_goal(value: Any) -> Optional[int]:
    """Gol come intero non negativo; float integri accettati, NaN/None/str no."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return int(value) if float(value).is_integer() and value >= 0 else None
    return None


# Il ramo "giornata 0" (chiamata per match_id) graduava 14 mercati, il ramo
# "loop per giornata" solo 7: un record OVER_1.5/1X/X2/12 salvato dal secondo
# ramo restava ⏳ per sempre, in silenzio. Unica fonte: questa tabella.
_GRADING = {
    "UNDER_1.5": lambda gh, ga: (gh + ga) < 2,
    "OVER_1.5": lambda gh, ga: (gh + ga) > 1,
    "UNDER_2.5": lambda gh, ga: (gh + ga) < 3,
    "OVER_2.5": lambda gh, ga: (gh + ga) > 2,
    "UNDER_3.5": lambda gh, ga: (gh + ga) < 4,
    "OVER_3.5": lambda gh, ga: (gh + ga) > 3,
    "1X": lambda gh, ga: gh >= ga,
    "X2": lambda gh, ga: ga >= gh,
    "12": lambda gh, ga: gh != ga,
    "GG": lambda gh, ga: gh > 0 and ga > 0,
    "NG": lambda gh, ga: gh == 0 or ga == 0,
    "X": lambda gh, ga: gh == ga,
    "1": lambda gh, ga: gh > ga,
    "2": lambda gh, ga: ga > gh,
}

MERCATI_GRADABILI = tuple(sorted(_GRADING))


def esito_mercato(mercato: Any, gol_casa: Any, gol_trasferta: Any) -> Optional[str]:
    """ESITO (``\\u2705``/``\\u274c``) di un mercato sul risultato finale.

    Ritorna ``None`` se il mercato non e' riconosciuto o i gol non sono due
    interi: il chiamante deve tenere ``\\u23f3``, mai inventare un esito.
    """
    code = str(mercato or "").strip().upper()
    if code == "ALTRO":
        return None
    fn = _GRADING.get(code)
    if fn is None:
        return None
    h = _as_goal(gol_casa)
    a = _as_goal(gol_trasferta)
    if h is None or a is None:
        return None
    return ESITO_VINTO if fn(h, a) else ESITO_PERSO


# ---------------------------------------------------------------------------
# Igiene delle righe mostrate/salvate (Top Mix)
# ---------------------------------------------------------------------------
def parse_kickoff(value: Any) -> Optional[datetime]:
    """``utcDate`` ISO (con o senza ``Z``) in datetime aware UTC; None se assente/non valido."""
    if isinstance(value, datetime):
        dt = value
    elif not value or not isinstance(value, str):
        return None
    else:
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def righe_non_iniziate(righe: Iterable[Dict[str, Any]], ora: Any = None,
                       campo_kickoff: str = "utcDate") -> Tuple[List[Dict[str, Any]], int]:
    """Scarta le righe il cui kickoff e' gia' passato.

    ``fetch_and_calc_top_mix`` e' ``@st.cache_data(ttl=1800)`` SENZA argomenti:
    il ``now`` calcolato dentro la funzione e' congelato per 30 minuti, quindi
    il risultato cached puo' contenere partite gia' iniziate (problema
    ``cache_30min``). Non si tocca ne' il TTL ne' gli argomenti della cache
    (un argomento per minuto = 5 chiamate API al minuto, contro il limite di
    10/min free di football-data): si rifiltra qui, a costo zero, prima di
    mostrare e di salvare.

    Le righe senza kickoff interpretabile RESTANO (un dato mancante non deve
    far sparire una previsione gia' presa): torna ``(tenute, scartate)``.
    """
    if ora is None:
        ora = datetime.now(timezone.utc)
    ora = parse_kickoff(ora) or datetime.now(timezone.utc)
    tenute: List[Dict[str, Any]] = []
    scartate = 0
    for r in righe or []:
        if not is_dict(r):
            continue
        kickoff = parse_kickoff(r.get(campo_kickoff))
        if kickoff is not None and kickoff <= ora:
            scartate += 1
            continue
        tenute.append(r)
    return tenute, scartate


# ---------------------------------------------------------------------------
# Affidabilita' (Brier) del Registro: dato gia' presente, mai esposto
# ---------------------------------------------------------------------------
def prob_of_entry(entry: Any) -> Optional[float]:
    """Probabilita' dichiarata in [0,1] dal campo ``prob_sicuro``.

    Il campo e' persistito in percentuale (61.0). I valori in (1, 100] sono
    letti come percentuale, quelli in [0, 1] come frazione: una previsione sotto
    l'1% non esiste (soglie 0,55/0,60), quindi la zona ambigua non e' raggiunta
    dai dati reali.
    """
    if not is_dict(entry):
        return None
    v = entry.get(PROB_FIELD)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    p = float(v) / 100.0 if float(v) > 1.0 else float(v)
    if not 0.0 <= p <= 1.0:
        return None
    return p


def outcome_of_entry(entry: Any) -> Optional[int]:
    """1 se vinta, 0 se persa, ``None`` se ancora in attesa o non riconosciuta."""
    if not is_dict(entry):
        return None
    esito = entry.get(ESITO_FIELD)
    if esito == ESITO_VINTO:
        return 1
    if esito == ESITO_PERSO:
        return 0
    return None


def brier_of_entry(entry: Any) -> Optional[float]:
    p = prob_of_entry(entry)
    y = outcome_of_entry(entry)
    if p is None or y is None:
        return None
    return (p - y) ** 2


def compute_calibration_stats(entries: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Win rate + Brier + gap di calibrazione sullo stesso sottoinsieme.

    Il Registro finora esponeva SOLO il win rate, mentre ``prob_sicuro`` e'
    persistito da sempre: il Brier non richiede nessuna migrazione.
    """
    lst = [e for e in (entries or []) if is_dict(e)]
    decise = [e for e in lst if outcome_of_entry(e) is not None]
    coppie = [(prob_of_entry(e), outcome_of_entry(e)) for e in decise]
    coppie = [(p, y) for p, y in coppie if p is not None]
    n_prob = len(coppie)
    hit = (sum(y for _, y in coppie) / n_prob) if n_prob else None
    mean_p = (sum(p for p, _ in coppie) / n_prob) if n_prob else None
    brier = (sum((p - y) ** 2 for p, y in coppie) / n_prob) if n_prob else None
    return {
        "total": len(lst),
        "decise": len(decise),
        "con_probabilita": n_prob,
        "hit_rate": (hit * 100.0) if hit is not None else None,
        "prob_media": (mean_p * 100.0) if mean_p is not None else None,
        "gap": ((mean_p - hit) * 100.0) if (mean_p is not None and hit is not None) else None,
        "brier": brier,
    }


def calibration_by_mercato(entries: Iterable[Dict[str, Any]], min_decise: int = 10,
                           per_origine: bool = True) -> List[Dict[str, Any]]:
    """Tabella di affidabilita' per mercato (e per origine).

    ``min_decise`` scarta i tagli con troppi pochi risultati giudicati: una
    riga con 3 partite decise darebbe un Brier a +-0,3 senza significato.
    """
    from collections import defaultdict
    gruppi = defaultdict(list)
    for e in entries or []:
        if not is_dict(e):
            continue
        mkt = str(e.get(MERCATO_FIELD) or "ALTRO")
        if per_origine:
            gruppi[(mkt, origin_of(e))].append(e)
        else:
            gruppi[(mkt, "")].append(e)
    righe = []
    for (mkt, org), elems in gruppi.items():
        st = compute_calibration_stats(elems)
        if st["decise"] < min_decise:
            continue
        righe.append({"mercato": mkt, "origine": org, **st})
    righe.sort(key=lambda r: (-r["decise"], r["mercato"]))
    return righe


def overall_reliability_transfer_warning(stats: Dict[str, Any]) -> Optional[str]:
    """Nota leggibile per la UI: ricorda che il Brier del registro NON e' out-of-sample."""
    if not stats or stats.get("brier") is None:
        return None
    if stats.get("con_probabilita", 0) < 30:
        return ("Campione sotto 30 partite giudicate con probabilita': il Brier "
                "e' un indizio, non una misura.")
    return None
