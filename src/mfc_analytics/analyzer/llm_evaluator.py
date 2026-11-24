"""Модуль семантического анализа и глубокой проверки качества консультаций."""

import re
from typing import Dict, List, Optional
from mfc_analytics.models.call import (
    ApplicantCategory,
    CriterionEvaluation,
    CriterionStatus,
    Evidence,
    SpeakerRole,
    Utterance,
)
from mfc_analytics.models.knowledge_base import ReferenceRule


class SemanticQualityEvaluator:
    """Глубокий анализатор тональности, скрытого сарказма и соответствия регламентам."""

    # Паттерны скрытой грубости и сарказма
    PASSIVE_AGGRESSION_PATTERNS = [
        r"конечно,? ведь нам больше делать нечего",
        r"вы вообще слышите,? что я говорю",
        r"я вам уже сто раз сказал",
        r"надо было раньше думать",
        r"читать умеете",
        r"не отнимайте время",
    ]

    def evaluate_dialogue_nuances(
        self,
        utterances: List[Utterance],
        rules: List[ReferenceRule],
    ) -> List[Evidence]:
        """Выявляет тонкие речевые нарушения, скрытый сарказм и пассивную агрессию."""
        evidences: List[Evidence] = []
        op_utterances = [u for u in utterances if u.speaker == SpeakerRole.OPERATOR]

        for u in op_utterances:
            low = u.text.lower()

            # 1. Поиск скрытого сарказма / пассивной агрессии
            for pattern in self.PASSIVE_AGGRESSION_PATTERNS:
                if re.search(pattern, low):
                    evidences.append(
                        Evidence(
                            criterion_id="communication",
                            quote=u.text,
                            start_ms=u.start_ms,
                            end_ms=u.end_ms,
                            rule_id="RULE_COMMUNICATION_STANDARDS",
                            rule_version="2026.1",
                            explanation="Обнаружена скрытая пассивная агрессия и раздражение в адрес заявителя.",
                            severity="HIGH",
                        )
                    )

            # 2. Необоснованный отказ в консультации
            if "я этим не занимаюсь" in low and not any(w in low for w in ["переведу", "соединяю", "обратитесь"]):
                evidences.append(
                    Evidence(
                        criterion_id="routing",
                        quote=u.text,
                        start_ms=u.start_ms,
                        end_ms=u.end_ms,
                        rule_id="RULE_COMMUNICATION_STANDARDS",
                        rule_version="2026.1",
                        explanation="Отказ в помощи без маршрутизации заявителя в профильное подразделение.",
                        severity="MEDIUM",
                    )
                )

        return evidences
