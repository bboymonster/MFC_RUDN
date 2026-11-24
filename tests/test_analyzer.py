"""Тесты модуля классификации и проверки качества."""

from datetime import datetime
from mfc_analytics.analyzer.classifier import CallClassifier
from mfc_analytics.analyzer.pipeline import MFCAnalyticsPipeline
from mfc_analytics.analyzer.quality_checker import QualityChecker
from mfc_analytics.models.call import (
    ApplicantCategory,
    Call,
    CallMetadata,
    CallOutcome,
    CallTopic,
    SpeakerRole,
    Utterance,
)


def test_classifier_topics_and_categories():
    classifier = CallClassifier()
    
    # Тема: согласие на зачисление
    topic, _ = classifier.classify_topic("Подскажите срок подачи согласия на бюджет бакалавриата и оригинал аттестата")
    assert topic == CallTopic.COMPETITION_ENROLLMENT

    # Тема: договор и оплата
    topic, _ = classifier.classify_topic("Как заключить договор на платное обучение и оплатить квитанцию через банк?")
    assert topic == CallTopic.CONTRACT_AND_PAYMENT

    # Категория: родитель
    category = classifier.classify_applicant_category("Здравствуйте, я мама абитуриента, поступающего на экономический факультет")
    assert category == ApplicantCategory.PARENT

    # Категория: иностранный абитуриент
    category = classifier.classify_applicant_category("Я иностранный гражданин из Казахстана, хочу поступить в РУДН")
    assert category == ApplicantCategory.APPLICANT_INT


def test_quality_checker_critical_consent_error():
    checker = QualityChecker()
    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2000, text="МФЦ РУДН, здравствуйте!"),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2500, end_ms=6000, text="До какого времени 5 августа можно подать согласие?"),
        Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=6500, end_ms=12000, text="Вы можете привезти согласие до вечера 5 августа, часов до 18:00."),
    ]
    
    evals, score, has_crit, crit_sum = checker.evaluate_call(
        utterances=utterances,
        topic=CallTopic.COMPETITION_ENROLLMENT,
        category=ApplicantCategory.APPLICANT_RF,
        outcome=CallOutcome.RESOLVED_IN_CALL,
        call_time=datetime(2026, 8, 4, 11, 0, 0),
    )

    assert has_crit is True
    assert score <= 40.0
    accuracy_eval = next(e for e in evals if e.criterion_id == "accuracy")
    assert accuracy_eval.status.value == "Нарушен"
    assert len(accuracy_eval.evidences) > 0
    assert accuracy_eval.evidences[0].rule_id == "RULE_CONSENT_BUDGET_DEADLINE"


def test_pipeline_end_to_end():
    pipeline = MFCAnalyticsPipeline()
    meta = CallMetadata(
        call_id="TEST-E2E",
        timestamp=datetime(2026, 7, 10, 10, 0, 0),
        duration_seconds=30,
    )
    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2000, text="Добрый день! МФЦ РУДН, оператор Дарья."),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2500, end_ms=6000, text="Когда начнется заселение в общежитие и какие медсправки нужны?"),
        Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=6500, end_ms=14000, text="Заселение с 25 августа. Заявление после приказа. Нужна справка 086/у и флюорография."),
    ]
    call = Call(metadata=meta, utterances=utterances)
    analyzed = pipeline.analyze_call(call)
    
    assert analyzed.topic == CallTopic.DORMITORY
    assert analyzed.overall_quality_score >= 80.0
    assert analyzed.has_critical_error is False
