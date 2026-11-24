"""Единый аналитический пайплайн обработки звонков МФЦ."""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from mfc_analytics.analyzer.classifier import CallClassifier
from mfc_analytics.analyzer.llm_evaluator import SemanticQualityEvaluator
from mfc_analytics.analyzer.quality_checker import QualityChecker
from mfc_analytics.analyzer.systemic_issues import SystemicIssueDetector
from mfc_analytics.data.seed_rules import REFERENCE_RULES
from mfc_analytics.models.call import (
    Call,
    CallMetadata,
    CallOutcome,
    CallTopic,
    CriterionStatus,
    Utterance,
)
from mfc_analytics.models.knowledge_base import ReferenceRule


class MFCAnalyticsPipeline:
    """Пайплайн пакетной и потоковой аналитики телефонных звонков контакт-центра."""

    def __init__(self, rules: Optional[List[ReferenceRule]] = None):
        self._rules: List[ReferenceRule] = list(rules) if rules else list(REFERENCE_RULES)
        self.classifier = CallClassifier()
        self.quality_checker = QualityChecker(rules=self._rules)
        self.semantic_evaluator = SemanticQualityEvaluator()
        self.systemic_detector = SystemicIssueDetector()

    @property
    def rules(self) -> List[ReferenceRule]:
        return self._rules

    @rules.setter
    def rules(self, new_rules: List[ReferenceRule]):
        self._rules = list(new_rules)
        self.quality_checker.set_rules(self._rules)

    def analyze_call(self, call: Call) -> Call:
        """Выполняет полный цикл обработки одного звонка: классификацию и оценку качества."""
        full_text = " ".join(u.text for u in call.utterances)
        call.full_transcript = full_text

        # 1. Классификация темы и заявителя
        primary_topic, add_topics = self.classifier.classify_topic(full_text)
        if call.topic == CallTopic.OTHER or not call.topic:
            call.topic = primary_topic
        call.additional_topics = add_topics

        call.applicant_category = self.classifier.classify_applicant_category(full_text)
        call.inquiry_type = self.classifier.classify_inquiry_type(full_text)
        call.outcome = self.classifier.classify_outcome(call.utterances)

        # 2. Проверка качества по 6 критериям со сверкой с базой знаний
        evaluations, score, has_crit, crit_summary = self.quality_checker.evaluate_call(
            utterances=call.utterances,
            topic=call.topic,
            category=call.applicant_category,
            outcome=call.outcome,
            call_time=call.metadata.timestamp,
            custom_rules=self._rules,
        )

        # 3. Глубокий семантический анализ (скрытая агрессия, нюансы регламентов)
        nuance_evidences = self.semantic_evaluator.evaluate_dialogue_nuances(
            utterances=call.utterances,
            rules=self._rules,
        )
        if nuance_evidences:
            for ev in nuance_evidences:
                target_crit = next((e for e in evaluations if e.criterion_id == ev.criterion_id), None)
                if target_crit:
                    target_crit.status = CriterionStatus.VIOLATED
                    target_crit.score = min(target_crit.score, 0.4)
                    target_crit.evidences.append(ev)
                    score = min(score, 60.0)

        call.criteria_evaluations = evaluations
        call.overall_quality_score = score
        call.has_critical_error = has_crit
        call.critical_error_summary = crit_summary

        return call

    def analyze_batch(self, calls: List[Call]) -> Tuple[List[Call], Dict]:
        """Пакетный анализ списка звонков с вычислением общесистемных показателей."""
        processed_calls = [self.analyze_call(c) for c in calls]
        systemic_summary = self.systemic_detector.analyze_batch(processed_calls)
        return processed_calls, systemic_summary
