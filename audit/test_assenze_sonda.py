from __future__ import annotations

from pathlib import Path

from audit.assenze import core, runner
from audit.assenze.core import HTTPResponse
from audit.assenze.laliga import parse_laliga_text
from audit.assenze.ligue1 import parse_ligue1_text
from audit.assenze.policy import excluded_snapshot
from audit.assenze.report import build_report, generate_and_store
from audit.assenze.serie_a import (
    diffidati_from_progressives,
    parse_serie_a_text,
    triggers_suspension_on_next_yellow,
)
from audit.assenze.team_mapping import canonical_team, decorate_records, load_live_teams

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "audit" / "fixtures" / "assenze"


def _serie_a_caution_text(matchday: int, progressive: int) -> str:
    words = {1: "PRIMA", 2: "SECONDA", 3: "TERZA", 4: "QUARTA"}
    return f"""Comunicato Ufficiale N. {40 + matchday}
Gare della {matchday}ª giornata
B) DECISIONI DEL GIUDICE SPORTIVO
b) CALCIATORI
AMMONIZIONE
{words[progressive]} SANZIONE
ROSSI Mario (Roma)
c) ALLENATORI
"""


def _synthetic_serie_a_text() -> str:
    """Schema realistico del CU, non sostituisce il PDF n. 47 mancante."""
    return """Comunicato Ufficiale N. 47
Del 13 ottobre 2026
Gare della Sesta giornata andata
B) DECISIONI DEL GIUDICE SPORTIVO
b) CALCIATORI
CALCIATORI ESPULSI
SQUALIFICA PER UNA GIORNATA EFFETTIVA DI GARA
ELMAS Eljif (Atalanta): per essersi reso responsabile di un fallo grave di giuoco.

PER PROTESTE NEI CONFRONTI DEGLI UFFICIALI DI GARA
AMMONIZIONE E AMMENDA DI € 1.500,00 (PRIMA SANZIONE)
BERARDI Domenico (Sassuolo): sanzione aggravata perché capitano.
VASQUEZ IBARRA Johan Felipe (Genoa): sanzione aggravata perché capitano.
AMMONIZIONE
SECONDA SANZIONE
DIAO DIAOUNE Assane (Como)

PER COMPORTAMENTO SCORRETTO
AMMONIZIONE
QUARTA SANZIONE
ROSSI Mario (Como)

c) ALLENATORI
ESPULSI
SQUALIFICA PER UNA GIORNATA EFFETTIVA DI GARA
PISACANE Fabio (Cagliari): condotta antisportiva.
"""


def test_real_rfef_j7_fixture_extracts_all_player_suspensions_and_maps_teams():
    text = (FIXTURES / "laliga_j7_2026-09-23.txt").read_text(encoding="utf-8")
    parsed = parse_laliga_text(text)

    assert parsed["recognized"] is True
    assert parsed["matchday"] == 7
    assert parsed["rows_extracted"] == 3
    players = parsed["suspended_players"]
    assert [row["player_name"] for row in players] == [
        'OSKARSSON, ORRI STEINN "OSKARSSON"',
        "REDONDO SOLARI, FEDERICO",
        'HUIJSEN WIJSMULLER, DEAN DONNY "HUIJSEN"',
    ]
    assert [row["suspension_type"] for row in players] == [
        "double_yellow", "direct_red", "direct_red"
    ]
    live = load_live_teams("laliga")
    decorated, unmatched = decorate_records(players, "laliga", live)
    assert unmatched == []
    assert [row["team_canonical"] for row in decorated] == ["Sociedad", "Elche", "Real Madrid"]


def test_real_lfp_decision_fixture_extracts_effective_dates_and_reasons():
    text = (FIXTURES / "ligue1_decisions_2026-09-23.txt").read_text(encoding="utf-8")
    parsed = parse_ligue1_text(text)

    assert parsed["recognized"] is True
    assert parsed["rows_extracted"] == 4
    players = parsed["suspended_players"]
    assert [row["player_name"] for row in players] == [
        "Paris BRUNNER", "Timothy WEAH", "Christ MAKOSSO", "Djibril SIDIBÉ"
    ]
    assert (players[0]["games"], players[0]["suspended_games"]) == (2, 2)
    assert all(row["effective_from"] == "2026-09-29" for row in players)
    assert players[2]["suspension_type"] == "yellow_accumulation_5"
    assert players[3]["suspension_type"] == "yellow_accumulation_5"
    decorated, unmatched = decorate_records(players, "ligue1", load_live_teams("ligue1"))
    assert unmatched == []
    assert [row["team_canonical"] for row in decorated] == ["Monaco", "Marseille", "Auxerre", "Le Mans"]


def test_serie_a_parser_on_synthetic_official_layout_separates_players_coaches_and_cautions():
    parsed = parse_serie_a_text(_synthetic_serie_a_text())

    assert parsed["recognized"] is True
    assert parsed["matchday"] == 6
    assert parsed["rows_extracted"] == 6
    assert [(row["player_name"], row["games"]) for row in parsed["suspended_players"]] == [("ELMAS Eljif", 1)]
    assert [(row["player_name"], row["games"]) for row in parsed["suspended_coaches"]] == [("PISACANE Fabio", 1)]
    assert [row["progressive_count"] for row in parsed["cautions"]] == [1, 1, 2, 4]
    assert [row["player_name"] for row in parsed["diffidati_observed"]] == ["ROSSI Mario"]


def test_serie_a_diffida_thresholds_include_every_threshold_and_each_card_after_18():
    assert [n for n in range(0, 21) if triggers_suspension_on_next_yellow(n)] == [4, 8, 12, 15, 17, 18, 19, 20]
    assert triggers_suspension_on_next_yellow(-1) is False
    assert triggers_suspension_on_next_yellow(3) is False
    assert triggers_suspension_on_next_yellow(18) is True


def test_diffidati_progressivi_deduplicate_player_at_latest_progressive():
    rows = [
        {"player_name": "Mario Rossi", "team_source": "Roma", "progressive_count": 3},
        {"player_name": "Mario Rossi", "team_source": "Roma", "progressive_count": 4},
        {"player_name": "Luigi Bianchi", "team_source": "Milan", "progressive_count": 8},
        {"player_name": "Paolo Verdi", "team_source": "Inter", "progressive_count": 9},
    ]
    result = diffidati_from_progressives(rows)
    # L'ordine è squadra poi nominativo; solo 4 e 8 sono alla soglia.
    assert [(row["player_name"], row["progressive_count"]) for row in result] == [
        ("Luigi Bianchi", 8), ("Mario Rossi", 4)
    ]


def test_empty_or_changed_schema_is_not_interpreted_as_zero_absences():
    assert parse_laliga_text("")["recognized"] is False
    assert parse_ligue1_text("Discipline : texte éditorial sans sanction") ["recognized"] is False
    parsed = parse_serie_a_text("Comunicato Ufficiale\nB) DECISIONI DEL GIUDICE SPORTIVO\nb) CALCIATORI\nc) ALLENATORI")
    assert parsed["recognized"] is False
    assert parsed["rows_extracted"] == 0


def test_team_resolver_is_exact_and_reports_unmatched_names():
    laliga_live = load_live_teams("laliga")
    assert canonical_team("laliga", "Rayo Vallecano de Madrid", laliga_live) == "Vallecano"
    assert canonical_team("laliga", "Real Sociedad de Fútbol", laliga_live) == "Sociedad"
    assert canonical_team("laliga", "Un Club inventado", laliga_live) is None
    _, unmatched = decorate_records(
        [{"player_name": "X", "team_source": "Un Club inventado"}], "laliga", laliga_live
    )
    assert unmatched == ["Un Club inventado"]


def test_html_text_extractor_ignores_scripts_and_preserves_visible_lfp_content():
    html = """<html><head><script>not player (bad)</script></head><body>
    <h1>Discipline : Toutes les décisions</h1><p>Un match de suspension ferme</p>
    <p>Timothy WEAH (Olympique de Marseille)</p></body></html>"""
    visible = core.html_to_text(html)
    assert "not player" not in visible
    parsed = parse_ligue1_text(visible)
    assert parsed["recognized"] is True
    assert parsed["suspended_players"][0]["player_name"] == "Timothy WEAH"


def test_dispatch_reader_laliga_runs_offline_against_real_fixture(monkeypatch):
    text = (FIXTURES / "laliga_j7_2026-09-23.txt").read_text(encoding="utf-8")
    body = b"%PDF-fake-fixture-bytes"
    response = HTTPResponse(
        requested_url="https://rfef.es/sites/default/files/sanciones/Primera_Division_J7.pdf",
        final_url="https://rfef.es/sites/default/files/sanciones/Primera_Division_J7.pdf",
        status_code=200,
        body=body,
        content_type="application/pdf",
    )
    monkeypatch.setattr(runner, "fetch_url", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(runner, "extract_pdf_text", lambda _body: (text, None))

    snapshot = runner.read_laliga(response.requested_url, authorized=True, report_window="turno fixture")

    assert snapshot["status"] == "read"
    assert snapshot["http_status"] == 200
    assert snapshot["response_bytes"] == len(body)
    assert snapshot["document_found"] is True
    assert snapshot["rows_extracted"] == 3
    assert snapshot["unmatched_teams"] == []


def test_dispatch_reader_lfp_runs_offline_against_real_fixture(monkeypatch):
    text = (FIXTURES / "ligue1_decisions_2026-09-23.txt").read_text(encoding="utf-8")
    body = b"<html>fixture</html>"
    url = "https://ligue1.com/fr/articles/l1_article_5894-discipline-toutes-les-decisions-du-23-septembre"
    response = HTTPResponse(url, url, 200, body, "text/html")
    monkeypatch.setattr(runner, "fetch_url", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(runner, "decode_html", lambda _body: (text, None))

    snapshot = runner.read_ligue1(url, authorized=True, report_window="turno fixture")

    assert snapshot["status"] == "read"
    assert snapshot["rows_extracted"] == 4
    assert snapshot["document_found"] is True
    assert snapshot["unmatched_teams"] == []


def test_serie_a_synthetic_reader_stays_read_but_diffidati_are_not_complete_without_history(monkeypatch):
    text = _synthetic_serie_a_text()
    url = "https://images.legaseriea.it/image/private/fl_attachment/prd/hvdturcnhbtepxu03mq7.pdf"
    body = b"%PDF-synthetic"
    response = HTTPResponse(url, url, 200, body, "application/pdf")
    monkeypatch.setattr(runner, "fetch_url", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(runner, "extract_pdf_text", lambda _body: (text, None))

    snapshot = runner.read_serie_a(url, authorized=True, report_window="test sintetico")

    assert snapshot["status"] == "read"
    assert snapshot["rows_extracted"] == 6
    assert snapshot["diffidati_complete"] is False
    assert snapshot["diffidati"] is None
    assert [row["player_name"] for row in snapshot["diffidati_observed"]] == ["ROSSI Mario"]


def test_serie_a_complete_history_allows_full_diffidati_only_when_every_round_is_present(monkeypatch):
    current_url = "https://images.legaseriea.it/current.pdf"
    history_url = "https://images.legaseriea.it/history.pdf"
    current_body = b"%PDF-current"
    history_body = b"%PDF-history"
    texts = {
        current_body: _serie_a_caution_text(2, 4),
        history_body: _serie_a_caution_text(1, 3),
    }
    responses = {
        current_url: HTTPResponse(current_url, current_url, 200, current_body, "application/pdf"),
        history_url: HTTPResponse(history_url, history_url, 200, history_body, "application/pdf"),
    }
    monkeypatch.setattr(runner, "fetch_url", lambda _source, url: responses[url])
    monkeypatch.setattr(runner, "extract_pdf_text", lambda body: (texts[body], None))

    snapshot = runner.read_serie_a(
        current_url,
        authorized=True,
        history_urls=[history_url],
        history_complete_confirmed=True,
    )

    assert snapshot["status"] == "read"
    assert snapshot["history"]["complete"] is True
    assert snapshot["history"]["rounds_seen"] == [1, 2]
    assert snapshot["history"]["missing_rounds"] == []
    assert snapshot["diffidati_complete"] is True
    assert [(row["player_name"], row["progressive_count"]) for row in snapshot["diffidati"]] == [
        ("ROSSI Mario", 4)
    ]
    assert snapshot["diffidati"][0]["team_match"] == "matched"


def test_missing_permission_or_url_never_sends_http(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("non deve essere inviata alcuna richiesta")

    monkeypatch.setattr(runner, "fetch_url", fail_if_called)
    denied = runner.read_laliga("https://rfef.es/example.pdf", authorized=False)
    missing = runner.read_laliga("", authorized=True)
    assert denied["status"] == "not_read"
    assert "permesso scritto" in denied["reason"]
    assert denied["requests"] == []
    assert missing["status"] == "not_read"
    assert "URL" in missing["reason"]
    assert missing["requests"] == []


def test_http_404_is_not_read_not_an_empty_suspension_list(monkeypatch):
    url = "https://rfef.es/sites/default/files/sanciones/Primera_Division_J7.pdf"
    response = HTTPResponse(url, url, 404, b"not found", "text/html", "risposta HTTP 404")
    monkeypatch.setattr(runner, "fetch_url", lambda *_args, **_kwargs: response)
    snapshot = runner.read_laliga(url, authorized=True)
    assert snapshot["status"] == "not_read"
    assert snapshot["http_status"] == 404
    assert snapshot["response_bytes"] == len(b"not found")
    assert snapshot["document_found"] is False
    assert "HTTP 404" in snapshot["reason"]


def test_http_200_zero_bytes_is_not_read(monkeypatch):
    url = "https://rfef.es/sites/default/files/sanciones/Primera_Division_J7.pdf"
    response = HTTPResponse(url, url, 200, b"", "application/pdf")
    monkeypatch.setattr(runner, "fetch_url", lambda *_args, **_kwargs: response)
    snapshot = runner.read_laliga(url, authorized=True)
    assert snapshot["status"] == "not_read"
    assert snapshot["document_found"] is False
    assert snapshot["rows_extracted"] == 0
    assert "zero byte" in snapshot["reason"]


def test_http_200_changed_document_schema_is_not_read(monkeypatch):
    url = "https://rfef.es/sites/default/files/sanciones/Primera_Division_J7.pdf"
    response = HTTPResponse(url, url, 200, b"%PDF-valid-ish", "application/pdf")
    monkeypatch.setattr(runner, "fetch_url", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(runner, "extract_pdf_text", lambda _body: ("Documento senza sezioni RFEF note", None))
    snapshot = runner.read_laliga(url, authorized=True)
    assert snapshot["status"] == "not_read"
    assert snapshot["document_found"] is True
    assert snapshot["rows_extracted"] == 0
    assert "intestazione" in snapshot["reason"]


def test_http_200_with_zero_disciplinary_rows_is_not_read_for_every_official_source(monkeypatch):
    urls = {
        "serie_a": "https://images.legaseriea.it/current.pdf",
        "laliga": "https://rfef.es/current.pdf",
        "ligue1": "https://ligue1.com/current-article",
    }
    texts = {
        "serie_a": """Comunicato Ufficiale N. 47
B) DECISIONI DEL GIUDICE SPORTIVO
b) CALCIATORI
CALCIATORI ESPULSI
c) ALLENATORI
""",
        "laliga": """COMUNICACIÓN PÚBLICA DE LOS ACUERDOS
JORNADA: 7
I JUGADORES
1.- SUSPENSIÓN DE EMPLEO Y SUELDO
Artículo: 121.1
II-ENTRENADORES Y AUXILIARES
""",
        "ligue1": """Commission de discipline
Discipline : Toutes les décisions
Un match de suspension ferme.
""",
    }
    bodies = {source: f"%PDF-{source}".encode() for source in ("serie_a", "laliga")}
    responses = {
        source: HTTPResponse(url, url, 200, bodies[source], "application/pdf")
        for source, url in urls.items()
        if source in bodies
    }
    responses["ligue1"] = HTTPResponse(urls["ligue1"], urls["ligue1"], 200, b"<html>fixture</html>", "text/html")

    monkeypatch.setattr(runner, "fetch_url", lambda source, _url: responses[source])
    monkeypatch.setattr(runner, "extract_pdf_text", lambda body: (texts[body.decode().removeprefix("%PDF-")], None))
    monkeypatch.setattr(runner, "decode_html", lambda _body: (texts["ligue1"], None))

    snapshots = {
        "serie_a": runner.read_serie_a(urls["serie_a"], authorized=True),
        "laliga": runner.read_laliga(urls["laliga"], authorized=True),
        "ligue1": runner.read_ligue1(urls["ligue1"], authorized=True),
    }
    for source, snapshot in snapshots.items():
        assert snapshot["status"] == "not_read", source
        assert snapshot["http_status"] == 200, source
        assert snapshot["document_found"] is True, source
        assert snapshot["rows_extracted"] == 0, source
        assert "zero" in snapshot["reason"].casefold() or "nessuna riga" in snapshot["reason"].casefold(), source


def test_report_archive_writes_all_six_source_snapshots_and_marks_missing_jobs(tmp_path):
    job_dir = tmp_path / "job-artifacts"
    job_dir.mkdir()
    core.write_json(job_dir / "rotowire.json", excluded_snapshot("rotowire", "finestra test"))
    data_root = tmp_path / "data"
    results_dir = tmp_path / "results"
    stamp = "2026-10-13_1200"
    states = {
        "serie_a": "failure",
        "laliga": "success",
        "ligue1": "success",
        "rotowire": "success",
        "premier_injuries": "success",
        "fantacalcio": "success",
    }

    report_path, snapshots = generate_and_store(
        job_dir,
        stamp=stamp,
        report_window="finestra test",
        run_id="12345",
        job_states=states,
        data_root=data_root,
        results_dir=results_dir,
    )

    expected_sources = {"serie_a", "laliga", "ligue1", "rotowire", "premier_injuries", "fantacalcio"}
    assert set(snapshots) == expected_sources
    assert {path.stem for path in (data_root / stamp).glob("*.json")} == expected_sources
    report = report_path.read_text(encoding="utf-8")
    assert "job senza snapshot (esito: failure)" in report
    assert "nessun esito sportivo inferito" in report
    assert "Nessuna richiesta HTTP eseguita" in report
    assert "HTTP per richiesta (byte)" in report


def test_excluded_sources_have_no_requests_or_document_claim():
    for source in ("rotowire", "premier_injuries", "fantacalcio"):
        snapshot = excluded_snapshot(source, "16-19/10")
        assert snapshot["status"] == "excluded_terms"
        assert snapshot["requests"] == []
        assert snapshot["http_status"] is None
        assert snapshot["response_bytes"] == 0
        assert snapshot["document_found"] is False
        assert snapshot["rows_extracted"] == 0


def test_low_rate_fetch_sends_identifying_user_agent_and_only_one_request(monkeypatch):
    calls = []

    class FakeResponse:
        headers = {"Content-Type": "application/pdf"}

        def geturl(self):
            return "https://rfef.es/sample.pdf"

        def getcode(self):
            return 200

        def read(self, size=-1):
            return b"%PDF-fake"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeOpener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            return FakeResponse()

    sleeps = []
    monkeypatch.setattr(core, "build_opener", lambda *_args: FakeOpener())
    monkeypatch.setattr(core.time, "sleep", lambda seconds: sleeps.append(seconds))
    response = core.fetch_url("laliga", "https://rfef.es/sample.pdf", delay_seconds=3)

    assert sleeps == [3]
    assert len(calls) == 1
    assert calls[0][1] == core.REQUEST_TIMEOUT_SECONDS
    user_agent = calls[0][0].get_header("User-agent")
    assert "github.com/iFelice/SoccerMath2.0" in user_agent
    assert response.status_code == 200
    assert response.response_bytes == len(b"%PDF-fake")


def test_wrong_host_is_rejected_before_request(monkeypatch):
    monkeypatch.setattr(core.time, "sleep", lambda _seconds: None)
    response = core.fetch_url("laliga", "https://example.com/fake.pdf", delay_seconds=0)
    assert response.status_code is None
    assert "host" in response.error
    assert response.response_bytes == 0


def test_report_places_rules_before_numbers_and_reports_unread_semantics():
    report = build_report({}, report_window="nessuna")
    assert report.index("## Regola decisionale (prima dei numeri)") < report.index("### Diagnostica per fonte")
    assert "non significa mai «nessuno squalificato»" in report.casefold()
    assert "concordanza esatta" in report
    assert "diffidati" in report
