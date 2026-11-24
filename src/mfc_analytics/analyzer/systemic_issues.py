"""Модуль выявления системных проблем, повторяющихся вопросов и формирования управленческих действий."""

from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from mfc_analytics.models.action import ActionProblemType, ActionStatus, ManagerAction
from mfc_analytics.models.call import Call, CallOutcome, CallTopic


class SystemicIssueDetector:
    """Анализатор системных паттернов и генератор управленческих решений."""

    def analyze_batch(self, calls: List[Call]) -> Dict:
        """Проводит комплексный анализ выборки звонков на предмет системных сбоев."""
        total_calls = len(calls)
        if total_calls == 0:
            return {}

        # 1. Анализ распределения тем
        topic_counts = Counter(c.topic.value for c in calls)
        
        # 2. Анализ повторных обращений и FCR
        repeat_calls = [c for c in calls if c.metadata.is_repeat_call]
        repeat_rate_pct = round(len(repeat_calls) / total_calls * 100.0, 1)
        
        resolved_first_contact = [
            c for c in calls
            if not c.metadata.is_repeat_call
            and c.outcome in (CallOutcome.RESOLVED_IN_CALL, CallOutcome.NEXT_STEP_PROVIDED)
            and c.overall_quality_score >= 70.0
        ]
        fcr_pct = round(len(resolved_first_contact) / max(1, total_calls - len(repeat_calls)) * 100.0, 1)

        # 3. Анализ узких мест маршрутизации
        transferred_calls = [c for c in calls if c.outcome == CallOutcome.TRANSFERRED]
        transfers_by_dept = Counter(
            c.actual_transfer_department or c.target_department
            for c in transferred_calls
        )

        # 4. Анализ нарушений и критических инцидентов
        critical_calls = [c for c in calls if c.has_critical_error]
        low_score_calls = [c for c in calls if c.overall_quality_score < 60.0]

        # 5. Генерация рекомендованных управленческих действий
        suggested_actions = self._generate_suggested_actions(calls, critical_calls, repeat_calls)

        return {
            "total_analyzed_calls": total_calls,
            "topic_distribution": dict(topic_counts.most_common()),
            "repeat_calls_count": len(repeat_calls),
            "repeat_rate_percent": repeat_rate_pct,
            "fcr_percent": fcr_pct,
            "total_transfers": len(transferred_calls),
            "transfers_by_department": dict(transfers_by_dept.most_common()),
            "critical_violations_count": len(critical_calls),
            "low_quality_calls_count": len(low_score_calls),
            "average_quality_score": round(sum(c.overall_quality_score for c in calls) / total_calls, 1),
            "suggested_actions": [a.model_dump() for a in suggested_actions],
        }

    def _generate_suggested_actions(
        self,
        calls: List[Call],
        critical_calls: List[Call],
        repeat_calls: List[Call],
    ) -> List[ManagerAction]:
        """Формирует список конкретных управленческих мер по итогам анализа."""
        actions: List[ManagerAction] = []
        now = datetime.now()

        # Проблема 1: Ошибки в дедлайне согласия на бюджет (5 августа 12:00)
        consent_errors = [
            c for c in calls
            if any(e.rule_id == "RULE_CONSENT_BUDGET_DEADLINE" for ev in c.criteria_evaluations for e in ev.evidences)
        ]
        if consent_errors:
            actions.append(
                ManagerAction(
                    action_id="ACT-2026-001",
                    title="Срочный инструктаж по дедлайну согласий (5 августа до 12:00 МСК)",
                    problem_type=ActionProblemType.OPERATOR_ERROR,
                    description=(
                        "Выявлены случаи дезинформации заявителей: операторы называют срок 'до 18:00' или 'до конца дня' "
                        "вместо строгого дедлайна 12:00 МСК 5 августа. Необходимо выпустить срочную памятку-всплывающее "
                        "окно в операторском ПО и провести 10-минутный разбор на планерке."
                    ),
                    owner="МФЦ РУДН (Отдел контроля качества)",
                    related_call_ids=[c.metadata.call_id for c in consent_errors],
                    created_at=now,
                    target_date=now + timedelta(days=1),
                    status=ActionStatus.OPEN,
                    expected_impact_metric="100% корректных консультаций по срокам подачи согласия",
                )
            )

        # Проблема 2: Рассинхронизация срока оплаты договора (10 дней vs 24 августа)
        payment_issues = [
            c for c in calls
            if any(e.rule_id == "RULE_CONTRACT_PAYMENT_DEADLINE" for ev in c.criteria_evaluations for e in ev.evidences)
        ]
        if payment_issues:
            actions.append(
                ManagerAction(
                    action_id="ACT-2026-002",
                    title="Согласование шаблона консультации по оплате договора с Приёмной комиссией",
                    problem_type=ActionProblemType.FAQ_GAP,
                    description=(
                        "Фраза в договоре 'оплата в течение 10 дней' вводит родителей в заблуждение перед дедлайном "
                        "24 августа 12:00 МСК. Требуется согласовать единый скрипт с ПК: при звонках после 14 августа "
                        "оператор обязан акцентировать внимание на предельном дедлайне 24.08."
                    ),
                    owner="Приёмная комиссия РУДН + МФЦ",
                    related_call_ids=[c.metadata.call_id for c in payment_issues],
                    created_at=now,
                    target_date=now + timedelta(days=3),
                    status=ActionStatus.IN_PROGRESS,
                    expected_impact_metric="Исключение жалоб на срыв сроков включения в приказы на зачисление",
                )
            )

        # Проблема 3: Направление иностранных граждан на портал Госуслуг
        intl_issues = [
            c for c in calls
            if any(e.rule_id == "RULE_APPLICATION_CHANNELS_INT" for ev in c.criteria_evaluations for e in ev.evidences)
        ]
        if intl_issues:
            actions.append(
                ManagerAction(
                    action_id="ACT-2026-003",
                    title="Внедрение подсказки в IVR и навигатор для иностранных абитуриентов",
                    problem_type=ActionProblemType.ROUTING_BOTTLENECK,
                    description=(
                        "Операторы по ошибке рекомендуют иностранцам Госуслуги. Предлагается добавить в IVR отдельную ветку "
                        "для иностранных граждан ('Если вы иностранный абитуриент — нажмите 3') и закрепить прямую ссылку "
                        "на международный портал intstudent.rudn.ru в шапке базы знаний оператора."
                    ),
                    owner="Департамент рекрутинга иностранных обучающихся + ИТ",
                    related_call_ids=[c.metadata.call_id for c in intl_issues],
                    created_at=now,
                    target_date=now + timedelta(days=5),
                    status=ActionStatus.OPEN,
                    expected_impact_metric="Снижение ошибочной маршрутизации иностранцев до 0%",
                )
            )

        # Проблема 4: Задержка синхронизации конкурсных списков ЕПГУ
        tech_repeats = [
            c for c in calls
            if c.metadata.is_repeat_call and c.topic == CallTopic.APPLICATION_AND_STATUS
        ]
        if tech_repeats:
            actions.append(
                ManagerAction(
                    action_id="ACT-2026-004",
                    title="Информационный баннер о регламентных сроках обновления списков (до 24 часов)",
                    problem_type=ActionProblemType.TECHNICAL_SYSTEM_FAILURE,
                    description=(
                        "Массовые повторные звонки абитуриентов вызваны тревогой из-за задержки появления их СНИЛС в списках. "
                        "ИТ-департаменту необходимо вывести предупреждение на сайте: 'Сведения с Госуслуг обновляются "
                        "в течение 24 часов'."
                    ),
                    owner="ИТ-департамент РУДН",
                    related_call_ids=[c.metadata.call_id for c in tech_repeats],
                    created_at=now,
                    target_date=now + timedelta(days=2),
                    status=ActionStatus.OPEN,
                    expected_impact_metric="Снижение повторных звонков по статусу заявления на 35%",
                )
            )

        return actions
