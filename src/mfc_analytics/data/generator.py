"""Генератор реалистичных синтетических данных для контакт-центра МФЦ РУДН.
Создает интервалы Avaya CMS и корпус звонков приёмной кампании 2026 года.
"""

from datetime import datetime, timedelta
import hashlib
import random
from typing import Dict, List, Tuple

from mfc_analytics.models.call import (
    ApplicantCategory,
    Call,
    CallMetadata,
    CallOutcome,
    CallTopic,
    CriterionEvaluation,
    CriterionStatus,
    Evidence,
    InquiryType,
    LoadRegime,
    ManagerStatus,
    SpeakerRole,
    Utterance,
)
from mfc_analytics.models.cms import CMSInterval, CMSReportSummary
from mfc_analytics.data.seed_rules import DEPARTMENTS, REFERENCE_RULES


def _pseudonymize(seed_str: str) -> str:
    """Генерирует устойчивый псевдоним по строке для соблюдения 152-ФЗ."""
    h = hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:8]
    return f"Заявитель_{h}"


class MFCDataGenerator:
    """Генератор демонстрационного датасета для воркшопа МФЦ РУДН."""

    def __init__(self, random_seed: int = 42):
        self.rng = random.Random(random_seed)

    def generate_cms_intervals(
        self,
        start_date: datetime = datetime(2026, 6, 20, 9, 0),
        days_count: int = 65,
    ) -> List[CMSInterval]:
        """Генерирует 30-минутные интервалы Avaya CMS с 9:00 до 19:00 за указанный период."""
        intervals: List[CMSInterval] = []
        
        # Ключевые пиковые даты приёмной кампании РУДН 2026
        peak_dates = {
            (6, 20), (6, 22),          # Старт приема
            (7, 9), (7, 10),           # Дедлайн бюджета для ДВИ
            (7, 24), (7, 25), (7, 27), # Дедлайн бюджета ЕГЭ/БВИ и публикация списков
            (8, 4), (8, 5),            # Согласие на бюджет до 12:00
            (8, 18), (8, 20),          # Контрактные дедлайны
            (8, 21), (8, 24),          # Дедлайн договоров и оплаты 24 августа
        }

        current_date = start_date
        end_date = start_date + timedelta(days=days_count)

        while current_date < end_date:
            is_sunday = current_date.weekday() == 6
            is_saturday = current_date.weekday() == 5
            
            # Воскресенье - выходной
            if is_sunday:
                current_date += timedelta(days=1)
                continue

            is_peak_day = (current_date.month, current_date.day) in peak_dates
            
            # Генерация интервалов с 09:00 до 19:00 (суббота до 15:00)
            end_hour = 15 if is_saturday else 19
            day_cursor = current_date.replace(hour=9, minute=0, second=0)

            while day_cursor.hour < end_hour:
                hour = day_cursor.hour
                # Пиковые часы дня
                is_peak_hour = hour in (10, 11, 12, 16)
                
                if is_peak_day and is_peak_hour:
                    offered = self.rng.randint(65, 120)
                    answered = int(offered * self.rng.uniform(0.70, 0.85))
                    positions = self.rng.randint(6, 8)
                    asa = round(self.rng.uniform(90.0, 240.0), 1)
                    regime = LoadRegime.HIGH
                elif is_peak_day or is_peak_hour:
                    offered = self.rng.randint(35, 64)
                    answered = int(offered * self.rng.uniform(0.85, 0.94))
                    positions = self.rng.randint(5, 7)
                    asa = round(self.rng.uniform(30.0, 85.0), 1)
                    regime = LoadRegime.TYPICAL
                else:
                    offered = self.rng.randint(8, 30)
                    answered = int(offered * self.rng.uniform(0.92, 0.98))
                    positions = self.rng.randint(4, 5)
                    asa = round(self.rng.uniform(5.0, 25.0), 1)
                    regime = LoadRegime.LOW

                abandoned = max(0, offered - answered)
                aht = round(self.rng.uniform(140.0, 310.0), 1)
                service_level = round(100.0 * (answered / offered if offered > 0 else 1.0), 1)

                interval = CMSInterval(
                    interval_start=day_cursor,
                    interval_minutes=30,
                    queue_vdn="VDN_MFC_RUDN",
                    offered_calls=offered,
                    answered_calls=answered,
                    abandoned_calls=abandoned,
                    avg_speed_of_answer_sec=asa,
                    avg_handle_time_sec=aht,
                    active_agent_positions=positions,
                    service_level_percent=service_level,
                    load_regime=regime,
                )
                intervals.append(interval)
                day_cursor += timedelta(minutes=30)

            current_date += timedelta(days=1)

        return intervals

    def generate_curated_calls(self) -> List[Call]:
        """Генерирует калиброванный эталонный корпус звонков, включая ключевые сценарии из ТЗ."""
        calls: List[Call] = []

        # Сценарий 1: Критическая ошибка в дедлайне согласия (4 августа)
        calls.append(self._create_scenario_1_critical_consent_error())

        # Сценарий 2: Неполный ответ и некорректный срок оплаты договора (21 августа)
        calls.append(self._create_scenario_2_incomplete_payment_deadline())

        # Сценарий 3: Иностранец отправлен на Госуслуги вместо международного портала (15 июля)
        calls.append(self._create_scenario_3_international_wrong_portal())

        # Сценарий 4: Повторный звонок заявителя из-за рассинхронизации списков (26 июля)
        calls.append(self._create_scenario_4_repeat_call_competition_lists())

        # Сценарий 5: Нарушение стандарта коммуникации (грубость, сброс звонка)
        calls.append(self._create_scenario_5_hostile_communication())

        # Сценарий 6: Идеальная консультация по общежитию (100% соблюдение стандартов)
        calls.append(self._create_scenario_6_perfect_dormitory_consultation())

        # Дополнительные типовые звонки для наполнения выборки до 30+ звонков
        additional = self._generate_additional_realistic_calls(count=26)
        calls.extend(additional)

        return calls

    def _create_scenario_1_critical_consent_error(self) -> Call:
        """Сценарий 1 из исследования: оператор назвал ошибочный дедлайн согласия."""
        timestamp = datetime(2026, 8, 4, 11, 42, 10)
        utterances = [
            Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2800, text="Добрый день! Единый контакт-центр МФЦ РУДН, оператор Анна. Чем могу вам помочь?"),
            Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=3100, end_ms=9500, text="Здравствуйте! Подскажите, пожалуйста, я поступаю на бюджетный бакалавриат по общему конкурсу. До какого времени завтра нужно предоставить согласие на зачисление и оригинал аттестата?"),
            Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=10100, end_ms=17200, text="Завтра, пятого августа, вы можете спокойно подать оригинал до вечера, где-то до 18:00 или до конца рабочего дня приёмной комиссии.", is_key_evidence=True),
            Utterance(id=4, speaker=SpeakerRole.APPLICANT, start_ms=17600, end_ms=21000, text="То есть если мы к 16 часам подъедем с родителями, то успеем?"),
            Utterance(id=5, speaker=SpeakerRole.OPERATOR, start_ms=21400, end_ms=26200, text="Да, успеете, главное завтра привезти. Комиссия принимает документы до шести вечера.", is_key_evidence=True),
            Utterance(id=6, speaker=SpeakerRole.APPLICANT, start_ms=26800, end_ms=28500, text="Понял вас, спасибо большое!"),
            Utterance(id=7, speaker=SpeakerRole.OPERATOR, start_ms=28900, end_ms=31200, text="Пожалуйста, хорошего вам дня! До свидания."),
        ]
        
        meta = CallMetadata(
            call_id="CALL-2026-0804-001",
            ucid="UCID-882319001",
            timestamp=timestamp,
            duration_seconds=32,
            queue_name="VDN_MFC_RUDN",
            load_regime=LoadRegime.HIGH,
            operator_pseudonym="Оператор №14 (Анна)",
            applicant_pseudonym=_pseudonymize("applicant_ivan_401"),
            is_repeat_call=False,
        )

        evidence = Evidence(
            criterion_id="accuracy",
            quote="Завтра, пятого августа, вы можете спокойно подать оригинал до вечера, где-то до 18:00... Комиссия принимает документы до шести вечера.",
            start_ms=10100,
            end_ms=26200,
            rule_id="RULE_CONSENT_BUDGET_DEADLINE",
            rule_version="2026.1",
            explanation="Критическая ошибка: официальный дедлайн подачи согласий на основном этапе бюджета — 5 августа строго до 12:00 МСК. Заявитель рискует не поступить на бюджет при явке в 16:00.",
            severity="CRITICAL",
        )

        criteria = [
            CriterionEvaluation(criterion_id="understanding", name="Понимание вопроса", status=CriterionStatus.COMPLIANT, score=1.0, comment="Суть вопроса понята."),
            CriterionEvaluation(criterion_id="accuracy", name="Точность информации", status=CriterionStatus.VIOLATED, score=0.0, evidences=[evidence], comment="Грубая дезинформация о сроке согласия."),
            CriterionEvaluation(criterion_id="completeness", name="Полнота ответа", status=CriterionStatus.VIOLATED, score=0.4, comment="Не озвучен часовой пояс и возможность подачи через Госуслуги."),
            CriterionEvaluation(criterion_id="routing", name="Маршрутизация", status=CriterionStatus.COMPLIANT, score=1.0, comment="Вопрос в компетенции линии МФЦ."),
            CriterionEvaluation(criterion_id="communication", name="Стандарты коммуникации", status=CriterionStatus.COMPLIANT, score=0.9, comment="Вежливо, без нарушений тональности."),
            CriterionEvaluation(criterion_id="result", name="Результат консультации", status=CriterionStatus.VIOLATED, score=0.0, comment="Ответ дан ошибочный, вопрос приведет к срыву зачисления."),
        ]

        return Call(
            metadata=meta,
            utterances=utterances,
            full_transcript=" ".join(u.text for u in utterances),
            topic=CallTopic.COMPETITION_ENROLLMENT,
            applicant_category=ApplicantCategory.APPLICANT_RF,
            inquiry_type=InquiryType.CONSULTATION,
            target_department="Приёмная комиссия РУДН (для граждан РФ)",
            outcome=CallOutcome.RESOLVED_IN_CALL,
            overall_quality_score=38.0,
            has_critical_error=True,
            critical_error_summary="Ошибочно названо время согласия: 'до 18:00' вместо строгого регламента 'до 12:00 МСК 5 августа'.",
            criteria_evaluations=criteria,
            manager_status=ManagerStatus.PENDING,
        )

    def _create_scenario_2_incomplete_payment_deadline(self) -> Call:
        """Сценарий 2: родитель спрашивает про оплату договора, не назван дедлайн 24.08."""
        timestamp = datetime(2026, 8, 21, 14, 15, 22)
        utterances = [
            Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2500, text="Контакт-центр МФЦ РУДН, здравствуйте! Чем могу помочь?"),
            Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2800, end_ms=10500, text="Добрый день! Я мама абитуриентки. Мы сегодня оформили договор на платное обучение на экономику. В договоре написано 'оплата в течение 10 дней'. До какого числа нам нужно внести деньги?"),
            Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=11000, end_ms=17500, text="Ну раз в договоре написано 10 дней, оплачивайте спокойно в течение 10 дней. Сейчас я переведу вас на бухгалтерию, там подтвердят.", is_key_evidence=True),
            Utterance(id=4, speaker=SpeakerRole.APPLICANT, start_ms=18000, end_ms=20500, text="Подождите, а приказ когда выходит?"),
            Utterance(id=5, speaker=SpeakerRole.OPERATOR, start_ms=21000, end_ms=23500, text="Оставайтесь на линии, соединяю с бухгалтерией.", is_key_evidence=True),
        ]

        meta = CallMetadata(
            call_id="CALL-2026-0821-002",
            ucid="UCID-882319002",
            timestamp=timestamp,
            duration_seconds=25,
            queue_name="VDN_MFC_RUDN",
            load_regime=LoadRegime.HIGH,
            operator_pseudonym="Оператор №08 (Михаил)",
            applicant_pseudonym=_pseudonymize("parent_elena_209"),
            is_repeat_call=False,
        )

        evidence = Evidence(
            criterion_id="completeness",
            quote="Ну раз в договоре написано 10 дней, оплачивайте спокойно в течение 10 дней.",
            start_ms=11000,
            end_ms=17500,
            rule_id="RULE_CONTRACT_PAYMENT_DEADLINE",
            rule_version="2026.1",
            explanation="Неполный и потенциально ошибочный ответ: крайний срок оплаты для основного платного набора — 24 августа до 12:00 МСК (через 3 дня), а не через 10 дней. Приказ выходит 28 августа.",
            severity="HIGH",
        )

        criteria = [
            CriterionEvaluation(criterion_id="understanding", name="Понимание вопроса", status=CriterionStatus.COMPLIANT, score=0.9, comment="Запрос на срок оплаты."),
            CriterionEvaluation(criterion_id="accuracy", name="Точность информации", status=CriterionStatus.VIOLATED, score=0.4, evidences=[evidence], comment="Игнорирование предельного дедлайна 24 августа."),
            CriterionEvaluation(criterion_id="completeness", name="Полнота ответа", status=CriterionStatus.VIOLATED, score=0.3, comment="Не озвучен дедлайн 24.08 12:00 и дата приказа."),
            CriterionEvaluation(criterion_id="routing", name="Маршрутизация", status=CriterionStatus.VIOLATED, score=0.5, comment="Перевод без предварительного разъяснения ситуации."),
            CriterionEvaluation(criterion_id="communication", name="Стандарты коммуникации", status=CriterionStatus.COMPLIANT, score=0.8, comment="Нейтрально, но перевод оборвал разговор."),
            CriterionEvaluation(criterion_id="result", name="Результат консультации", status=CriterionStatus.COMPLIANT, score=0.6, comment="Переведен в профильное подразделение."),
        ]

        return Call(
            metadata=meta,
            utterances=utterances,
            full_transcript=" ".join(u.text for u in utterances),
            topic=CallTopic.CONTRACT_AND_PAYMENT,
            applicant_category=ApplicantCategory.PARENT,
            inquiry_type=InquiryType.PROCEDURE,
            target_department="Приёмная комиссия РУДН (для граждан РФ)",
            actual_transfer_department="Управление бухгалтерского учёта и финансового контроля",
            outcome=CallOutcome.TRANSFERRED,
            overall_quality_score=52.0,
            has_critical_error=False,
            criteria_evaluations=criteria,
            manager_status=ManagerStatus.PENDING,
        )

    def _create_scenario_3_international_wrong_portal(self) -> Call:
        """Сценарий 3: иностранного абитуриента отправили на Госуслуги."""
        timestamp = datetime(2026, 7, 15, 12, 10, 45)
        utterances = [
            Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2700, text="Добрый день! МФЦ РУДН, оператор Виктория. Слушаю вас."),
            Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=3000, end_ms=11200, text="Здравствуйте! Я гражданин Узбекистана, сейчас нахожусь в Ташкенте. Хочу поступить к вам в Медицинский институт на Лечебное дело. Как мне подать документы дистанционно?"),
            Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=11800, end_ms=18400, text="Все заявления подаются через портал Госуслуг, суперсервис 'Поступление в вуз онлайн'. Заходите туда и прикрепляете документы.", is_key_evidence=True),
            Utterance(id=4, speaker=SpeakerRole.APPLICANT, start_ms=19000, end_ms=23800, text="А если у меня нет российского паспорта и СНИЛС, я смогу зарегистрироваться на Госуслугах?"),
            Utterance(id=5, speaker=SpeakerRole.OPERATOR, start_ms=24200, end_ms=28500, text="Ой, ну вообще все через Госуслуги подают. Попробуйте там, если не получится — перезвоните.", is_key_evidence=True),
            Utterance(id=6, speaker=SpeakerRole.APPLICANT, start_ms=29000, end_ms=31000, text="Э-э, ладно... Спасибо."),
        ]

        meta = CallMetadata(
            call_id="CALL-2026-0715-003",
            ucid="UCID-882319003",
            timestamp=timestamp,
            duration_seconds=32,
            queue_name="VDN_MFC_RUDN",
            load_regime=LoadRegime.TYPICAL,
            operator_pseudonym="Оператор №21 (Виктория)",
            applicant_pseudonym=_pseudonymize("applicant_farrukh_uz"),
            is_repeat_call=False,
        )

        evidence = Evidence(
            criterion_id="accuracy",
            quote="Все заявления подаются через портал Госуслуг, суперсервис 'Поступление в вуз онлайн'. Заходите туда и прикрепляете документы.",
            start_ms=11800,
            end_ms=18400,
            rule_id="RULE_APPLICATION_CHANNELS_INT",
            rule_version="2026.1",
            explanation="Ошибочный канал подачи: иностранные граждане без СНИЛС подают документы через международный портал intstudent.rudn.ru, а не через портал Госуслуг РФ.",
            severity="HIGH",
        )

        criteria = [
            CriterionEvaluation(criterion_id="understanding", name="Понимание вопроса", status=CriterionStatus.VIOLATED, score=0.2, comment="Оператор проигнорировал статус иностранного гражданина."),
            CriterionEvaluation(criterion_id="accuracy", name="Точность информации", status=CriterionStatus.VIOLATED, score=0.1, evidences=[evidence], comment="Направление на неподходящий портал."),
            CriterionEvaluation(criterion_id="completeness", name="Полнота ответа", status=CriterionStatus.VIOLATED, score=0.2, comment="Не назван портал intstudent.rudn.ru и требования к переводам."),
            CriterionEvaluation(criterion_id="routing", name="Маршрутизация", status=CriterionStatus.VIOLATED, score=0.2, comment="Не переведён в департамент международного рекрутинга."),
            CriterionEvaluation(criterion_id="communication", name="Стандарты коммуникации", status=CriterionStatus.COMPLIANT, score=0.7, comment="Без грубости, но консультация бесполезна."),
            CriterionEvaluation(criterion_id="result", name="Результат консультации", status=CriterionStatus.VIOLATED, score=0.1, comment="Вопрос остался не решен."),
        ]

        return Call(
            metadata=meta,
            utterances=utterances,
            full_transcript=" ".join(u.text for u in utterances),
            topic=CallTopic.INTERNATIONAL_QUESTIONS,
            applicant_category=ApplicantCategory.APPLICANT_INT,
            inquiry_type=InquiryType.PROCEDURE,
            target_department="Департамент рекрутинга и сопровождения иностранных обучающихся",
            outcome=CallOutcome.UNRESOLVED,
            overall_quality_score=25.0,
            has_critical_error=False,
            critical_error_summary="Иностранного абитуриента отправили на Госуслуги РФ вместо международного портала intstudent.rudn.ru.",
            criteria_evaluations=criteria,
            manager_status=ManagerStatus.PENDING,
        )

    def _create_scenario_4_repeat_call_competition_lists(self) -> Call:
        """Сценарий 4: повторный звонок (абитуриент не видит себя в списках)."""
        timestamp = datetime(2026, 7, 26, 14, 20, 0)
        utterances = [
            Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2400, text="МФЦ РУДН, оператор Сергей. Здравствуйте!"),
            Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2700, end_ms=13800, text="Здравствуйте! Я звоню уже в третий раз за эти два дня! Мое заявление принято на Госуслугах ещё 23 июля, но в списках на сайте РУДН меня до сих пор нет! Позавчера мне сказали 'ждите вечера', вчера 'ждите утра'. Конкурсные списки уже завтра публикуются, а меня нет!"),
            Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=14300, end_ms=24000, text="Понимаю ваше беспокойство. Не волнуйтесь, из-за пиковой нагрузки на шлюз Госуслуг выгрузка в базу приёмной комиссии идёт с задержкой до 24-36 часов. Продиктуйте номер вашего СНИЛС или номер заявления на ЕПГУ, я проверю технический статус в системе."),
            Utterance(id=4, speaker=SpeakerRole.APPLICANT, start_ms=24500, end_ms=29000, text="СНИЛС 142-883-991 70. Заявление номер 492001."),
            Utterance(id=5, speaker=SpeakerRole.OPERATOR, start_ms=30000, end_ms=39500, text="Вижу ваше заявление. Оно находится в статусе 'Успешно импортировано', сейчас проходит финальную валидацию модератором ПК. К сегодняшнему вечеру, к 20:00, ваш СНИЛС появится в пофамильном перечне."),
            Utterance(id=6, speaker=SpeakerRole.APPLICANT, start_ms=40000, end_ms=43000, text="Ох, спасибо вам огромное, Сергей! Хоть один оператор всё проверил и объяснил!"),
            Utterance(id=7, speaker=SpeakerRole.OPERATOR, start_ms=43500, end_ms=47000, text="Рад помочь! Если к 21:00 запись не появится, звоните сразу в ПК РФ. Удачи в конкурсе!"),
        ]

        meta = CallMetadata(
            call_id="CALL-2026-0726-004",
            ucid="UCID-882319004",
            timestamp=timestamp,
            duration_seconds=48,
            queue_name="VDN_MFC_RUDN",
            load_regime=LoadRegime.HIGH,
            operator_pseudonym="Оператор №03 (Сергей)",
            applicant_pseudonym=_pseudonymize("applicant_dmitry_repeat"),
            is_repeat_call=True,
            previous_call_id="CALL-2026-0724-889",
        )

        criteria = [
            CriterionEvaluation(criterion_id="understanding", name="Понимание вопроса", status=CriterionStatus.COMPLIANT, score=1.0, comment="Снял тревожность, точно определил проблему."),
            CriterionEvaluation(criterion_id="accuracy", name="Точность информации", status=CriterionStatus.COMPLIANT, score=1.0, comment="Проверил реальный технический статус в базе."),
            CriterionEvaluation(criterion_id="completeness", name="Полнота ответа", status=CriterionStatus.COMPLIANT, score=1.0, comment="Назван четкий дедлайн обновления и план действий."),
            CriterionEvaluation(criterion_id="routing", name="Маршрутизация", status=CriterionStatus.COMPLIANT, score=1.0, comment="Решено на первой линии без перевода."),
            CriterionEvaluation(criterion_id="communication", name="Стандарты коммуникации", status=CriterionStatus.COMPLIANT, score=1.0, comment="Эмпатия, профессионализм, соблюдение скрипта."),
            CriterionEvaluation(criterion_id="result", name="Результат консультации", status=CriterionStatus.COMPLIANT, score=1.0, comment="Вопрос полностью решен."),
        ]

        return Call(
            metadata=meta,
            utterances=utterances,
            full_transcript=" ".join(u.text for u in utterances),
            topic=CallTopic.APPLICATION_AND_STATUS,
            applicant_category=ApplicantCategory.APPLICANT_RF,
            inquiry_type=InquiryType.TECHNICAL_ISSUE,
            target_department="Приёмная комиссия РУДН (для граждан РФ)",
            outcome=CallOutcome.RESOLVED_IN_CALL,
            overall_quality_score=100.0,
            has_critical_error=False,
            criteria_evaluations=criteria,
            manager_status=ManagerStatus.RESOLVED,
            manager_notes="Эталонная отработка повторного обращения и технической задержки ЕПГУ.",
        )

    def _create_scenario_5_hostile_communication(self) -> Call:
        """Сценарий 5: грубость оператора и бросание трубки в час пик."""
        timestamp = datetime(2026, 8, 1, 16, 52, 10)
        utterances = [
            Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=1500, text="МФЦ, слушаю."),
            Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=1800, end_ms=8500, text="Здравствуйте... Подскажите, пожалуйста, я не могу понять, где в личном кабинете нажать подтверждение для согласия..."),
            Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=8800, end_ms=16000, text="Женщина, у меня тридцать звонков в очереди висит! Читайте инструкцию на сайте, там крупными буквами всё написано! До свидания.", is_key_evidence=True),
        ]

        meta = CallMetadata(
            call_id="CALL-2026-0801-005",
            ucid="UCID-882319005",
            timestamp=timestamp,
            duration_seconds=17,
            queue_name="VDN_MFC_RUDN",
            load_regime=LoadRegime.HIGH,
            operator_pseudonym="Оператор №19 (Ольга)",
            applicant_pseudonym=_pseudonymize("applicant_nervous_mom"),
            is_repeat_call=False,
        )

        evidence = Evidence(
            criterion_id="communication",
            quote="Женщина, у меня тридцать звонков в очереди висит! Читайте инструкцию на сайте, там крупными буквами всё написано! До свидания.",
            start_ms=8800,
            end_ms=16000,
            rule_id="RULE_COMMUNICATION_STANDARDS",
            rule_version="2026.1",
            explanation="Грубое нарушение стандарта телефонного обслуживания: перебивание заявителя, раздражение, отказ в помощи и односторонний сброс вызова.",
            severity="CRITICAL",
        )

        criteria = [
            CriterionEvaluation(criterion_id="understanding", name="Понимание вопроса", status=CriterionStatus.VIOLATED, score=0.1, comment="Вопрос не выслушан."),
            CriterionEvaluation(criterion_id="accuracy", name="Точность информации", status=CriterionStatus.INSUFFICIENT_DATA, score=0.5, comment="Информация не предоставлена."),
            CriterionEvaluation(criterion_id="completeness", name="Полнота ответа", status=CriterionStatus.VIOLATED, score=0.0, comment="Консультация сорвана."),
            CriterionEvaluation(criterion_id="routing", name="Маршрутизация", status=CriterionStatus.NOT_APPLICABLE, score=0.5, comment="Маршрутизация не проводилась."),
            CriterionEvaluation(criterion_id="communication", name="Стандарты коммуникации", status=CriterionStatus.VIOLATED, score=0.0, evidences=[evidence], comment="Грубость, эмоциональный срыв оператора."),
            CriterionEvaluation(criterion_id="result", name="Результат консультации", status=CriterionStatus.VIOLATED, score=0.0, comment="Звонок сброшен оператором."),
        ]

        return Call(
            metadata=meta,
            utterances=utterances,
            full_transcript=" ".join(u.text for u in utterances),
            topic=CallTopic.COMPETITION_ENROLLMENT,
            applicant_category=ApplicantCategory.PARENT,
            inquiry_type=InquiryType.COMPLAINT,
            target_department="МФЦ РУДН",
            outcome=CallOutcome.UNRESOLVED,
            overall_quality_score=15.0,
            has_critical_error=True,
            critical_error_summary="Грубое нарушение этики общения: раздражительность, отказ в консультации и сброс трубки.",
            criteria_evaluations=criteria,
            manager_status=ManagerStatus.PENDING,
        )

    def _create_scenario_6_perfect_dormitory_consultation(self) -> Call:
        """Сценарий 6: идеальная консультация по общежитиям."""
        timestamp = datetime(2026, 7, 10, 10, 15, 30)
        utterances = [
            Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2800, text="Доброе утро! Контакт-центр МФЦ РУДН, оператор Дарья. Чем могу вам помочь?"),
            Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=3100, end_ms=9000, text="Здравствуйте! Я подал документы на бюджет, мы из Самары. Хотел узнать, как получить общежитие и когда начнётся заселение?"),
            Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=9500, end_ms=21000, text="С удовольствием подскажу! Заявление на общежитие подается через ваш личный кабинет абитуриента, но строго после того, как выйдет приказ о вашем зачислении. Заселение первого курса начнётся с 25 августа."),
            Utterance(id=4, speaker=SpeakerRole.APPLICANT, start_ms=21500, end_ms=25000, text="Понял. А какие медицинские справки понадобятся для заселения?"),
            Utterance(id=5, speaker=SpeakerRole.OPERATOR, start_ms=25500, end_ms=37500, text="Обязательно подготовьте справку формы 086/у, действующую флюорографию не старше 11 месяцев, прививочный сертификат и полис ОМС. Без флюорографии ордер на заселение не выдается."),
            Utterance(id=6, speaker=SpeakerRole.APPLICANT, start_ms=38000, end_ms=40500, text="Отлично, всё очень понятно! Спасибо большое, Дарья!"),
            Utterance(id=7, speaker=SpeakerRole.OPERATOR, start_ms=41000, end_ms=44500, text="Была рада помочь! Ждём вас в РУДН. Удачи и прекрасного дня! До свидания."),
        ]

        meta = CallMetadata(
            call_id="CALL-2026-0710-006",
            ucid="UCID-882319006",
            timestamp=timestamp,
            duration_seconds=45,
            queue_name="VDN_MFC_RUDN",
            load_regime=LoadRegime.LOW,
            operator_pseudonym="Оператор №07 (Дарья)",
            applicant_pseudonym=_pseudonymize("applicant_gleb_samara"),
            is_repeat_call=False,
        )

        criteria = [
            CriterionEvaluation(criterion_id="understanding", name="Понимание вопроса", status=CriterionStatus.COMPLIANT, score=1.0, comment="Точно определена потребность и статус иногороднего."),
            CriterionEvaluation(criterion_id="accuracy", name="Точность информации", status=CriterionStatus.COMPLIANT, score=1.0, comment="Все даты и регламенты соответствуют положению об общежитиях."),
            CriterionEvaluation(criterion_id="completeness", name="Полнота ответа", status=CriterionStatus.COMPLIANT, score=1.0, comment="Озвучены условия, дата старта (25.08) и список меддокументов."),
            CriterionEvaluation(criterion_id="routing", name="Маршрутизация", status=CriterionStatus.COMPLIANT, score=1.0, comment="Информация дана в полном объеме без избыточных переводов."),
            CriterionEvaluation(criterion_id="communication", name="Стандарты коммуникации", status=CriterionStatus.COMPLIANT, score=1.0, comment="Приветливый тон, структурированная речь, эталонный диалог."),
            CriterionEvaluation(criterion_id="result", name="Результат консультации", status=CriterionStatus.COMPLIANT, score=1.0, comment="Вопрос полностью закрыт."),
        ]

        return Call(
            metadata=meta,
            utterances=utterances,
            full_transcript=" ".join(u.text for u in utterances),
            topic=CallTopic.DORMITORY,
            applicant_category=ApplicantCategory.APPLICANT_RF,
            inquiry_type=InquiryType.CONSULTATION,
            target_department="Управление размещения в общежитиях РУДН",
            outcome=CallOutcome.RESOLVED_IN_CALL,
            overall_quality_score=100.0,
            has_critical_error=False,
            criteria_evaluations=criteria,
            manager_status=ManagerStatus.RESOLVED,
            manager_notes="Отличная консультация. Рекомендовано использовать в качестве обучающего примера.",
        )

    def _generate_additional_realistic_calls(self, count: int = 26) -> List[Call]:
        """Генерирует дополнительные реалистичные звонки по разным темам и датам."""
        calls: List[Call] = []

        templates = [
            (
                CallTopic.PROGRAM_CHOICE,
                ApplicantCategory.APPLICANT_RF,
                InquiryType.CONSULTATION,
                "Проходные баллы на юриспруденцию",
                [
                    (SpeakerRole.OPERATOR, "Здравствуйте! МФЦ РУДН, оператор Игорь. Чем могу помочь?"),
                    (SpeakerRole.APPLICANT, "Добрый день! Подскажите, какой проходной балл был на бюджет юриспруденции в прошлом году?"),
                    (SpeakerRole.OPERATOR, "В прошлом году минимальный балл зачисленного на бюджет составил 286 баллов с учётом индивидуальных достижений. На платное обучение порог от 180 баллов."),
                    (SpeakerRole.APPLICANT, "Спасибо большое!"),
                    (SpeakerRole.OPERATOR, "Пожалуйста, ждём вас среди поступающих! Всего доброго."),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                96.0,
                False,
                None,
            ),
            (
                CallTopic.ENTRANCE_EXAMS,
                ApplicantCategory.APPLICANT_RF,
                InquiryType.PROCEDURE,
                "Формат сдачи ДВИ по творческому конкурсу (Журналистика)",
                [
                    (SpeakerRole.OPERATOR, "МФЦ РУДН, оператор Екатерина. Добрый день!"),
                    (SpeakerRole.APPLICANT, "Здравствуйте! Я подал документы на журналистику. Как будут проходить вступительные испытания — онлайн или очно в корпусе?"),
                    (SpeakerRole.OPERATOR, "Творческое испытание проходит в дистанционном формате с системой прокторинга. Ссылка на подключение придёт в ваш личный кабинет за 2 дня до экзамена. Расписание доступно на сайте priem.rudn.ru в разделе 'Вступительные испытания'."),
                    (SpeakerRole.APPLICANT, "А если камера отключится во время экзамена?"),
                    (SpeakerRole.OPERATOR, "В случае технического сбоя составляется акт прокторинга, и вам предоставят резервный день. Приказ и инструкция по прокторингу есть в личном кабинете."),
                    (SpeakerRole.APPLICANT, "Понятно, спасибо!"),
                    (SpeakerRole.OPERATOR, "Успехов на экзамене! До свидания."),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                100.0,
                False,
                None,
            ),
            (
                CallTopic.SPECIAL_RIGHTS_QUOTAS,
                ApplicantCategory.PARENT,
                InquiryType.CONSULTATION,
                "Квота для участников СВО и их детей",
                [
                    (SpeakerRole.OPERATOR, "МФЦ РУДН, здравствуйте! Чем могу помочь?"),
                    (SpeakerRole.APPLICANT, "Добрый день. Мой сын поступает по отдельной квоте. Какие справки нужны для подтверждения?"),
                    (SpeakerRole.OPERATOR, "Необходима официальная справка из военкомата или воинской части установленного образца. Вы можете прикрепить её скан на Госуслугах при подаче заявления или принести оригинал в ПК РФ."),
                    (SpeakerRole.APPLICANT, "А он сдает экзамены или по ЕГЭ?"),
                    (SpeakerRole.OPERATOR, "По отдельной квоте абитуриенты имеют право как использовать результаты ЕГЭ, так и сдать внутренние общеобразовательные вступительные испытания в РУДН."),
                    (SpeakerRole.APPLICANT, "Спасибо, теперь ясно."),
                    (SpeakerRole.OPERATOR, "Всего хорошего, до свидания!"),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                98.0,
                False,
                None,
            ),
            (
                CallTopic.MFC_SERVICES,
                ApplicantCategory.STUDENT,
                InquiryType.PROCEDURE,
                "Справка об обучении для военкомата (Приложение №4)",
                [
                    (SpeakerRole.OPERATOR, "МФЦ РУДН, оператор Максим. Слушаю вас."),
                    (SpeakerRole.APPLICANT, "Приветствую! Я студент 2 курса филфака. Мне нужна справка с гербовой печатью для военкомата. Как её заказать?"),
                    (SpeakerRole.OPERATOR, "Добрый день! Справку для военкомата (Приложение №4) вы можете заказать онлайн через Единый личный кабинет студента в разделе 'Услуги МФЦ'. Срок изготовления — 3 рабочих дня. Смс-уведомление придёт, когда она будет готова к выдаче в холле главного корпуса."),
                    (SpeakerRole.APPLICANT, "Понял, сделаю через ЛК. Спасибо!"),
                    (SpeakerRole.OPERATOR, "Всего доброго!"),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                95.0,
                False,
                None,
            ),
            (
                CallTopic.CONTRACT_AND_PAYMENT,
                ApplicantCategory.APPLICANT_RF,
                InquiryType.PROCEDURE,
                "Оплата материнским капиталом",
                [
                    (SpeakerRole.OPERATOR, "МФЦ РУДН, оператор Ксения. Здравствуйте!"),
                    (SpeakerRole.APPLICANT, "Здравствуйте! Мы хотим оплатить обучение материнским капиталом. Как оформить дополнительное соглашение?"),
                    (SpeakerRole.OPERATOR, "Для оплаты маткапиталом вам необходимо обратиться в юридический отдел приёмной комиссии с сертификатом и СНИЛС владельца сертификата. РУДН оформляет трехсторонний договор, который затем передается в Социальный фонд. Сейчас переведу вас на специалиста договорного отдела для записи."),
                    (SpeakerRole.APPLICANT, "Хорошо, соедините, пожалуйста."),
                    (SpeakerRole.OPERATOR, "Перевожу вызов. Ожидайте ответа."),
                ],
                CallOutcome.TRANSFERRED,
                88.0,
                False,
                None,
            ),
            (
                CallTopic.APPLICATION_AND_STATUS,
                ApplicantCategory.APPLICANT_RF,
                InquiryType.TECHNICAL_ISSUE,
                "Зависла кнопка отправки согласия в личном кабинете",
                [
                    (SpeakerRole.OPERATOR, "Контакт-центр МФЦ, оператор Артём. Слушаю вас!"),
                    (SpeakerRole.APPLICANT, "Здравствуйте! У меня в личном кабинете кнопка 'Подать согласие' серая и не нажимается! Что делать?"),
                    (SpeakerRole.OPERATOR, "Проверьте, прикреплена ли скан-копия документа об образовании и заполнено ли поле с паспортными данными законного представителя, если вам меньше 18 лет."),
                    (SpeakerRole.APPLICANT, "Ой, точно, паспорт мамы не был прикреплен! Спасибо огромное!"),
                    (SpeakerRole.OPERATOR, "Пожалуйста! Нажмите 'Сохранить', и кнопка станет активной. Удачи!"),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                100.0,
                False,
                None,
            ),
        ]

        base_start = datetime(2026, 6, 25, 10, 0)

        for i in range(count):
            tpl = templates[i % len(templates)]
            topic, category, inq_type, title, dialog, outcome, score, is_crit, crit_sum = tpl
            
            call_id = f"CALL-2026-{self.rng.randint(6, 8):02d}{self.rng.randint(1, 28):02d}-{100 + i:03d}"
            ucid = f"UCID-{self.rng.randint(880000000, 889999999)}"
            day_offset = self.rng.randint(0, 55)
            hour = self.rng.choice([10, 11, 12, 14, 15, 16, 17])
            minute = self.rng.randint(0, 59)
            call_time = base_start + timedelta(days=day_offset, hours=hour, minutes=minute)
            
            # Разброс оценок для естественности
            adjusted_score = round(max(30.0, min(100.0, score + self.rng.uniform(-10.0, 4.0))), 1)

            utterances: List[Utterance] = []
            curr_ms = 0
            for uid, (spk, text) in enumerate(dialog, start=1):
                duration_ms = len(text) * 70 + self.rng.randint(400, 1200)
                utterances.append(Utterance(
                    id=uid,
                    speaker=spk,
                    start_ms=curr_ms,
                    end_ms=curr_ms + duration_ms,
                    text=text,
                ))
                curr_ms += duration_ms + self.rng.randint(300, 800)

            duration_sec = int(curr_ms / 1000)
            regime = LoadRegime.HIGH if hour in (11, 12, 16) else LoadRegime.TYPICAL

            meta = CallMetadata(
                call_id=call_id,
                ucid=ucid,
                timestamp=call_time,
                duration_seconds=duration_sec,
                queue_name="VDN_MFC_RUDN",
                load_regime=regime,
                operator_pseudonym=f"Оператор №{self.rng.randint(1, 25):02d}",
                applicant_pseudonym=_pseudonymize(f"caller_{call_id}"),
                is_repeat_call=(i % 7 == 0),
            )

            criteria = [
                CriterionEvaluation(criterion_id="understanding", name="Понимание вопроса", status=CriterionStatus.COMPLIANT, score=1.0),
                CriterionEvaluation(criterion_id="accuracy", name="Точность информации", status=CriterionStatus.COMPLIANT if adjusted_score > 60 else CriterionStatus.VIOLATED, score=adjusted_score / 100.0),
                CriterionEvaluation(criterion_id="completeness", name="Полнота ответа", status=CriterionStatus.COMPLIANT if adjusted_score > 70 else CriterionStatus.VIOLATED, score=adjusted_score / 100.0),
                CriterionEvaluation(criterion_id="routing", name="Маршрутизация", status=CriterionStatus.COMPLIANT, score=1.0),
                CriterionEvaluation(criterion_id="communication", name="Стандарты коммуникации", status=CriterionStatus.COMPLIANT, score=0.95),
                CriterionEvaluation(criterion_id="result", name="Результат консультации", status=CriterionStatus.COMPLIANT if outcome != CallOutcome.UNRESOLVED else CriterionStatus.VIOLATED, score=1.0),
            ]

            calls.append(Call(
                metadata=meta,
                utterances=utterances,
                full_transcript=" ".join(u.text for u in utterances),
                topic=topic,
                applicant_category=category,
                inquiry_type=inq_type,
                target_department="Приёмная комиссия РУДН" if topic != CallTopic.MFC_SERVICES else "МФЦ РУДН",
                outcome=outcome,
                overall_quality_score=adjusted_score,
                has_critical_error=is_crit,
                critical_error_summary=crit_sum,
                criteria_evaluations=criteria,
                manager_status=ManagerStatus.PENDING if adjusted_score < 80 else ManagerStatus.RESOLVED,
            ))

        return calls
