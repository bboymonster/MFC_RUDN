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
from mfc_analytics.models.cms import CMSInterval
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
            
            if is_sunday:
                current_date += timedelta(days=1)
                continue

            is_peak_day = (current_date.month, current_date.day) in peak_dates
            end_hour = 15 if is_saturday else 19
            day_cursor = current_date.replace(hour=9, minute=0, second=0)

            while day_cursor.hour < end_hour:
                hour = day_cursor.hour
                is_peak_hour = hour in (10, 11, 12, 16)
                
                if is_peak_day and is_peak_hour:
                    offered = self.rng.randint(70, 130)
                    answered = int(offered * self.rng.uniform(0.70, 0.85))
                    positions = self.rng.randint(6, 8)
                    asa = round(self.rng.uniform(90.0, 240.0), 1)
                    regime = LoadRegime.HIGH
                elif is_peak_day or is_peak_hour:
                    offered = self.rng.randint(35, 68)
                    answered = int(offered * self.rng.uniform(0.85, 0.94))
                    positions = self.rng.randint(5, 7)
                    asa = round(self.rng.uniform(30.0, 85.0), 1)
                    regime = LoadRegime.TYPICAL
                else:
                    offered = self.rng.randint(8, 32)
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
        """Генерирует калиброванный эталонный корпус звонков, включая ключевые сценарии."""
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

        # Дополнительные разнообразные звонки
        additional = self._generate_additional_realistic_calls(count=28)
        calls.extend(additional)

        return calls

    def _create_scenario_1_critical_consent_error(self) -> Call:
        """Сценарий 1: оператор назвал ошибочный дедлайн согласия."""
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
            manager_status=ManagerStatus.RESOLVED,
            manager_notes="Отличная консультация. Рекомендовано использовать в качестве обучающего примера.",
        )

    def _generate_additional_realistic_calls(self, count: int = 28) -> List[Call]:
        """Генерирует корпус реалистичных диалогов по разным темам, категориям и датам."""
        calls: List[Call] = []

        dialogue_scenarios = [
            # 1. ДВИ и прокторинг
            (
                CallTopic.ENTRANCE_EXAMS,
                ApplicantCategory.APPLICANT_RF,
                InquiryType.PROCEDURE,
                [
                    (SpeakerRole.OPERATOR, "МФЦ РУДН, оператор Екатерина. Добрый день!"),
                    (SpeakerRole.APPLICANT, "Здравствуйте! Я подал документы на журналистику. Как будут проходить вступительные испытания — онлайн или очно в корпусе?"),
                    (SpeakerRole.OPERATOR, "Творческое испытание проходит в дистанционном формате с системой биометрического прокторинга. Ссылка на подключение придёт в ваш личный кабинет за 48 часов до экзамена. Расписание доступно на сайте priem.rudn.ru в разделе 'Вступительные испытания'."),
                    (SpeakerRole.APPLICANT, "А если пропадет интернет во время экзамена?"),
                    (SpeakerRole.OPERATOR, "В случае технического сбоя составляется электронный акт с техподдержкой, и вам предоставят резервный день сдачи. Инструкция есть в личном кабинете."),
                    (SpeakerRole.APPLICANT, "Понятно, спасибо огромное!"),
                    (SpeakerRole.OPERATOR, "Успехов на испытании! До свидания."),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                "Приёмная комиссия РУДН (для граждан РФ)",
            ),
            # 2. Квота СВО и льготы
            (
                CallTopic.SPECIAL_RIGHTS_QUOTAS,
                ApplicantCategory.PARENT,
                InquiryType.CONSULTATION,
                [
                    (SpeakerRole.OPERATOR, "МФЦ РУДН, здравствуйте! Чем могу помочь?"),
                    (SpeakerRole.APPLICANT, "Добрый день. Мой сын поступает по отдельной квоте для участников СВО. Какие документы нужны для подтверждения?"),
                    (SpeakerRole.OPERATOR, "Необходима официальная справка из военкомата или воинской части установленного образца. Скан можно прикрепить на Госуслугах или предоставить оригинал в приёмную комиссию РУДН."),
                    (SpeakerRole.APPLICANT, "А он сдает экзамены или учитываются баллы ЕГЭ?"),
                    (SpeakerRole.OPERATOR, "По отдельной квоте абитуриенты имеют право как использовать баллы ЕГЭ, так и сдать внутренние общеобразовательные экзамены в РУДН."),
                    (SpeakerRole.APPLICANT, "Спасибо большое, всё понятно!"),
                    (SpeakerRole.OPERATOR, "Всего доброго, удачи при поступлении!"),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                "Приёмная комиссия РУДН (для граждан РФ)",
            ),
            # 3. Справка для военкомата в МФЦ
            (
                CallTopic.MFC_SERVICES,
                ApplicantCategory.STUDENT,
                InquiryType.PROCEDURE,
                [
                    (SpeakerRole.OPERATOR, "МФЦ РУДН, оператор Максим. Слушаю вас."),
                    (SpeakerRole.APPLICANT, "Приветствую! Я студент 2 курса филологического факультета. Мне срочно нужна справка для военкомата по форме Приложение 4. Как её заказать?"),
                    (SpeakerRole.OPERATOR, "Добрый день! Справку для военкомата вы заказываете онлайн через Единый личный кабинет студента в разделе 'Услуги МФЦ'. Срок оформления — до 3 рабочих дней. Смс придет, когда она будет готова к выдаче в холле Главного корпуса."),
                    (SpeakerRole.APPLICANT, "Отлично, отправлю заявку в ЛК прямо сейчас."),
                    (SpeakerRole.OPERATOR, "Прекрасно! Хорошего вам дня."),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                "Многофункциональный центр РУДН",
            ),
            # 4. Материнский капитал
            (
                CallTopic.CONTRACT_AND_PAYMENT,
                ApplicantCategory.PARENT,
                InquiryType.PROCEDURE,
                [
                    (SpeakerRole.OPERATOR, "МФЦ РУДН, оператор Ксения. Здравствуйте!"),
                    (SpeakerRole.APPLICANT, "Здравствуйте! Мы хотим оплатить обучение дочери материнским капиталом. Как оформить документы?"),
                    (SpeakerRole.OPERATOR, "Для оплаты маткапиталом оформляется трехстороннее соглашение. Вам понадобятся сертификат, СНИЛС владельца и паспорт. Сейчас я переведу вас на специалиста договорного отдела бухгалтерии для сверки реквизитов."),
                    (SpeakerRole.APPLICANT, "Да, соедините, пожалуйста."),
                    (SpeakerRole.OPERATOR, "Перевожу звонок. Пожалуйста, оставайтесь на линии."),
                ],
                CallOutcome.TRANSFERRED,
                "Управление бухгалтерского учёта и финансового контроля",
            ),
            # 5. Сбой на Госуслугах при подаче согласия
            (
                CallTopic.APPLICATION_AND_STATUS,
                ApplicantCategory.APPLICANT_RF,
                InquiryType.TECHNICAL_ISSUE,
                [
                    (SpeakerRole.OPERATOR, "Контакт-центр МФЦ РУДН, оператор Артём. Слушаю вас!"),
                    (SpeakerRole.APPLICANT, "Здравствуйте! В личном кабинете кнопка 'Подать оригинал и согласие' серая и не нажимается! Что делать?"),
                    (SpeakerRole.OPERATOR, "Проверьте, прикреплена ли скан-копия аттестата и согласие законного представителя, если вам нет 18 лет. После загрузки документов нажмите кнопку 'Сохранить' внизу анкеты."),
                    (SpeakerRole.APPLICANT, "Ой, точно, согласие мамы не сохранилось! Сейчас загрузил, и кнопка стала синей!"),
                    (SpeakerRole.OPERATOR, "Отлично! Главное не забудьте отправить до 5 августа 12:00 МСК. Удачи!"),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                "Приёмная комиссия РУДН (для граждан РФ)",
            ),
            # 6. Целевое обучение и "Работа в России"
            (
                CallTopic.SPECIAL_RIGHTS_QUOTAS,
                ApplicantCategory.APPLICANT_RF,
                InquiryType.CONSULTATION,
                [
                    (SpeakerRole.OPERATOR, "МФЦ РУДН, оператор Полина. Здравствуйте!"),
                    (SpeakerRole.APPLICANT, "Здравствуйте! Я хочу поступить по целевой квоте от больницы. Где регистрировать заявку?"),
                    (SpeakerRole.OPERATOR, "Все заявки на целевое обучение подаются строго через цифровую платформу 'Работа в России' и дублируются на Госуслугах при подаче заявления. Договор заключается в электронном виде с заказчиком."),
                    (SpeakerRole.APPLICANT, "А в сам РУДН нужно привозить договор?"),
                    (SpeakerRole.OPERATOR, "Нет, при электронной подаче данные подтягиваются автоматически из системы 'Работа в России'."),
                    (SpeakerRole.APPLICANT, "Спасибо за подробное разъяснение!"),
                    (SpeakerRole.OPERATOR, "Всего хорошего, ждем вас в РУДН!"),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                "Приёмная комиссия РУДН (для граждан РФ)",
            ),
            # 7. Проходные баллы и конкурсная ситуация
            (
                CallTopic.PROGRAM_CHOICE,
                ApplicantCategory.APPLICANT_RF,
                InquiryType.CONSULTATION,
                [
                    (SpeakerRole.OPERATOR, "Здравствуйте! МФЦ РУДН, оператор Денис. Чем могу помочь?"),
                    (SpeakerRole.APPLICANT, "Добрый день! Подскажите, какой проходной балл на международные отношения на бюджет? У меня 291 балл."),
                    (SpeakerRole.OPERATOR, "В прошлом году проходной балл составил 288 баллов. С 291 баллом ваши шансы очень высоки! Обязательно отслеживайте конкурсный список с 27 июля."),
                    (SpeakerRole.APPLICANT, "Отлично, спасибо большое!"),
                    (SpeakerRole.OPERATOR, "Пожалуйста, ждём ваше согласие. До свидания!"),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                "Приёмная комиссия РУДН (для граждан РФ)",
            ),
            # 8. Международный студент (правильная консультация)
            (
                CallTopic.INTERNATIONAL_QUESTIONS,
                ApplicantCategory.APPLICANT_INT,
                InquiryType.PROCEDURE,
                [
                    (SpeakerRole.OPERATOR, "Контакт-центр МФЦ РУДН, оператор Алиса. Добрый день!"),
                    (SpeakerRole.APPLICANT, "Здравствуйте! Я гражданка Казахстана. Подскажите, через какой портал мне подавать документы на магистратуру?"),
                    (SpeakerRole.OPERATOR, "Добрый день! Иностранные абитуриенты подают документы через наш международный портал intstudent.rudn.ru. Понадобится паспорт, нотариальный перевод на русский язык и диплом бакалавра с легализацией."),
                    (SpeakerRole.APPLICANT, "А на Госуслугах нужно регистрироваться?"),
                    (SpeakerRole.OPERATOR, "Нет, для иностранных граждан подача идёт исключительно через intstudent.rudn.ru. Если возникнут вопросы по визе, я могу переключить вас на международный отдел."),
                    (SpeakerRole.APPLICANT, "Спасибо, теперь всё предельно ясно!"),
                    (SpeakerRole.OPERATOR, "Всего доброго! Ждём вас в РУДН."),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                "Департамент рекрутинга и сопровождения иностранных обучающихся",
            ),
            # 9. Пропуск и кампусная карта сотрудника
            (
                CallTopic.MFC_SERVICES,
                ApplicantCategory.STAFF,
                InquiryType.PROCEDURE,
                [
                    (SpeakerRole.OPERATOR, "МФЦ РУДН, оператор Роман. Слушаю вас."),
                    (SpeakerRole.APPLICANT, "Здравствуйте, я новый преподаватель кафедры иностранных языков. Как мне оформить электронный пропуск в кампус?"),
                    (SpeakerRole.OPERATOR, "Здравствуйте! Вам необходимо подойти в окно №4 МФЦ в Главном корпусе с паспортом и трудовым договором. Фотографирование и выдача кампусной карты занимают 5 минут."),
                    (SpeakerRole.APPLICANT, "Спасибо, сегодня же зайду."),
                    (SpeakerRole.OPERATOR, "Пожалуйста, рады видеть вас в команде РУДН!"),
                ],
                CallOutcome.RESOLVED_IN_CALL,
                "Многофункциональный центр РУДН",
            ),
        ]

        base_start = datetime(2026, 6, 25, 9, 30)

        for i in range(count):
            tpl = dialogue_scenarios[i % len(dialogue_scenarios)]
            topic, category, inq_type, dialog, outcome, target_dept = tpl

            month = self.rng.choice([6, 7, 8])
            day = self.rng.randint(1, 28)
            hour = self.rng.choice([9, 10, 11, 12, 14, 15, 16, 17, 18])
            minute = self.rng.randint(0, 59)
            call_time = datetime(2026, month, day, hour, minute)

            call_id = f"CALL-2026-{month:02d}{day:02d}-{100 + i:03d}"
            ucid = f"UCID-{self.rng.randint(881000000, 889999999)}"

            utterances: List[Utterance] = []
            curr_ms = 0
            for uid, (spk, text) in enumerate(dialog, start=1):
                duration_ms = len(text) * 72 + self.rng.randint(400, 1100)
                utterances.append(Utterance(
                    id=uid,
                    speaker=spk,
                    start_ms=curr_ms,
                    end_ms=curr_ms + duration_ms,
                    text=text,
                ))
                curr_ms += duration_ms + self.rng.randint(300, 700)

            duration_sec = int(curr_ms / 1000)
            is_peak = hour in (10, 11, 12, 16) and day in (20, 25, 4, 5, 21, 24)
            regime = LoadRegime.HIGH if is_peak else (LoadRegime.TYPICAL if hour in (11, 12, 16) else LoadRegime.LOW)

            meta = CallMetadata(
                call_id=call_id,
                ucid=ucid,
                timestamp=call_time,
                duration_seconds=duration_sec,
                queue_name="VDN_MFC_RUDN",
                load_regime=regime,
                operator_pseudonym=f"Оператор №{self.rng.randint(1, 25):02d}",
                applicant_pseudonym=_pseudonymize(f"caller_{call_id}"),
                is_repeat_call=(i % 5 == 0),
            )

            calls.append(Call(
                metadata=meta,
                utterances=utterances,
                full_transcript=" ".join(u.text for u in utterances),
                topic=topic,
                applicant_category=category,
                inquiry_type=inq_type,
                target_department=target_dept,
                outcome=outcome,
                manager_status=ManagerStatus.PENDING if (i % 4 == 0) else ManagerStatus.RESOLVED,
            ))

        return calls
