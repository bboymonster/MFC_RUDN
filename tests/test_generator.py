"""Тесты генератора синтетических данных и калиброванных сценариев."""

from mfc_analytics.data.generator import MFCDataGenerator
from mfc_analytics.models.call import CallTopic


def test_generate_cms_intervals():
    gen = MFCDataGenerator(random_seed=42)
    intervals = gen.generate_cms_intervals(days_count=7)
    assert len(intervals) > 0
    # Проверка, что есть интервалы разных типов нагрузки
    regimes = {i.load_regime for i in intervals}
    assert len(regimes) >= 2


def test_generate_curated_calls():
    gen = MFCDataGenerator(random_seed=42)
    calls = gen.generate_curated_calls()
    assert len(calls) >= 30

    # Проверка наличия ключевых сценариев
    call_ids = [c.metadata.call_id for c in calls]
    assert "CALL-2026-0804-001" in call_ids
    assert "CALL-2026-0821-002" in call_ids
    assert "CALL-2026-0715-003" in call_ids
    assert "CALL-2026-0726-004" in call_ids
    assert "CALL-2026-0801-005" in call_ids
    assert "CALL-2026-0710-006" in call_ids

    # Проверка сценария 1 с критической ошибкой согласия
    sc1 = next(c for c in calls if c.metadata.call_id == "CALL-2026-0804-001")
    assert sc1.has_critical_error is True
    assert sc1.topic == CallTopic.COMPETITION_ENROLLMENT
    assert sc1.overall_quality_score < 50.0
