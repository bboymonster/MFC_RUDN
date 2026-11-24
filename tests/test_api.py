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
