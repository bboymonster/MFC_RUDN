"""Интеграционные тесты FastAPI REST API."""

import pytest
from fastapi.testclient import TestClient
from mfc_analytics.api.app import app

client = TestClient(app)


def test_api_overview():
    response = client.get("/api/overview")
    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data
    assert data["metrics"]["total_calls"] > 0
    assert "topic_distribution" in data
    assert "category_distribution" in data


def test_api_calls_list_and_filters():
    # Без фильтра
    res = client.get("/api/calls")
    assert res.status_code == 200
    calls = res.json()
    assert len(calls) > 0

    # Фильтр по критическим ошибкам
    res_crit = client.get("/api/calls?critical_only=true")
    assert res_crit.status_code == 200
    crit_calls = res_crit.json()
    assert len(crit_calls) > 0
    assert all(c["has_critical_error"] is True for c in crit_calls)


def test_api_call_detail():
    call_id = "CALL-2026-0804-001"
    res = client.get(f"/api/calls/{call_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["metadata"]["call_id"] == call_id
    assert len(data["utterances"]) > 0
    assert len(data["criteria_evaluations"]) == 6


def test_api_call_status_update():
    call_id = "CALL-2026-0804-001"
    res = client.post(
        f"/api/calls/{call_id}/status",
        json={"manager_status": "Нарушение подтверждено", "manager_notes": "Проверено руководителем, назначена переподготовка."},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_api_cms_intervals():
    res = client.get("/api/cms/intervals?limit=10")
    assert res.status_code == 200
    intervals = res.json()
    assert len(intervals) == 10
    assert "offered_calls" in intervals[0]


def test_api_actions():
    res = client.get("/api/actions")
    assert res.status_code == 200
    actions = res.json()
    assert len(actions) > 0


def test_api_custom_analysis():
    res = client.post(
        "/api/analyze-custom",
        json={
            "caller_text": "До какого числа нужно сдать согласие на бюджет?",
            "operator_text": "Вы можете приехать до вечера 5 августа, часиков до восьми.",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["has_critical_error"] is True
    assert data["overall_quality_score"] <= 40.0


def test_index_html_served():
    res = client.get("/")
    assert res.status_code == 200
    assert "МФЦ РУДН" in res.text


def test_api_call_audio_and_waveform():
    call_id = "CALL-2026-0804-001"
    # 1. Audio WAV endpoint
    res_audio = client.get(f"/api/calls/{call_id}/audio.wav")
    assert res_audio.status_code == 200
    assert res_audio.headers["content-type"] == "audio/wav"
    assert len(res_audio.content) > 1000  # Valid binary wav file
    assert res_audio.content[:4] == b"RIFF"
    assert res_audio.content[8:12] == b"WAVE"

    # 2. Waveform bars endpoint
    res_wave = client.get(f"/api/calls/{call_id}/waveform")
    assert res_wave.status_code == 200
    bars = res_wave.json()
    assert len(bars) == 60
    assert "amplitude_percent" in bars[0]
    assert "speaker" in bars[0]


def test_api_cms_summary():
    res = client.get("/api/cms/summary")
    assert res.status_code == 200
    data = res.json()
    assert "total_offered" in data
    assert "total_answered" in data
    assert "service_level_percent" in data
    assert "hourly_offered" in data
    assert len(data["hourly_offered"]) > 0


def test_api_manager_action_lifecycle():
    # 1. Create action
    res_create = client.post(
        "/api/actions",
        json={
            "title": "Тестовая мера руководителя",
            "problem_type": "Систематическая ошибка операторов",
            "description": "Разбор инцидента и дообучение группы операторов.",
            "owner": "МФЦ РУДН",
            "target_days": 2,
            "expected_impact_metric": "Снижение нарушений на 40%",
            "related_call_ids": ["CALL-2026-0804-001"],
        },
    )
    assert res_create.status_code == 200
    act_data = res_create.json()["action"]
    action_id = act_data["action_id"]
    assert act_data["status"] == "Открыто"

    # 2. Update status to IN_PROGRESS
    res_patch = client.patch(f"/api/actions/{action_id}/status?status=В работе")
    assert res_patch.status_code == 200
    assert res_patch.json()["action"]["status"] == "В работе"

    # 3. Delete action
    res_del = client.delete(f"/api/actions/{action_id}")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "deleted"


def test_api_operators_leaderboard():
    res = client.get("/api/operators")
    assert res.status_code == 200
    profiles = res.json()
    assert len(profiles) > 0
    first = profiles[0]
    assert "operator_pseudonym" in first
    assert "average_score" in first
    assert "coaching_status" in first


def test_api_operator_detail():
    res_list = client.get("/api/operators")
    op_name = res_list.json()[0]["operator_pseudonym"]
    res_detail = client.get(f"/api/operators/{op_name}")
    assert res_detail.status_code == 200
    data = res_detail.json()
    assert "profile" in data
    assert "calls" in data
    assert len(data["calls"]) > 0


def test_api_telephony_correlation():
    res = client.get("/api/analytics/correlation")
    assert res.status_code == 200
    data = res.json()
    assert "regime_breakdown" in data
    assert len(data["regime_breakdown"]) == 3
    assert "p90_speed_of_answer_sec" in data
    assert "key_findings" in data


def test_api_executive_and_printable_reports():
    # 1. JSON Executive summary
    res_exec = client.get("/api/reports/executive")
    assert res_exec.status_code == 200
    data = res_exec.json()
    assert "executive_summary" in data
    assert data["executive_summary"]["total_calls_analyzed"] > 0
    assert "top_systemic_issues" in data

    # 2. Printable HTML report
    res_print = client.get("/api/reports/print")
    assert res_print.status_code == 200
    assert "Аналитический отчёт МФЦ РУДН" in res_print.text
    assert "window.print()" in res_print.text


def test_api_calls_csv_export_format():
    res = client.get("/api/reports/export")
    assert res.status_code == 200
    assert res.headers["content-type"] == "text/csv; charset=utf-8"
    content = res.content.decode("utf-8-sig")
    lines = content.strip().splitlines()
    assert len(lines) >= 28  # Header + 28 calls
    header = lines[0].split(";")
    assert "ID звонка" in header
    assert "Оценка качества (%)" in header
    assert "Критическая ошибка" in header
    assert "Режим нагрузки" in header


def test_api_call_review_score_clamp():
    call_id = "CALL-2026-0804-001"
    # Negative score should clamp to 0
    res_neg = client.post(
        f"/api/calls/{call_id}/review",
        json={"manager_status": "Ложное срабатывание", "score_override": -25.0},
    )
    assert res_neg.status_code == 200
    assert res_neg.json()["new_score"] == 0.0

    # Over 100 should clamp to 100
    res_over = client.post(
        f"/api/calls/{call_id}/review",
        json={"manager_status": "Проверено / замечаний нет", "score_override": 140.0},
    )
    assert res_over.status_code == 200
    assert res_over.json()["new_score"] == 100.0


def test_api_operators_coaching_status():
    res = client.get("/api/operators")
    assert res.status_code == 200
    profiles = res.json()
    assert len(profiles) >= 3
    # Sorted descending by average score
    scores = [p["average_score"] for p in profiles]
    assert scores == sorted(scores, reverse=True)
    # Check coaching recommendation exists
    for p in profiles:
        assert len(p["coaching_recommendation"]) > 0



