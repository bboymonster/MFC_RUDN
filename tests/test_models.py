"""Тесты моделей данных и валидации."""

from datetime import datetime
from mfc_analytics.models.call import (
    ApplicantCategory,
    Call,
    CallMetadata,
    CallOutcome,
    CallTopic,
    CriterionEvaluation,
    CriterionStatus,
    LoadRegime,
    SpeakerRole,
    Utterance,
)
from mfc_analytics.models.cms import CMSInterval


def test_call_model_creation():
    meta = CallMetadata(
        call_id="TEST-001",
        timestamp=datetime(2026, 8, 4, 10, 0, 0),
        duration_seconds=45,
        load_regime=LoadRegime.HIGH,
    )
    
    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2000, text="Добрый день!"),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2500, end_ms=5000, text="Здравствуйте!"),
    ]

    call = Call(
        metadata=meta,
        utterances=utterances,
        topic=CallTopic.COMPETITION_ENROLLMENT,
        applicant_category=ApplicantCategory.APPLICANT_RF,
        outcome=CallOutcome.RESOLVED_IN_CALL,
        overall_quality_score=95.0,
    )

    assert call.metadata.call_id == "TEST-001"
    assert len(call.utterances) == 2
    assert call.topic == CallTopic.COMPETITION_ENROLLMENT
    assert call.overall_quality_score == 95.0


def test_cms_interval_model():
    interval = CMSInterval(
        interval_start=datetime(2026, 8, 4, 11, 0, 0),
        offered_calls=50,
        answered_calls=45,
        abandoned_calls=5,
        avg_speed_of_answer_sec=42.5,
    )
    assert interval.offered_calls == 50
    assert interval.answered_calls == 45
    assert interval.abandoned_calls == 5
    assert interval.load_regime == LoadRegime.TYPICAL
