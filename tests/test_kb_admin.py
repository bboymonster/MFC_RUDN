"""Интеграционные тесты новых эндпоинтов: CRUD правил, загрузка звонка, HitL ревью, экспорт отчета."""

import io
from fastapi.testclient import TestClient
from mfc_analytics.api.app import app

client = TestClient(app)


def test_kb_rules_crud():
    rule_id = "RULE_TEST_CRUD_01"
    
    # 1. Создание
    res_create = client.post(
        "/api/rules",
        json={
            "rule_id": rule_id,
            "category": "Тестовая категория",
            "title": "Тестовое правило",
            "exact_rule_text": "Официальный регламент тестирования.",
            "source_document": "Приказ №123",
            "critical_terms": ["тест", "дедлайн"],
        },
    )
    assert res_create.status_code == 200
    assert res_create.json()["status"] == "created"

    # 2. Получение
    res_get = client.get("/api/rules")
    assert res_get.status_code == 200
    rule_ids = [r["rule_id"] for r in res_get.json()]
    assert rule_id in rule_ids

    # 3. Обновление
    res_update = client.put(
        f"/api/rules/{rule_id}",
        json={"title": "Обновленное тестовое правило"},
    )
    assert res_update.status_code == 200
    assert res_update.json()["rule"]["title"] == "Обновленное тестовое правило"

    # 4. Удаление
    res_del = client.delete(f"/api/rules/{rule_id}")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "deleted"


def test_upload_call_with_anonymization():
    res = client.post(
        "/api/calls/upload",
        data={
            "caller_text": "Здравствуйте, мой СНИЛС 142-883-991 70, телефон +7 925 000-11-22, когда будут списки зачисления?",
            "operator_text": "Добрый день! Списки будут опубликованы 27 июля.",
            "operator_name": "Оператор №05",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "created"
    assert data["anonymization_stats"]["snils_masked"] >= 1
    assert data["anonymization_stats"]["phones_masked"] >= 1
    
    # Проверка, что в сохраненном звонке ПДн замаскированы
    stored_transcript = data["call"]["full_transcript"]
    assert "142-883-991 70" not in stored_transcript
    assert "[СНИЛС_СКРЫТ]" in stored_transcript


def test_hitl_call_review_override():
    call_id = "CALL-2026-0804-001"
    res = client.post(
        f"/api/calls/{call_id}/review",
        json={
            "manager_status": "Нарушение подтверждено",
            "score_override": 25.0,
            "manager_notes": "Скорректировано экспертом контроля качества.",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["new_score"] == 25.0
    assert data["manager_status"] == "Нарушение подтверждено"


def test_cms_csv_upload_endpoint():
    csv_file = io.BytesIO(b"""Date;Time;VDN;CallsOffered;ACDCalls;AbanCalls;Positions;Avg_Speed_Ans;Avg_ACD_Time
2026-08-10;10:00;VDN_MFC_RUDN;55;50;5;6;22.0;180.0
2026-08-10;10:30;VDN_MFC_RUDN;65;58;7;7;35.0;190.0
""")
    res = client.post(
        "/api/cms/upload",
        files={"file": ("avaya_report.csv", csv_file, "text/csv")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["intervals_imported"] == 2


def test_export_report_csv():
    res = client.get("/api/reports/export")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    content = res.content.decode("utf-8-sig")
    assert "ID звонка;Время (МСК);Длительность (сек)" in content
