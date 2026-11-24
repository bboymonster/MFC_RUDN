"""Модуль оценки качества консультаций по 6 обязательным критериям РУДН.
Динамическая сверка с действующими регламентами и приказами университета.
"""

from datetime import datetime
import re
from typing import Dict, List, Optional, Tuple

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
from mfc_analytics.models.knowledge_base import ReferenceRule


class QualityChecker:
    """Движок проверки качества консультаций и выявления нарушений с доказательной базой."""

    # Недопустимые и грубые выражения оператора
    RUDE_PATTERNS = [
        (r"читайте на сайте", "Перенаправление на самостоятельный поиск без помощи."),
        (r"у меня очередь", "Упрёк заявителю в наличии входящей очереди."),
        (r"женщина,? у меня", "Некорректное фамильярное обращение к заявителю."),
        (r"мне некогда", "Отказ в консультации из-за дефицита времени оператора."),
        (r"не морочьте голову", "Грубое хамство и пренебрежение к вопросу заявителя."),
        (r"сколько можно звонить", "Раздражение и упрёк в повторном обращении."),
        (r"читать умеете", "Оскорбительный вопрос о грамотности заявителя."),
        (r"не отнимайте время", "Требование прекратить разговор."),
        (r"я вам уже сто раз", "Раздражение оператора при повторном вопросе."),
        (r"надо было раньше думать", "Обвинение заявителя в пропуске сроков."),
    ]

    def __init__(self, rules: Optional[List[ReferenceRule]] = None):
        self.rules: List[ReferenceRule] = list(rules) if rules else list(REFERENCE_RULES)

    def set_rules(self, rules: List[ReferenceRule]):
        """Обновляет актуальный набор эталонных правил."""
        self.rules = list(rules)

    def evaluate_call(
        self,
        utterances: List[Utterance],
        topic: CallTopic,
        category: ApplicantCategory,
        outcome: CallOutcome,
        call_time: datetime,
        custom_rules: Optional[List[ReferenceRule]] = None,
    ) -> Tuple[List[CriterionEvaluation], float, bool, Optional[str]]:
        """Проводит комплексную проверку звонка по 6 обязательным критериям РУДН."""
        evaluations: List[CriterionEvaluation] = []
        has_critical = False
        critical_summary: Optional[str] = None
        active_rules = custom_rules if custom_rules is not None else self.rules

        op_utterances = [u for u in utterances if u.speaker == SpeakerRole.OPERATOR]
        app_utterances = [u for u in utterances if u.speaker == SpeakerRole.APPLICANT]
        all_op_text = " ".join(u.text for u in op_utterances).lower()
        all_app_text = " ".join(u.text for u in app_utterances).lower()

        # 1. Понимание вопроса
        crit_understanding = self._check_understanding(category, all_app_text, all_op_text, app_utterances, op_utterances)
        evaluations.append(crit_understanding)

        # 2. Точность информации (динамическая сверка с регламентами)
        crit_accuracy = self._check_accuracy(topic, category, all_op_text, op_utterances, call_time, active_rules)
        if any(e.severity == "CRITICAL" for e in crit_accuracy.evidences):
            has_critical = True
            crit_evidence = next(e for e in crit_accuracy.evidences if e.severity == "CRITICAL")
            critical_summary = crit_evidence.explanation
        evaluations.append(crit_accuracy)

        # 3. Полнота ответа (чек-лист обязательных сведений)
        crit_completeness = self._check_completeness(topic, all_op_text, op_utterances, active_rules)
        evaluations.append(crit_completeness)

        # 4. Маршрутизация (обоснованность и информирование)
        crit_routing = self._check_routing(outcome, all_op_text, op_utterances)
        evaluations.append(crit_routing)

        # 5. Стандарты коммуникации (этика, приветствие, вежливость)
        crit_communication = self._check_communication(all_op_text, op_utterances)
        if any(e.severity == "CRITICAL" for e in crit_communication.evidences):
            has_critical = True
            crit_comm_ev = next(e for e in crit_communication.evidences if e.severity == "CRITICAL")
            critical_summary = critical_summary or crit_comm_ev.explanation
        evaluations.append(crit_communication)

        # 6. Результат консультации (исход)
        crit_result = self._check_result(outcome, crit_accuracy.score, has_critical)
        evaluations.append(crit_result)

        # Весовые коэффициенты критериев
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
        app_utterances: List[Utterance],
        op_utterances: List[Utterance],
    ) -> CriterionEvaluation:
        """Критерий 1: Понимание вопроса заявителя."""
        # 1. Если заявитель - иностранец, а оператор проигнорировал и направил на Госуслуги
        if category == ApplicantCategory.APPLICANT_INT and any(k in all_app_text for k in ["иностран", "узбекистан", "таджикистан", "казахстан", "беларусь", "виза", "паспорт"]):
            if "госуслуг" in all_op_text and "intstudent" not in all_op_text:
                return CriterionEvaluation(
                    criterion_id="understanding",
                    name="Понимание вопроса",
                    status=CriterionStatus.VIOLATED,
                    score=0.2,
                    comment="Оператор проигнорировал статус иностранного гражданина и специфику международного набора.",
                )

        # 2. Если звонок сброшен до того, как заявитель успел объяснить суть
        if not app_utterances or (len(app_utterances) == 1 and len(all_app_text.split()) < 4):
            if any(w in all_op_text for w in ["некогда", "очередь", "до свидания"]):
                return CriterionEvaluation(
                    criterion_id="understanding",
                    name="Понимание вопроса",
                    status=CriterionStatus.VIOLATED,
                    score=0.1,
                    comment="Оператор оборвал разговор, не выслушав суть обращения.",
                )

        return CriterionEvaluation(
            criterion_id="understanding",
            name="Понимание вопроса",
            status=CriterionStatus.COMPLIANT,
            score=1.0,
            comment="Вопрос и статус заявителя определены корректно.",
        )

    def _check_accuracy(
        self,
        topic: CallTopic,
        category: ApplicantCategory,
        all_op_text: str,
        op_utterances: List[Utterance],
        call_time: datetime,
        rules: List[ReferenceRule],
    ) -> CriterionEvaluation:
        """Критерий 2: Точность информации со сверкой с действующими регламентами РУДН."""
        evidences: List[Evidence] = []
        score = 1.0
        status = CriterionStatus.COMPLIANT

        # Сверка с правилами
        for rule in rules:
            # Правило применяется к приёмной кампании соответствующего года (или бессрочно)
            if rule.valid_from and call_time.year < rule.valid_from.year:
                continue
            if rule.valid_to and call_time.year > rule.valid_to.year:
                continue

            # 1. Правило дедлайна согласий на бюджет (5 августа до 12:00 МСК)
            if rule.rule_id == "RULE_CONSENT_BUDGET_DEADLINE":
                if "согласи" in all_op_text or topic == CallTopic.COMPETITION_ENROLLMENT or "оригинал" in all_op_text:
                    for u in op_utterances:
                        low = u.text.lower()
                        # Поиск ошибочного дедлайна "до вечера", "до 18:00", "до конца рабочего дня"
                        if any(w in low for w in ["до вечера", "до 18:00", "до шести", "до конца дня", "до конца рабочего", "до 19:00", "до 20:00"]):
                            ev = Evidence(
                                criterion_id="accuracy",
                                quote=u.text,
                                start_ms=u.start_ms,
                                end_ms=u.end_ms,
                                rule_id=rule.rule_id,
                                rule_version=rule.version,
                                explanation=(
                                    "Критическая дезинформация: официальный регламентный дедлайн подачи согласий "
                                    "на основном бюджетном этапе — 5 августа строго до 12:00 МСК. Назван неверный срок "
                                    "'до вечера / до 18:00', что неминуемо приведет к незачислению абитуриента."
                                ),
                                severity="CRITICAL",
                            )
                            evidences.append(ev)
                            score = 0.0
                            status = CriterionStatus.VIOLATED
                            break

            # 2. Правило дедлайна оплаты договора (24 августа до 12:00 МСК)
            elif rule.rule_id == "RULE_CONTRACT_PAYMENT_DEADLINE":
                if ("договор" in all_op_text or "оплат" in all_op_text) and "10 дней" in all_op_text:
                    if "24 августа" not in all_op_text:
                        for u in op_utterances:
                            if "10 дней" in u.text.lower():
                                ev = Evidence(
                                    criterion_id="accuracy",
                                    quote=u.text,
                                    start_ms=u.start_ms,
                                    end_ms=u.end_ms,
                                    rule_id=rule.rule_id,
                                    rule_version=rule.version,
                                    explanation=(
                                        "Неточная консультация: озвучен стандартный срок '10 дней', но скрыт "
                                        "жесткий дедлайн завершения оплаты платного набора 24 августа 12:00 МСК. "
                                        "Заявитель рискует не попасть в приказ о зачислении."
                                    ),
                                    severity="HIGH",
                                )
                                evidences.append(ev)
                                score = min(score, 0.4)
                                status = CriterionStatus.VIOLATED
                                break

            # 3. Правило каналов подачи для иностранцев (intstudent.rudn.ru)
            elif rule.rule_id == "RULE_APPLICATION_CHANNELS_INT":
                if category == ApplicantCategory.APPLICANT_INT:
                    for u in op_utterances:
                        low = u.text.lower()
                        if "госуслуг" in low and "intstudent" not in all_op_text:
                            ev = Evidence(
                                criterion_id="accuracy",
                                quote=u.text,
                                start_ms=u.start_ms,
                                end_ms=u.end_ms,
                                rule_id=rule.rule_id,
                                rule_version=rule.version,
                                explanation=(
                                    "Недостоверный канал подачи: иностранные граждане должны подавать документы через "
                                    "международный портал intstudent.rudn.ru. Портал Госуслуг для них недоступен."
                                ),
                                severity="HIGH",
                            )
                            evidences.append(ev)
                            score = min(score, 0.2)
                            status = CriterionStatus.VIOLATED
                            break

            # 4. Проверка общих пользовательских правил из реестра по common_errors
            else:
                for err_phrase in rule.common_errors:
                    err_clean = err_phrase.lower().strip("'\"«»")
                    # Проверяем, встречается ли часть ошибочной фразы в речи оператора
                    key_tokens = [w for w in err_clean.split() if len(w) > 3]
                    if len(key_tokens) >= 2 and all(tok in all_op_text for tok in key_tokens[:3]):
                        for u in op_utterances:
                            if any(tok in u.text.lower() for tok in key_tokens[:2]):
                                ev = Evidence(
                                    criterion_id="accuracy",
                                    quote=u.text,
                                    start_ms=u.start_ms,
                                    end_ms=u.end_ms,
                                    rule_id=rule.rule_id,
                                    rule_version=rule.version,
                                    explanation=f"Выявлено нарушение правила '{rule.title}': {err_phrase}",
                                    severity="MEDIUM",
                                )
                                evidences.append(ev)
                                score = min(score, 0.5)
                                status = CriterionStatus.VIOLATED
                                break

        comment = (
            "Все утверждения оператора строго соответствуют официальным регламентам РУДН."
            if not evidences
            else f"Обнаружены расхождения с регламентами ({len(evidences)} наруш.)."
        )

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
        rules: List[ReferenceRule],
    ) -> CriterionEvaluation:
        """Критерий 3: Полнота ответа (проверка чек-листа обязательных сведений)."""
        score = 1.0
        missing_items: List[str] = []

        # 1. По общежитиям
        if topic == CallTopic.DORMITORY:
            has_date = any(w in all_op_text for w in ["25 августа", "август"])
            has_med = any(w in all_op_text for w in ["флюорографи", "086", "справк", "мед"])
            has_order = any(w in all_op_text for w in ["приказ", "зачислен", "после выхода"])
            if not has_date:
                missing_items.append("дата начала заселения (с 25 августа)")
            if not has_med:
                missing_items.append("обязательные медсправки (086/у, флюорография)")
            if not has_order:
                missing_items.append("условие подачи заявления (строго после приказа)")

        # 2. По договорам и оплате
        elif topic == CallTopic.CONTRACT_AND_PAYMENT:
            if "оплат" in all_op_text or "договор" in all_op_text:
                if "24 августа" not in all_op_text and "бухгалтери" not in all_op_text:
                    missing_items.append("предельный дедлайн подтверждения оплаты (24 августа до 12:00 МСК)")

        # 3. По услугам МФЦ (справкам)
        elif topic == CallTopic.MFC_SERVICES:
            if "справк" in all_op_text:
                has_portal = any(w in all_op_text for w in ["личный кабинет", "лк", "онлайн"])
                has_timeline = any(w in all_op_text for w in ["3 дня", "три дня", "рабочих"])
                if not (has_portal or has_timeline):
                    missing_items.append("порядок онлайн-заказа через личный кабинет и срок 3 рабочих дня")

        if missing_items:
            penalty = min(0.6, len(missing_items) * 0.25)
            score = max(0.2, 1.0 - penalty)
            return CriterionEvaluation(
                criterion_id="completeness",
                name="Полнота ответа",
                status=CriterionStatus.VIOLATED if score < 0.7 else CriterionStatus.COMPLIANT,
                score=round(score, 2),
                comment=f"Не озвучены обязательные сведения: {', '.join(missing_items)}.",
            )

        return CriterionEvaluation(
            criterion_id="completeness",
            name="Полнота ответа",
            status=CriterionStatus.COMPLIANT,
            score=1.0,
            comment="Ответ содержит полный исчерпывающий чек-лист сведений.",
        )

    def _check_routing(
        self,
        outcome: CallOutcome,
        all_op_text: str,
        op_utterances: List[Utterance],
    ) -> CriterionEvaluation:
        """Критерий 4: Маршрутизация обращения."""
        # Если звонок переведен
        if outcome == CallOutcome.TRANSFERRED:
            # Проверяем, объяснил ли оператор, куда и зачем переводит
            explained = any(
                w in all_op_text
                for w in ["бухгалтери", "приемн", "специалист", "отдел", "департамент", "соединяю", "перевожу", "оставайтесь на линии"]
            )
            named_unit = any(
                w in all_op_text
                for w in ["бухгалтери", "приемн", "комисси", "рекрутинг", "деканат", "общежити", "ит"]
            )

            if not explained or not named_unit:
                return CriterionEvaluation(
                    criterion_id="routing",
                    name="Маршрутизация",
                    status=CriterionStatus.VIOLATED,
                    score=0.4,
                    comment="Перевод вызова выполнен без должного пояснения заявителю принимающего подразделения.",
                )
            return CriterionEvaluation(
                criterion_id="routing",
                name="Маршрутизация",
                status=CriterionStatus.COMPLIANT,
                score=0.9,
                comment="Обоснованный перевод с предварительным информированием заявителя.",
            )

        # Если оператор отказал в помощи без перевода
        if "не занимаемся" in all_op_text or "не знаю" in all_op_text:
            if not any(w in all_op_text for w in ["переведу", "соединяю", "обратитесь", "телефон"]):
                return CriterionEvaluation(
                    criterion_id="routing",
                    name="Маршрутизация",
                    status=CriterionStatus.VIOLATED,
                    score=0.3,
                    comment="Отказ в решении вопроса без маршрутизации в ответственное подразделение университета.",
                )

        return CriterionEvaluation(
            criterion_id="routing",
            name="Маршрутизация",
            status=CriterionStatus.COMPLIANT,
            score=1.0,
            comment="Обращение отработано на первой линии МФЦ без необоснованных переводов.",
        )

    def _check_communication(
        self,
        all_op_text: str,
        op_utterances: List[Utterance],
    ) -> CriterionEvaluation:
        """Критерий 5: Стандарты коммуникации, речевой этикет и доброжелательность."""
        evidences: List[Evidence] = []
        score = 1.0

        # 1. Поиск грубых и недопустимых речевых паттернов
        for u in op_utterances:
            low = u.text.lower()
            for pattern, expl in self.RUDE_PATTERNS:
                if re.search(pattern, low):
                    ev = Evidence(
                        criterion_id="communication",
                        quote=u.text,
                        start_ms=u.start_ms,
                        end_ms=u.end_ms,
                        rule_id="RULE_COMMUNICATION_STANDARDS",
                        rule_version="2026.1",
                        explanation=f"Грубое нарушение речевого стандарта контакт-центра МФЦ РУДН: {expl}",
                        severity="CRITICAL",
                    )
                    evidences.append(ev)
                    return CriterionEvaluation(
                        criterion_id="communication",
                        name="Стандарты коммуникации",
                        status=CriterionStatus.VIOLATED,
                        score=0.0,
                        evidences=evidences,
                        comment=f"Зафиксирована грубость оператора: {expl}",
                    )

        # 2. Проверка приветствия
        has_greeting = any(w in all_op_text for w in ["здравствуйте", "добрый день", "доброе утро", "приветствую", "мфц"])
        if not has_greeting:
            score -= 0.2

        # 3. Проверка вежливого завершения
        has_farewell = any(w in all_op_text for w in ["до свидания", "всего доброго", "всего хорошего", "удачи", "пожалуйста", "рада помочь", "рад помочь"])
        if not has_farewell:
            score -= 0.1

        return CriterionEvaluation(
            criterion_id="communication",
            name="Стандарты коммуникации",
            status=CriterionStatus.COMPLIANT,
            score=max(0.6, score),
            comment="Соблюден вежливый деловой тон общения и речевой регламент.",
        )

    def _check_result(self, outcome: CallOutcome, accuracy_score: float, has_critical: bool) -> CriterionEvaluation:
        """Критерий 6: Итоговый результат консультации."""
        if has_critical or accuracy_score == 0.0 or outcome == CallOutcome.UNRESOLVED:
            return CriterionEvaluation(
                criterion_id="result",
                name="Результат консультации",
                status=CriterionStatus.VIOLATED,
                score=0.0,
                comment="Отрицательный исход: предоставлена ложная информация либо консультация сорвана.",
            )

        if outcome in (CallOutcome.RESOLVED_IN_CALL, CallOutcome.NEXT_STEP_PROVIDED):
            return CriterionEvaluation(
                criterion_id="result",
                name="Результат консультации",
                status=CriterionStatus.COMPLIANT,
                score=1.0,
                comment="Положительный исход: вопрос решен в звонке либо предоставлен чёткий план действий.",
            )

        if outcome == CallOutcome.TRANSFERRED:
            return CriterionEvaluation(
                criterion_id="result",
                name="Результат консультации",
                status=CriterionStatus.COMPLIANT,
                score=0.85,
                comment="Консультация успешно маршрутизирована на профильного эксперта университета.",
            )

        return CriterionEvaluation(
            criterion_id="result",
            name="Результат консультации",
            status=CriterionStatus.COMPLIANT,
            score=0.75,
            comment="Зафиксировано обещание обратной связи со стороны университета.",
        )
