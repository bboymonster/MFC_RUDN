"""Модуль оценки качества консультаций по 6 обязательным критериям РУДН."""

from datetime import datetime
from typing import List, Optional, Tuple

from mfc_analytics.data.seed_rules import REFERENCE_RULES
from mfc_analytics.models.call import (
    ApplicantCategory,
    CallOutcome,
    CallTopic,
    CriterionEvaluation,
    CriterionStatus,
    Evidence,
    SpeakerRole,
    Utterance,
)


class QualityChecker:
    """Движок проверки качества консультаций и выявления нарушений с доказательствами."""

    def __init__(self):
        self.rules = REFERENCE_RULES

    def evaluate_call(
        self,
        utterances: List[Utterance],
        topic: CallTopic,
        category: ApplicantCategory,
        outcome: CallOutcome,
        call_time: datetime,
    ) -> Tuple[List[CriterionEvaluation], float, bool, Optional[str]]:
        """Проводит комплексную оценку звонка по 6 критериям качества."""
        evaluations: List[CriterionEvaluation] = []
        has_critical = False
        critical_summary: Optional[str] = None

        op_utterances = [u for u in utterances if u.speaker == SpeakerRole.OPERATOR]
        app_utterances = [u for u in utterances if u.speaker == SpeakerRole.APPLICANT]
        all_op_text = " ".join(u.text for u in op_utterances).lower()
        all_app_text = " ".join(u.text for u in app_utterances).lower()

        # 1. Понимание вопроса
        crit_understanding = self._check_understanding(category, all_app_text, all_op_text, op_utterances)
        evaluations.append(crit_understanding)

        # 2. Точность информации (сверка с эталонами)
        crit_accuracy = self._check_accuracy(topic, category, all_op_text, op_utterances, call_time)
        if any(e.severity == "CRITICAL" for e in crit_accuracy.evidences):
            has_critical = True
            critical_summary = crit_accuracy.evidences[0].explanation
        evaluations.append(crit_accuracy)

        # 3. Полнота ответа
        crit_completeness = self._check_completeness(topic, all_op_text, op_utterances)
        evaluations.append(crit_completeness)

        # 4. Маршрутизация
        crit_routing = self._check_routing(outcome, all_op_text, op_utterances)
        evaluations.append(crit_routing)

        # 5. Стандарты коммуникации
        crit_communication = self._check_communication(all_op_text, op_utterances)
        if any(e.severity == "CRITICAL" for e in crit_communication.evidences):
            has_critical = True
            critical_summary = critical_summary or crit_communication.evidences[0].explanation
        evaluations.append(crit_communication)

        # 6. Результат консультации
        crit_result = self._check_result(outcome, crit_accuracy.score)
        evaluations.append(crit_result)

        # Расчет итогового балла (0 - 100)
        # Если есть критическая ошибка, итоговый балл штрафуется на 50%
        weights = {
            "understanding": 0.15,
            "accuracy": 0.30,
            "completeness": 0.20,
            "routing": 0.10,
            "communication": 0.15,
            "result": 0.10,
        }

        total_score = sum(ev.score * weights.get(ev.criterion_id, 0.1) for ev in evaluations) * 100.0
        if has_critical:
            total_score = min(total_score, 40.0)

        total_score = round(max(0.0, min(100.0, total_score)), 1)
        return evaluations, total_score, has_critical, critical_summary

    def _check_understanding(
        self,
        category: ApplicantCategory,
        all_app_text: str,
        all_op_text: str,
        op_utterances: List[Utterance],
    ) -> CriterionEvaluation:
        """Критерий 1: Понимание вопроса заявителя."""
        # Если заявитель иностранец, а оператор этого не учел
        if category == ApplicantCategory.APPLICANT_INT and ("узбекистан" in all_app_text or "иностран" in all_app_text):
            if "госуслуги" in all_op_text and "intstudent" not in all_op_text:
                return CriterionEvaluation(
                    criterion_id="understanding",
                    name="Понимание вопроса",
                    status=CriterionStatus.VIOLATED,
                    score=0.2,
                    comment="Оператор проигнорировал статус иностранного гражданина.",
                )

        # Если вопрос вообще не был выслушан (менее 1 реплики заявителя)
        if not op_utterances or len(op_utterances) == 1 and "слушаю" in all_op_text:
            return CriterionEvaluation(
                criterion_id="understanding",
                name="Понимание вопроса",
                status=CriterionStatus.VIOLATED,
                score=0.1,
                comment="Оператор прервал диалог, не выслушав вопрос.",
            )

        return CriterionEvaluation(
            criterion_id="understanding",
            name="Понимание вопроса",
            status=CriterionStatus.COMPLIANT,
            score=1.0,
            comment="Вопрос и категория заявителя определены корректно.",
        )

    def _check_accuracy(
        self,
        topic: CallTopic,
        category: ApplicantCategory,
        all_op_text: str,
        op_utterances: List[Utterance],
        call_time: datetime,
    ) -> CriterionEvaluation:
        """Критерий 2: Точность информации со сверкой с эталонными правилами."""
        evidences: List[Evidence] = []
        score = 1.0
        status = CriterionStatus.COMPLIANT

        # Проверка 1: Дедлайн согласия на бюджет (5 августа до 12:00 МСК)
        if "согласи" in all_op_text or topic == CallTopic.COMPETITION_ENROLLMENT:
            for u in op_utterances:
                low = u.text.lower()
                if "до вечера" in low or "до 18:00" in low or "до шести" in low or "до конца дня" in low:
                    ev = Evidence(
                        criterion_id="accuracy",
                        quote=u.text,
                        start_ms=u.start_ms,
                        end_ms=u.end_ms,
                        rule_id="RULE_CONSENT_BUDGET_DEADLINE",
                        rule_version="2026.1",
                        explanation="Критическая ошибка: официальный дедлайн согласий на основном этапе бюджета — 5 августа строго до 12:00 МСК. Оператор назвал 'до вечера'/'до 18:00'.",
                        severity="CRITICAL",
                    )
                    evidences.append(ev)
                    score = 0.0
                    status = CriterionStatus.VIOLATED
                    break

        # Проверка 2: Иностранец отправлен на Госуслуги
        if category == ApplicantCategory.APPLICANT_INT:
            for u in op_utterances:
                low = u.text.lower()
                if "госуслуг" in low and "intstudent" not in all_op_text:
                    ev = Evidence(
                        criterion_id="accuracy",
                        quote=u.text,
                        start_ms=u.start_ms,
                        end_ms=u.end_ms,
                        rule_id="RULE_APPLICATION_CHANNELS_INT",
                        rule_version="2026.1",
                        explanation="Недостоверный канал: иностранные граждане должны подавать документы через международный портал intstudent.rudn.ru, портал Госуслуг для них недоступен.",
                        severity="HIGH",
                    )
                    evidences.append(ev)
                    score = min(score, 0.2)
                    status = CriterionStatus.VIOLATED
                    break

        # Проверка 3: Оплата договора и предельный дедлайн 24 августа
        if "10 дней" in all_op_text and "договор" in all_op_text:
            if "24 августа" not in all_op_text:
                for u in op_utterances:
                    if "10 дней" in u.text.lower():
                        ev = Evidence(
                            criterion_id="accuracy",
                            quote=u.text,
                            start_ms=u.start_ms,
                            end_ms=u.end_ms,
                            rule_id="RULE_CONTRACT_PAYMENT_DEADLINE",
                            rule_version="2026.1",
                            explanation="Неточная консультация: указан общий срок '10 дней', но не озвучен жесткий дедлайн оплаты 24 августа до 12:00 МСК.",
                            severity="HIGH",
                        )
                        evidences.append(ev)
                        score = min(score, 0.4)
                        status = CriterionStatus.VIOLATED
                        break

        comment = "Все утверждения соответствуют официальным эталонам РУДН." if not evidences else "Обнаружены расхождения с нормативными правилами приёма."
        return CriterionEvaluation(
            criterion_id="accuracy",
            name="Точность информации",
            status=status,
            score=score,
            evidences=evidences,
            comment=comment,
        )

    def _check_completeness(
        self,
        topic: CallTopic,
        all_op_text: str,
        op_utterances: List[Utterance],
    ) -> CriterionEvaluation:
        """Критерий 3: Полнота ответа (чек-лист обязательных сведений)."""
        score = 1.0
        evidences: List[Evidence] = []

        # По общежитию: обязателен список меддокументов (флюорография) и дата старта
        if topic == CallTopic.DORMITORY:
            has_date = "25 августа" in all_op_text or "август" in all_op_text
            has_med = "флюорографи" in all_op_text or "086" in all_op_text or "справк" in all_op_text
            if not (has_date and has_med):
                score = 0.5
                return CriterionEvaluation(
                    criterion_id="completeness",
                    name="Полнота ответа",
                    status=CriterionStatus.VIOLATED,
                    score=score,
                    comment="Не озвучен полный чек-лист для заселения (сроки заселения или обязательные медицинские справки).",
                )

        return CriterionEvaluation(
            criterion_id="completeness",
            name="Полнота ответа",
            status=CriterionStatus.COMPLIANT,
            score=score,
            comment="Ответ содержит исчерпывающие сведения по запросу.",
        )

    def _check_routing(
        self,
        outcome: CallOutcome,
        all_op_text: str,
        op_utterances: List[Utterance],
    ) -> CriterionEvaluation:
        """Критерий 4: Маршрутизация."""
        if outcome == CallOutcome.TRANSFERRED:
            # Проверяем, объяснил ли оператор цель перевода
            explained = any(w in all_op_text for w in ["бухгалтери", "приемн", "специалист", "отдел", "департамент"])
            if not explained:
                return CriterionEvaluation(
                    criterion_id="routing",
                    name="Маршрутизация",
                    status=CriterionStatus.VIOLATED,
                    score=0.4,
                    comment="Перевод вызова выполнен без указания принимающего подразделения.",
                )
            return CriterionEvaluation(
                criterion_id="routing",
                name="Маршрутизация",
                status=CriterionStatus.COMPLIANT,
                score=0.9,
                comment="Корректный перевод с информированием заявителя.",
            )

        return CriterionEvaluation(
            criterion_id="routing",
            name="Маршрутизация",
            status=CriterionStatus.COMPLIANT,
            score=1.0,
            comment="Вопрос решен на первой линии МФЦ без избыточных переводов.",
        )

    def _check_communication(
        self,
        all_op_text: str,
        op_utterances: List[Utterance],
    ) -> CriterionEvaluation:
        """Критерий 5: Стандарты коммуникации и этика."""
        evidences: List[Evidence] = []
        score = 1.0

        # Поиск недопустимых выражений и грубости
        rude_patterns = [
            "читайте на сайте",
            "у меня очередь",
            "женщина, у меня",
            "мне некогда",
            "не морочьте голову",
            "сколько можно звонить",
        ]

        for u in op_utterances:
            low = u.text.lower()
            for pattern in rude_patterns:
                if pattern in low:
                    ev = Evidence(
                        criterion_id="communication",
                        quote=u.text,
                        start_ms=u.start_ms,
                        end_ms=u.end_ms,
                        rule_id="RULE_COMMUNICATION_STANDARDS",
                        rule_version="2026.1",
                        explanation="Грубое нарушение стандарта телефонного обслуживания: раздражение, упрек заявителю в наличии очереди или отказ в помощи.",
                        severity="CRITICAL",
                    )
                    evidences.append(ev)
                    return CriterionEvaluation(
                        criterion_id="communication",
                        name="Стандарты коммуникации",
                        status=CriterionStatus.VIOLATED,
                        score=0.0,
                        evidences=evidences,
                        comment="Зафиксировано некорректное/грубое поведение оператора.",
                    )

        # Проверка приветствия
        has_greeting = any(w in all_op_text for w in ["здравствуйте", "добрый день", "доброе утро", "приветствую", "мфц"])
        if not has_greeting:
            score -= 0.2

        # Проверка вежливого завершения
        has_farewell = any(w in all_op_text for w in ["до свидания", "всего доброго", "всего хорошего", "удачи", "пожалуйста"])
        if not has_farewell:
            score -= 0.1

        return CriterionEvaluation(
            criterion_id="communication",
            name="Стандарты коммуникации",
            status=CriterionStatus.COMPLIANT,
            score=max(0.6, score),
            comment="Соблюден доброжелательный деловой тон.",
        )

    def _check_result(self, outcome: CallOutcome, accuracy_score: float) -> CriterionEvaluation:
        """Критерий 6: Результат консультации."""
        if accuracy_score == 0.0 or outcome == CallOutcome.UNRESOLVED:
            return CriterionEvaluation(
                criterion_id="result",
                name="Результат консультации",
                status=CriterionStatus.VIOLATED,
                score=0.0,
                comment="Результат отрицательный: ответ ошибочный либо консультация сорвана.",
            )

        if outcome in (CallOutcome.RESOLVED_IN_CALL, CallOutcome.NEXT_STEP_PROVIDED):
            return CriterionEvaluation(
                criterion_id="result",
                name="Результат консультации",
                status=CriterionStatus.COMPLIANT,
                score=1.0,
                comment="Вопрос заявителя закрыт либо дан четкий маршрут действий.",
            )

        return CriterionEvaluation(
            criterion_id="result",
            name="Результат консультации",
            status=CriterionStatus.COMPLIANT,
            score=0.8,
            comment="Вопрос направлен на второй уровень поддержки.",
        )
