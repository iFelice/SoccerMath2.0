"""Genera il referto Markdown e archivia gli snapshot di un dispatch."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .core import empty_snapshot, write_json
from .policy import EXCLUDED_SOURCES, SOURCE_LABELS

SOURCE_ORDER = ("serie_a", "laliga", "ligue1", "rotowire", "premier_injuries", "fantacalcio")

TERMS_ROWS = (
    (
        "Serie A / Lega Serie A",
        "§2.4 limita l'uso a fini personali/non commerciali; §5.2 vieta estrazione/uso di contenuti, inclusi data-mining e robot, senza consenso scritto espresso. Attiva solo con autorizzazione scritta specifica.",
        "https://www.legaseriea.it/terms-and-conditions",
    ),
    (
        "La Liga / RFEF",
        "Legal notice §2: vieta la riproduzione completa o parziale senza autorizzazione RFEF. Il dispatch richiede conferma dell'autorizzazione scritta.",
        "https://rfef.es/en/legal-notice",
    ),
    (
        "Ligue 1 / LFP",
        "CGU §§6, 10: uso di consultazione personale entro la funzione prevista; le informazioni non possono essere riprodotte o riutilizzate senza consenso scritto preventivo.",
        "https://ligue1.com/en/legal/cgu",
    ),
    (
        "RotoWire",
        "Esclusa: Article VI vieta mezzi automatici/scraping; Article VII limita l'uso tramite AI.",
        "https://www.rotowire.com/termsandconditions.php",
    ),
    (
        "Premier Injuries",
        "Esclusa dagli snapshot GitHub: archivio personale ammesso su dispositivo locale, non su server/dispositivi di rete.",
        "https://www.premierinjuries.com/terms",
    ),
    (
        "Fantacalcio.it",
        "Esclusa: NAVIGAZIONE §3 vieta software o meccanismi automatici/manuali di accesso/copia, compreso scraping, senza autorizzazione scritta ed espressa; vieta anche riuso/elaborazione dei contenuti.",
        "https://www.fantacalcio.it/termini-e-condizioni",
    ),
)


def _esc(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _status_label(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return "non letta"
    return {
        "read": "letta",
        "not_read": "non letta",
        "excluded_terms": "esclusa dai termini",
    }.get(str(snapshot.get("status")), "non letta")


def _http_cell(snapshot: dict[str, Any] | None) -> str:
    if not snapshot or not snapshot.get("requests"):
        return "n/d (nessuna richiesta)"
    return "; ".join(
        f"{row.get('http_status') if row.get('http_status') is not None else 'n/d'} ({int(row.get('response_bytes', 0))} B)"
        for row in snapshot["requests"]
    )


def _rows_for(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return list(snapshot.get("suspended_players") or [])


def _format_suspensions(snapshot: dict[str, Any], *, coaches: bool = False) -> list[str]:
    key = "suspended_coaches" if coaches else "suspended_players"
    rows = list(snapshot.get(key) or [])
    heading = "Allenatori squalificati" if coaches else "Calciatori squalificati"
    lines = [f"#### {heading}"]
    if not rows:
        lines.append("- Nessuna riga di squalifica estratta nel documento letto.")
        return lines
    lines.extend([
        "| Nominativo | Squadra fonte → display | Giornate | Motivo |",
        "|---|---|---:|---|",
    ])
    for row in rows:
        team = row.get("team_display") or row.get("team_source") or "non abbinata"
        canonical = row.get("team_canonical")
        if canonical and canonical != team:
            team = f"{team} (`{canonical}`)"
        games = row.get("games", "n/d")
        if row.get("suspended_games"):
            games = f"{games} ferme + {row['suspended_games']} con sursis"
        lines.append(
            f"| {_esc(row.get('player_name'))} | {_esc(team)} | {games} | {_esc(row.get('reason'))} |"
        )
    return lines


def _diagnostic_table(snapshots: dict[str, dict[str, Any]], job_states: dict[str, str]) -> list[str]:
    lines = [
        "| Fonte | Stato | HTTP per richiesta (byte) | Byte totali | Documento trovato | Righe estratte | Squadre non abbinate |",
        "|---|---|---|---:|---|---:|---|",
    ]
    for source in SOURCE_ORDER:
        snapshot = snapshots.get(source)
        status = _status_label(snapshot)
        if not snapshot:
            status = f"non letta (job {job_states.get(source, 'senza esito')}; snapshot assente)"
        rows = snapshot.get("rows_extracted", 0) if snapshot else 0
        byte_count = snapshot.get("response_bytes", 0) if snapshot else 0
        document = "sì" if snapshot and snapshot.get("document_found") else "no"
        unmatched = ", ".join(snapshot.get("unmatched_teams") or []) if snapshot else "n/d"
        lines.append(
            f"| {_esc(SOURCE_LABELS[source])} | {_esc(status)} | {_esc(_http_cell(snapshot))} | {byte_count} | {document} | {rows} | {_esc(unmatched or 'nessuna')} |"
        )
    return lines


def _source_details(source: str, snapshot: dict[str, Any] | None) -> list[str]:
    label = SOURCE_LABELS[source]
    lines = [f"### {label}"]
    if not snapshot:
        lines.append("- **Non letta**: il job non ha prodotto uno snapshot; non equivale a nessuno squalificato.")
        return lines
    lines.append(f"- Esito: **{_status_label(snapshot)}**.")
    lines.append(f"- URL input: `{_esc(snapshot.get('source_url') or 'n/d')}`.")
    lines.append(f"- Diagnostica: HTTP `{_esc(snapshot.get('http_status') if snapshot.get('http_status') is not None else 'n/d')}`, byte `{snapshot.get('response_bytes', 0)}`, documento trovato `{str(bool(snapshot.get('document_found'))).lower()}`, righe `{snapshot.get('rows_extracted', 0)}`.")
    if snapshot.get("reason"):
        lines.append(f"- Motivo: {_esc(snapshot['reason'])}.")
    if source == "serie_a" and snapshot.get("status") == "read":
        lines.append(f"- Giornata comunicata: {_esc(snapshot.get('matchday') or 'n/d')}.")
        lines.extend(_format_suspensions(snapshot))
        lines.extend(_format_suspensions(snapshot, coaches=True))
        cautions = list(snapshot.get("cautions") or [])
        lines.append("#### Ammonizioni progressive estratte")
        if cautions:
            lines.extend(["| Calciatore | Squadra display | Progressivo |", "|---|---|---:|"])
            for row in cautions:
                lines.append(f"| {_esc(row.get('player_name'))} | {_esc(row.get('team_display') or row.get('team_source'))} | {row.get('progressive_count', 'n/d')} |")
        else:
            lines.append("- Nessuna riga di ammonizione progressiva estratta.")
        history = snapshot.get("history") or {}
        if snapshot.get("diffidati_complete"):
            lines.append("#### Diffidati (cronologia completa dichiarata e verificata)")
            diffidati = snapshot.get("diffidati") or []
            if diffidati:
                lines.extend(["| Calciatore | Squadra display | Ammonizioni |", "|---|---|---:|"])
                for row in diffidati:
                    lines.append(f"| {_esc(row.get('player_name'))} | {_esc(row.get('team_display') or row.get('team_source'))} | {row.get('progressive_count')} |")
            else:
                lines.append("- Cronologia completa letta: nessun progressivo noto soddisfa la regola di diffida.")
        else:
            lines.append("#### Diffidati")
            lines.append("- Elenco completo **non calcolabile**: serve la cronologia ufficiale completa dalla 1ª giornata. Non interpretare l'assenza di righe osservate come zero diffidati.")
            lines.append(f"- Copertura storia: giornate lette `{_esc(history.get('rounds_seen', []))}`, mancanti `{_esc(history.get('missing_rounds', []))}`, completa `{str(bool(history.get('complete'))).lower()}`.")
            observed = snapshot.get("diffidati_observed") or []
            if observed:
                lines.append("- Tra i soli calciatori ammoniti in questo comunicato, i progressivi già in diffida sono:")
                lines.extend(["| Calciatore | Squadra display | Progressivo |", "|---|---|---:|"])
                for row in observed:
                    lines.append(f"| {_esc(row.get('player_name'))} | {_esc(row.get('team_display') or row.get('team_source'))} | {row.get('progressive_count')} |")
            else:
                lines.append("- Nessun progressivo di diffida fra i soli calciatori ammoniti in questo comunicato; elenco generale comunque non completo.")
        if history.get("errors"):
            lines.append(f"- Errori nei PDF storici: {_esc('; '.join(history['errors']))}.")
    elif source in {"laliga", "ligue1"} and snapshot.get("status") == "read":
        if snapshot.get("matchday") is not None:
            lines.append(f"- Giornata comunicata: {_esc(snapshot.get('matchday'))}.")
        lines.extend(_format_suspensions(snapshot))
    elif snapshot.get("status") == "excluded_terms":
        lines.append("- Nessuna richiesta HTTP eseguita; nessun contenuto estratto o confrontato.")
    for request in snapshot.get("requests", []):
        lines.append(
            f"- Richiesta: `{_esc(request.get('url'))}` — HTTP `{_esc(request.get('http_status') if request.get('http_status') is not None else 'n/d')}`, `{int(request.get('response_bytes', 0))}` byte."
        )
    unmatched = snapshot.get("unmatched_teams") or []
    if unmatched:
        lines.append(f"- **Squadre non abbinate** (nessun fuzzy matching): {_esc(', '.join(unmatched))}.")
    return lines


def build_report(
    snapshots: dict[str, dict[str, Any]] | None = None,
    *,
    report_window: str = "",
    stamp: str = "",
    run_id: str = "",
    job_states: dict[str, str] | None = None,
) -> str:
    snapshots = snapshots or {}
    job_states = job_states or {}
    lines = [
        "# Sonda assenze — referto di audit",
        "",
        "## Regola decisionale (prima dei numeri)",
        "",
        "1. **Squalifiche**: fa fede solo il provvedimento ufficiale del Giudice Sportivo (Serie A), della RFEF (La Liga) o della Commissione LFP (Ligue 1). I cartellini non sono mai usati per ricostruire una squalifica già pronunciata.",
        "2. **Serie A — diffidati**: soglie progressive 5, 9, 13, 16, 18 e ogni ammonizione dalla 19ª. È diffidato chi ha un progressivo per cui la prossima ammonizione raggiunge una soglia. La lista è completa soltanto con tutti i comunicati ufficiali dalla 1ª giornata; altrimenti è `non calcolabile`, non zero.",
        "3. **Fonte non ufficiale**: può essere dichiarata affidabile per le squalifiche solo dopo concordanza esatta di tutti i calciatori con la fonte ufficiale per **due giornate consecutive** in una lega coperta da fonte ufficiale. Solo dopo tale verifica può coprire Premier League/Bundesliga dove necessario. Una fonte esclusa dai termini non viene confrontata e non accumula giornate di affidabilità.",
        "4. **Errore di fonte** (documento non trovato, HTTP diverso da 200, zero righe o schema cambiato) = **non letta**, con motivo. Non significa mai «nessuno squalificato».",
        "5. **Infortuni/formazioni**: non sono raccolti da questa sonda. Ogni eventuale dato manuale deve sempre riportare fonte, URL e ora di aggiornamento/raccolta.",
        "",
        "## Esecuzione",
        "",
    ]
    if stamp:
        lines.extend([
            f"- Snapshot UTC: `audit/data/assenze/{stamp}/`.",
            f"- Finestra dichiarata al dispatch: `{_esc(report_window or 'non specificata')}`.",
            f"- Run GitHub Actions: `{_esc(run_id or 'n/d')}`.",
        ])
    else:
        lines.append("- Nessun run di `audit_assenze.yml` registrato in questo referto iniziale.")
    lines.extend(["", "### Diagnostica per fonte", ""])
    lines.extend(_diagnostic_table(snapshots, job_states))
    lines.append("")
    if snapshots:
        lines.extend(["### Dettaglio fonte per fonte", ""])
        for source in SOURCE_ORDER:
            lines.extend(_source_details(source, snapshots.get(source)))
            lines.append("")
    else:
        lines.append("Nessuna richiesta o estrazione è stata eseguita nel referto iniziale; tutte le diagnostiche sono `n/d`.")
        lines.append("")

    lines.extend([
        "## Confronto fonti non ufficiali",
        "",
        "| Fonte richiesta | Stato | Verifica contro l'ufficiale |",
        "|---|---|---|",
        "| RotoWire | esclusa dai termini | non eseguita; concordanza 0/2 turni verificati |",
        "| Premier Injuries | esclusa dall'archiviazione in rete senza autorizzazione scritta | non eseguita; concordanza 0/2 turni verificati |",
        "| Fantacalcio.it | esclusa finché non esiste autorizzazione scritta ed espressa | non eseguita; concordanza 0/2 turni verificati |",
        "",
        "Il numero `0/2` indica **nessun turno verificato**, non una discordanza né una fonte senza assenti. Non sono stati effettuati fetch automatici di queste fonti.",
        "",
        "## Fonti ufficiali e termini d'uso controllati il 13/10/2026",
        "",
        "| Fonte | Esito dei termini | Riferimento |",
        "|---|---|---|",
    ])
    for name, summary, url in TERMS_ROWS:
        lines.append(f"| {_esc(name)} | {_esc(summary)} | [termini]({url}) |")
    lines.extend([
        "",
        "Le tre fonti ufficiali richiedono autorizzazione scritta per l'estrazione/riuso descritti dai rispettivi termini. L'operatore ha dichiarato il 13/10/2026 di possedere permessi scritti per Serie A, RFEF e LFP; i documenti di autorizzazione non sono conservati nel repository. Ogni job ufficiale è **fail-closed**: input di conferma per fonte predefinito `no`, nessuna richiesta se non impostato su `yes`.",
        "",
        "## Verifica di formato su documenti reali",
        "",
        "- **Serie A**: il PDF ufficiale CU n. 47 del 13/10/2026 (6ª giornata) è stato letto durante la verifica preliminare: 3 squalifiche di calciatori e 3 di allenatori, oltre alle ammonizioni progressive. Il fixture PDF dichiarato dall'utente non è nel checkout; il test del parser su quel PDF reale resta da eseguire quando sarà ripristinato. Il codice non crea una copia sostitutiva.",
        "- **La Liga/RFEF**: PDF J7, comunicato 23/09/2026, verificato su documento reale; fixture testuale ridotto in `audit/fixtures/assenze/`. Tre squalifiche di calciatori: doppia ammonizione (1) e due espulsioni dirette (1 ciascuna). Il percorso ipotizzato per J8 restituiva 404 al 13/10; non si presume un URL per le giornate successive.",
        "- **Ligue 1/LFP**: articolo disciplinare del 23/09/2026 (pubblicato 24/09), verificato su pagina reale; fixture testuale ridotto in `audit/fixtures/assenze/`. Quattro nominativi: una sanzione di 2 gare ferme + 2 con sursis, una da 1 gara e due da 1 gara per quinto avvertimento. È l'ultimo comunicato individuato nella ricerca del 13/10, non una garanzia che non ne esistessero di più recenti.",
        "- I fixture La Liga/LFP sono estratti testuali minimi per test offline, non copie integrali dei PDF/HTML. I permessi scritti sono stati dichiarati dall'operatore; il repository non include i documenti di autorizzazione.",
        "",
        "## Premier League e Bundesliga: fonti ufficiali trovate",
        "",
        "- **Premier League**: la pagina ufficiale aggiornata al 12/10/2026 pubblica sospesi per GW7 e giocatori vicini alla soglia gialla; rimanda alle regole FA sulle soglie (5 entro le prime 19 gare; 10 entro la 32ª). La tabella non specifica il motivo disciplinare per ogni nominativo: la copertura è utile ma non completa per distinguere gialli/rossi senza ulteriore conferma. [Pagina ufficiale](https://www.premierleague.com/en/news/4425344/which-players-are-suspended-or-close-to-a-ban-in-fantasy).",
        "- **Bundesliga**: il DFB mantiene una tabella ufficiale «Die aktuellen Sperren in der Bundesliga» con giocatore, club, decisione e motivo, aggiornata al 21/09/2026 alla consultazione; non è un calendario per giornata e in quel momento non mostrava una squalifica per accumulo gialli. [Tabella DFB](https://www.dfb.de/ueber-uns/verbandsrecht/sperren). La pagina redazionale Bundesliga.com consultata è indicata «correct as of 14 September 2026» e non migliora l'aggiornamento per il 13/10. Nessuna delle due fonti è stata automatizzata; termini d'uso per eventuale lettore da verificare prima del codice.",
        "",
        "## Modalità di lancio e lacune operative",
        "",
        "- Solo `workflow_dispatch`; un job indipendente per fonte; un URL ufficiale diretto per ogni documento; nessun crawling dell'indice e nessun URL RFEF futuro indovinato.",
        "- Inserire la finestra (es. `16–19/10/2026`, `23–26/10/2026` oppure `confronto dopo comunicato del martedì`), i PDF/URL ufficiali esatti e confermare separatamente i permessi scritti per ogni fonte. Il lettore effettua una richiesta per pagina, con User-Agent identificativo e pausa di 3 secondi; redirect e retry sono disabilitati.",
        "- Per diffidati Serie A completi, fornire nell'input tutti i PDF precedenti dalla 1ª giornata e confermare che l'archivio non omette documenti/parti. Con un solo PDF la lista resta parziale.",
        "- Squadre abbinate con `team_aliases.clean_name`, crosswalk ufficiale dichiarato e `display_names.display_name`; nessun fuzzy matching. Ogni nome non abbinato resta visibile in tabella.",
        "- Non è stata lanciata alcuna acquisizione reale in questa PR. I job, il referto e i test non modificano `SoccerMath/` né l'app.",
        "",
    ])
    return "\n".join(lines)


def generate_and_store(
    snapshot_dir: Path,
    *,
    stamp: str,
    report_window: str,
    run_id: str,
    job_states: dict[str, str],
    data_root: Path,
    results_dir: Path,
) -> tuple[Path, dict[str, dict[str, Any]]]:
    destination = data_root / stamp
    destination.mkdir(parents=True, exist_ok=True)
    snapshots: dict[str, dict[str, Any]] = {}
    for source in SOURCE_ORDER:
        candidate = snapshot_dir / f"{source}.json"
        if candidate.is_file():
            try:
                snapshot = json.loads(candidate.read_text(encoding="utf-8"))
                if snapshot.get("source") != source:
                    raise ValueError("campo source non corrisponde al nome file")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                snapshot = empty_snapshot(source, SOURCE_LABELS[source], report_window)
                snapshot["reason"] = f"snapshot di job non leggibile: {exc}"
        else:
            snapshot = empty_snapshot(source, SOURCE_LABELS[source], report_window)
            snapshot["reason"] = f"job senza snapshot (esito: {job_states.get(source, 'n/d')}); nessun esito sportivo inferito"
        snapshot["report_window"] = report_window
        write_json(destination / f"{source}.json", snapshot)
        snapshots[source] = snapshot

    report_path = results_dir / "sonda_assenze.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        build_report(snapshots, report_window=report_window, stamp=stamp, run_id=run_id, job_states=job_states),
        encoding="utf-8",
    )
    return report_path, snapshots


def _parse_job_states(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"job-states JSON non valido: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("job-states deve essere un oggetto JSON")
    return {str(key): str(item) for key, item in value.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Archivia snapshot fonte e genera audit/results/sonda_assenze.md")
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--stamp", required=True, help="YYYY-MM-DD_HHMM UTC")
    parser.add_argument("--report-window", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--job-states", default="{}")
    parser.add_argument("--data-root", type=Path, default=Path("audit/data/assenze"))
    parser.add_argument("--results-dir", type=Path, default=Path("audit/results"))
    args = parser.parse_args()
    report_path, snapshots = generate_and_store(
        args.snapshot_dir,
        stamp=args.stamp,
        report_window=args.report_window,
        run_id=args.run_id,
        job_states=_parse_job_states(args.job_states),
        data_root=args.data_root,
        results_dir=args.results_dir,
    )
    print(f"Referto: {report_path}")
    for source in SOURCE_ORDER:
        snapshot = snapshots[source]
        print(
            f"{source}: status={snapshot.get('status')}; HTTP={snapshot.get('http_status')}; "
            f"bytes={snapshot.get('response_bytes', 0)}; document_found={snapshot.get('document_found')}; "
            f"rows={snapshot.get('rows_extracted', 0)}; reason={snapshot.get('reason') or 'n/d'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
