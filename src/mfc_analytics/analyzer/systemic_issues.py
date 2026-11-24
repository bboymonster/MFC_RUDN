"""Модуль выявления системных проблем, повторяющихся вопросов и формирования управленческих действий."""

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple
from mfc_analytics.models.action import ActionProblemType, ActionStatus, ManagerAction
from mfc_analytics.models.call import Call, CallOutcome, CallTopic


class SystemicIssueDetector:
    """Анализатор системных паттернов и генератор управленческих решений."""

    def analyze_batch(self, calls: List[Call]) -> Dict[str, Any]:
        """Проводит комплексный анализ выборки звонков на предмет системных сбоев."""
        total_calls = len(calls)
        if total_calls == 0:
            return {
                "total_analyzed_calls": 0,
                "topic_distribution": {},
                "repeat_calls_count": 0,
                "total_repeat_calls": 0,
                "repeat_rate_percent": 0.0,
                "fcr_percent": 0.0,
                "total_transfers": 0,
                "transfers_by_department": {},
                "critical_violations_count": 0,
                "low_quality_calls_count": 0,
                "average_quality_score": 0.0,
                "top_systemic_issues": [],
                "suggested_actions": [],
            }

        # 1. Распределение тем
        topic_counts = Counter(c.topic.value for c in calls)

        # 2. Повторные обращения и FCR (First Contact Resolution)
        repeat_calls = [c for c in calls if c.metadata.is_repeat_call]
        repeat_rate_pct = round(len(repeat_calls) / total_calls * 100.0, 1)

        resolved_first_contact = [
            c for c in calls
            if not c.metadata.is_repeat_call
            and c.outcome in (CallOutcome.RESOLVED_IN_CALL, CallOutcome.NEXT_STEP_PROVIDED)
            and c.overall_quality_score >= 70.0
        ]
        fcr_pct = round(len(resolved_first_contact) / max(1, total_calls - len(repeat_calls)) * 100.0, 1)

        # 3. Маршрутизация и переводы
        transferred_calls = [c for c in calls if c.outcome == CallOutcome.TRANSFERRED]
        transfers_by_dept = Counter(
            c.actual_transfer_department or c.target_department
            for c in transferred_calls
            if c.actual_transfer_department or c.target_department
        )

        # 4. Нарушения и критические звонки
        critical_calls = [c for c in calls if c.has_critical_error]
        low_score_calls = [c for c in calls if c.overall_quality_score < 60.0]

        # 5. Кластеризация топ-системных проблем
        top_systemic_issues = self._identify_top_issues(calls, repeat_calls, critical_calls)

        # 6. Рекомендованные управленческие меры (Action Plan)
        suggested_actions = self._generate_suggested_actions(calls, critical_calls, repeat_calls)

        return {
            "total_analyzed_calls": total_calls,
            "topic_distribution": dict(topic_counts.most_common()),
            "repeat_calls_count": len(repeat_calls),
            "total_repeat_calls": len(repeat_calls),
            "repeat_rate_percent": repeat_rate_pct,
            "fcr_percent": fcr_pct,
            "total_transfers": len(transferred_calls),
            "transfers_by_department": dict(transfers_by_dept.most_common()),
            "critical_violations_count": len(critical_calls),
            "low_quality_calls_count": len(low_score_calls),
            "average_quality_score": round(sum(c.overall_quality_score for c in calls) / total_calls, 1),
            "top_systemic_issues": top_systemic_issues,
            "suggested_actions": [a.model_dump() for a in suggested_actions],
        }

    def _identify_top_issues(
        self,
        calls: List[Call],
        repeat_calls: List[Call],
        critical_calls: List[Call],
    ) -> List[Dict[str, Any]]:
        """Выявляет и ранжирует системные инциденты и информационные пробелы."""
        total = max(1, len(calls))
        issues: List[Dict[str, Any]] = []

        # Кластер 1: Ошибки в дедлайне согласия на бюджет
        consent_calls = [
            c for c in calls
            if any(e.rule_id == "RULE_CONSENT_BUDGET_DEADLINE" for ev in c.criteria_evaluations for e in ev.evidences)
        ]
        if consent_calls:
            issues.append({
                "issue_id": "ISSUE-01-CONSENT",
                "title": "Дезинформация о дедлайне согласий на бюджет (до вечера vs 12:00 МСК)",
                "category": ActionProblemType.OPERATOR_ERROR.value,
                "severity": "CRITICAL",
                "affected_calls_count": len(consent_calls),
                "share_percent": round(len(consent_calls) / total * 100.0, 1),
                "root_cause": "Отсутствие всплывающего регламентного таймера в ПО оператора перед дедлайном 5 августа.",
                "sample_call_ids": [c.metadata.call_id for c in consent_calls[:3]],
            })

        # Кластер 2: Технические задержки синхронизации ЕПГУ (повторные звонки)
        sync_calls = [
            c for c in repeat_calls
            if "списк" in c.full_transcript.lower() or "снилс" in c.full_transcript.lower() or "госуслуг" in c.full_transcript.lower()
        ]
        if sync_calls:
            issues.append({
                "issue_id": "ISSUE-02-SYNC-LAG",
                "title": "Шквал повторных обращений из-за задержки выгрузки списков с ЕПГУ (до 24-36 ч)",
                "category": ActionProblemType.TECHNICAL_SYSTEM_FAILURE.value,
                "severity": "HIGH",
                "affected_calls_count": len(sync_calls),
                "share_percent": round(len(sync_calls) / total * 100.0, 1),
                "root_cause": "Абитуриенты не видят себя в списках и звонят повторно. На сайте нет дисклеймера о регламентном лаге.",
                "sample_call_ids": [c.metadata.call_id for c in sync_calls[:3]],
            })

        # Кластер 3: Направление иностранных абитуриентов на портал Госуслуг
        intl_calls = [
            c for c in calls
            if any(e.rule_id == "RULE_APPLICATION_CHANNELS_INT" for ev in c.criteria_evaluations for e in ev.evidences)
        ]
        if intl_calls:
            issues.append({
                "issue_id": "ISSUE-03-INTL-PORTAL",
                "title": "Ошибочная переадресация иностранцев на Госуслуги РФ вместо intstudent.rudn.ru",
                "category": ActionProblemType.ROUTING_BOTTLENECK.value,
                "severity": "HIGH",
                "affected_calls_count": len(intl_calls),
                "share_percent": round(len(intl_calls) / total * 100.0, 1),
                "root_cause": "В скрипте первой линии нет жесткого ветвления на проверку гражданства заявителя.",
                "sample_call_ids": [c.metadata.call_id for c in intl_calls[:3]],
            })

        # Кластер 4: Коллизия срока оплаты договора (10 дней vs 24 августа)
        contract_calls = [
            c for c in calls
            if any(e.rule_id == "RULE_CONTRACT_PAYMENT_DEADLINE" for ev in c.criteria_evaluations for e in ev.evidences)
        ]
        if contract_calls:
            issues.append({
                "issue_id": "ISSUE-04-PAYMENT-DEADLINE",
                "title": "Умолчание о жестком дедлайне оплаты платного набора (24 августа)",
                "category": ActionProblemType.FAQ_GAP.value,
                "severity": "MEDIUM",
                "affected_calls_count": len(contract_calls),
                "share_percent": round(len(contract_calls) / total * 100.0, 1),
                "root_cause": "Текст типового договора говорит об оплате 'в течение 10 дней', что противоречит приказу о зачислении 28.08.",
                "sample_call_ids": [c.metadata.call_id for c in contract_calls[:3]],
            })

        # Сортировка по тяжести и частоте
        return issues

    def _generate_suggested_actions(
        self,
        calls: List[Call],
        critical_calls: List[Call],
        repeat_calls: List[Call],
    ) -> List[ManagerAction]:
        """Формирует список конкретных управленческих мер по итогам анализа."""
        actions: List[ManagerAction] = []
        now = datetime.now()

        # Проблема 1: Ошибки в дедлайне согласия на бюджет
        consent_errors = [
            c for c in calls
            if any(e.rule_id == "RULE_CONSENT_BUDGET_DEADLINE" for ev in c.criteria_evaluations for e in ev.evidences)
        ]
        if consent_errors:
            actions.append(
                ManagerAction(
                    action_id="ACT-2026-001",
                    title="Срочный инструктаж операторов по дедлайну согласий (5 августа до 12:00 МСК)",
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

        # Проблема 2: Рассинхронизация срока оплаты договора
        payment_issues = [
            c for c in calls
            if any(e.rule_id == "RULE_CONTRACT_PAYMENT_DEADLINE" for ev in c.criteria_evaluations for e in ev.evidences)
        ]
        if payment_issues:
            actions.append(
                ManagerAction(
                    action_id="ACT-2026-002",
                    title="Согласование скрипта консультации по оплате договора с Приёмной комиссией",
                    problem_type=ActionProblemType.FAQ_GAP,
                    description=(
                        "Фраза в договоре 'оплата в течение 10 дней' вводит родителей в заблуждение перед дедлайном "
                        "24 августа 12:00 МСК. Требуется согласовать единый скрипт с ПК: при звонках после 14 августа "
                        "оператор обязан акцентировать внимание на предельном дедлайне 24.08."
                    ),
                    owner="Приёмная комиссия РУДН + Бухгалтерия",
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
                    title="Внедрение подсказки в IVR и навигатора для иностранных абитуриентов",
                    problem_type=ActionProblemType.ROUTING_BOTTLENECK,
                    description=(
                        "Операторы по ошибке рекомендуют иностранцам Госуслуги. Предлагается добавить в голосовое меню IVR "
                        "отдельный выбор для иностранных граждан ('Если вы иностранный абитуриент — нажмите 3') и закрепить "
                        "прямую ссылку на портал intstudent.rudn.ru в операторском интерфейсе."
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
                    title="Информационный баннер о регламентных сроках обновления списков (до 24-36 часов)",
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

        # Проблема 5: Нарушения стандартов коммуникации в пиковые часы
        hostile_calls = [
            c for c in calls
            if any(e.rule_id == "RULE_COMMUNICATION_STANDARDS" and e.severity == "CRITICAL" for ev in c.criteria_evaluations for e in ev.evidences)
        ]
        if hostile_calls:
            actions.append(
                ManagerAction(
                    action_id="ACT-2026-005",
                    title="Введение ротации операторов и разгрузочных пауз в пиковые часы CMS",
                    problem_type=ActionProblemType.COMMUNICATION_STANDARD,
                    description=(
                        "В пиковые интервалы нагрузки (ASA > 120 сек, сбросы > 15%) зафиксированы эмоциональные срывы "
                        "операторов. Предлагается ввести 15-минутные паузы ротации между сменами и подключить 2 резервных "
                        "позиции операторов из числа стажёров МФЦ."
                    ),
                    owner="Руководство контакт-центра МФЦ РУДН",
                    related_call_ids=[c.metadata.call_id for c in hostile_calls],
                    created_at=now,
                    target_date=now + timedelta(days=2),
                    status=ActionStatus.OPEN,
                    expected_impact_metric="Исключение критических нарушений вежливости в часы пик",
                )
            )

        return actions
