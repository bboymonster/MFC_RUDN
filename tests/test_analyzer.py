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


def test_quality_checker_international_wrong_portal():
    checker = QualityChecker()
    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2000, text="МФЦ РУДН, добрый день!"),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2500, end_ms=7000, text="Я иностранный гражданин из Узбекистана, как подать документы?"),
        Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=7500, end_ms=13000, text="Все подают через Госуслуги, регистрируйтесь там."),
    ]
    evals, score, has_crit, _ = checker.evaluate_call(
        utterances=utterances,
        topic=CallTopic.INTERNATIONAL_QUESTIONS,
        category=ApplicantCategory.APPLICANT_INT,
        outcome=CallOutcome.UNRESOLVED,
        call_time=datetime(2026, 7, 15, 12, 0, 0),
    )
    acc = next(e for e in evals if e.criterion_id == "accuracy")
    assert acc.status.value == "Нарушен"
    assert any(ev.rule_id == "RULE_APPLICATION_CHANNELS_INT" for ev in acc.evidences)


def test_quality_checker_hostile_communication():
    checker = QualityChecker()
    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=1500, text="МФЦ, слушаю."),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2000, end_ms=5000, text="Не могу найти приказ о зачислении..."),
        Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=5500, end_ms=10000, text="Женщина, у меня тридцать звонков в очереди! Читайте на сайте!"),
    ]
    evals, score, has_crit, crit_sum = checker.evaluate_call(
        utterances=utterances,
        topic=CallTopic.COMPETITION_ENROLLMENT,
        category=ApplicantCategory.PARENT,
        outcome=CallOutcome.UNRESOLVED,
        call_time=datetime(2026, 8, 1, 16, 0, 0),
    )
    assert has_crit is True
    assert score <= 40.0
    comm = next(e for e in evals if e.criterion_id == "communication")
    assert comm.status.value == "Нарушен"


def test_quality_checker_dormitory_completeness():
    checker = QualityChecker()
    # Missing medical requirements
    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2000, text="Здравствуйте! МФЦ РУДН."),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2500, end_ms=6000, text="Как заселиться в общежитие?"),
        Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=6500, end_ms=10000, text="Заселение с 25 августа. Приезжайте."),
    ]
    evals, score, has_crit, _ = checker.evaluate_call(
        utterances=utterances,
        topic=CallTopic.DORMITORY,
        category=ApplicantCategory.APPLICANT_RF,
        outcome=CallOutcome.RESOLVED_IN_CALL,
        call_time=datetime(2026, 7, 10, 10, 0, 0),
    )
    comp = next(e for e in evals if e.criterion_id == "completeness")
    assert comp.score < 1.0  # Penalized for missing medical checklist items


def test_diarization_talk_listen_and_speech_rate():
    from mfc_analytics.audio.diarization import ChannelDiarizer
    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=10000, text="Здравствуйте! Контакт-центр МФЦ РУДН. Чем могу вам помочь сегодня?"),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=11000, end_ms=20000, text="Здравствуйте! Подскажите, пожалуйста, где можно ознакомиться с приказами о зачислении на бюджетные места?"),
    ]
    metrics = ChannelDiarizer.calculate_talk_listen_metrics(utterances, total_duration_seconds=22)
    assert "operator_talk_pct" in metrics
    assert "applicant_talk_pct" in metrics
    assert "silence_pct" in metrics
    assert "operator_speech_rate_wpm" in metrics
    assert metrics["operator_talk_pct"] > 0
    assert metrics["applicant_talk_pct"] > 0
    assert metrics["operator_speech_rate_wpm"] > 0


def test_diarization_interruption_detection():
    from mfc_analytics.audio.diarization import ChannelDiarizer
    # Overlapping speech
    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=6000, text="Да, вы можете подать документы через личный кабинет абитуриента..."),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=4500, end_ms=9000, text="А через Госуслуги можно? Подождите, скажите!"),
    ]
    interruptions = ChannelDiarizer.detect_interruptions(utterances, min_overlap_ms=500)
    assert len(interruptions) == 1
    assert interruptions[0]["overlap_ms"] == 1500
    assert interruptions[0]["interrupter"] == "Заявитель"


def test_systemic_issues_clustering_and_actions():
    from mfc_analytics.analyzer.systemic_issues import SystemicIssueDetector
    from mfc_analytics.data.generator import MFCDataGenerator
    from mfc_analytics.analyzer.pipeline import MFCAnalyticsPipeline

    gen = MFCDataGenerator(random_seed=42)
    pipe = MFCAnalyticsPipeline()
    calls = [pipe.analyze_call(c) for c in gen.generate_curated_calls()[:15]]

    detector = SystemicIssueDetector()
    summary = detector.analyze_batch(calls)
    assert "top_systemic_issues" in summary
    assert len(summary["top_systemic_issues"]) > 0
    assert "suggested_actions" in summary
    assert len(summary["suggested_actions"]) > 0
    top = summary["top_systemic_issues"][0]
    assert "title" in top
    assert "root_cause" in top
    assert "share_percent" in top
