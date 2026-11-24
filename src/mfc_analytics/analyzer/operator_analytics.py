"""Модуль аналитики эффективности операторов контакт-центра МФЦ РУДН."""

from collections import defaultdict
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from mfc_analytics.models.call import Call, CriterionStatus, SpeakerRole


class OperatorPerformanceProfile(BaseModel):
    """Индивидуальный профиль эффективности и качества консультаций оператора."""
    operator_pseudonym: str
    total_calls: int
    average_score: float
    critical_errors_count: int
    critical_error_rate_percent: float
    avg_duration_seconds: float
    transfers_count: int
    transfer_rate_percent: float
    understanding_compliance_percent: float
    accuracy_compliance_percent: float
    completeness_compliance_percent: float
    communication_compliance_percent: float
    top_topics: List[str]
    coaching_status: str
    coaching_recommendation: str
    sample_call_ids: List[str]


class OperatorAnalyticsEngine:
    """Движок расчёта операторских метрик, выявления зон роста и рекомендаций для наставников."""

    @classmethod
    def calculate_profiles(cls, calls: List[Call]) -> List[OperatorPerformanceProfile]:
        """Рассчитывает профили всех операторов на основе пула звонков."""
        grouped: Dict[str, List[Call]] = defaultdict(list)
        for c in calls:
            op_name = c.metadata.operator_pseudonym or "Оператор первой линии"
            grouped[op_name].append(c)

        profiles: List[OperatorPerformanceProfile] = []

        for op_name, op_calls in grouped.items():
            total = len(op_calls)
            if total == 0:
                continue

            avg_score = round(sum(c.overall_quality_score for c in op_calls) / total, 1)
            critical_count = sum(1 for c in op_calls if c.has_critical_error)
            crit_rate = round(critical_count / total * 100.0, 1)
            avg_dur = round(sum(c.metadata.duration_seconds for c in op_calls) / total, 1)

            transfers = sum(1 for c in op_calls if c.outcome.value == "Переведен в профильное подразделение")
            transfer_rate = round(transfers / total * 100.0, 1)

            # Расчет соблюдения отдельных критериев
            def get_crit_rate(crit_id: str) -> float:
                compliant = 0
                total_applicable = 0
                for c in op_calls:
                    for ev in c.criteria_evaluations:
                        if ev.criterion_id == crit_id:
                            total_applicable += 1
                            if ev.status == CriterionStatus.COMPLIANT:
                                compliant += 1
                return round(compliant / max(1, total_applicable) * 100.0, 1)

            understanding_rate = get_crit_rate("understanding")
            accuracy_rate = get_crit_rate("accuracy")
            completeness_rate = get_crit_rate("completeness")
            comm_rate = get_crit_rate("communication")

            # Топ тематик оператора
            topic_counts = defaultdict(int)
            for c in op_calls:
                topic_counts[c.topic.value] += 1
            top_topics = [t for t, _ in sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:3]]

            # Рекомендации по наставничеству
            if critical_count > 0:
                coaching_status = "ТРЕБУЕТСЯ РАЗБОР"
                if comm_rate < 70.0:
                    coaching_recommendation = "Тренинг по стрессоустойчивости и речевым стандартам в часы пик."
                else:
                    coaching_recommendation = "Индивидуальный инструктаж по нормативным дедлайнам приёмной кампании 2026."
            elif avg_score < 75.0:
                coaching_status = "ПЛАНОВОЕ ДООБУЧЕНИЕ"
                coaching_recommendation = "Проработка полноты ответов и чек-листа обязательных сведений."
            else:
                coaching_status = "ЭТАЛОН"
                coaching_recommendation = "Рекомендован в качестве наставника для новых стажёров МФЦ."

            profile = OperatorPerformanceProfile(
                operator_pseudonym=op_name,
                total_calls=total,
                average_score=avg_score,
                critical_errors_count=critical_count,
                critical_error_rate_percent=crit_rate,
                avg_duration_seconds=avg_dur,
                transfers_count=transfers,
                transfer_rate_percent=transfer_rate,
                understanding_compliance_percent=understanding_rate,
                accuracy_compliance_percent=accuracy_rate,
                completeness_compliance_percent=completeness_rate,
                communication_compliance_percent=comm_rate,
                top_topics=top_topics,
                coaching_status=coaching_status,
                coaching_recommendation=coaching_recommendation,
                sample_call_ids=[c.metadata.call_id for c in op_calls[:4]],
            )
            profiles.append(profile)

        # Сортировка по общему баллу качества (по убыванию рейтинга)
        profiles.sort(key=lambda x: x.average_score, reverse=True)
        return profiles
