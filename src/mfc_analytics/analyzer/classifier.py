"""Модуль классификации обращений: тематика, категория заявителя, характер запроса и маршрут."""

import re
from typing import List, Tuple
from mfc_analytics.models.call import (
    ApplicantCategory,
    CallOutcome,
    CallTopic,
    InquiryType,
    Utterance,
)


class CallClassifier:
    """Классификатор обращений на основе правил и лексического анализа предметной области РУДН."""

    TOPIC_KEYWORDS = {
        CallTopic.COMPETITION_ENROLLMENT: [
            "согласие", "согласия", "зачисление", "зачислении", "приказ", "приказы",
            "конкурсный список", "конкурсные списки", "оригинал аттестата", "рейтинг",
            "прохожу ли я", "зеленая волна", "выписка из приказа"
        ],
        CallTopic.CONTRACT_AND_PAYMENT: [
            "договор", "оплата", "оплатить", "стоимость", "бухгалтерия", "платное",
            "контракт", "скидка", "рассрочка", "материнский капитал", "маткапитал", "квитанция"
        ],
        CallTopic.APPLICATION_AND_STATUS: [
            "подать документы", "подача документов", "госуслуги", "епгу", "личном кабинете",
            "статус заявления", "заявление принято", "не отображается", "снилс", "суперсервис"
        ],
        CallTopic.ENTRANCE_EXAMS: [
            "дви", "вступительные", "экзамен", "экзамены", "расписание экзаменов",
            "прокторинг", "творческий конкурс", "апелляция", "консультация к экзамену"
        ],
        CallTopic.SPECIAL_RIGHTS_QUOTAS: [
            "квота", "квоте", "бви", "олимпиада", "олимпиады", "льгота", "льготы",
            "отдельная квота", "особая квота", "целевое", "целевой договор", "инвалид"
        ],
        CallTopic.DORMITORY: [
            "общежитие", "общежития", "заселение", "койко-место", "комната",
            "кампус", "ордер", "086/у", "флюорография", "проживание"
        ],
        CallTopic.INTERNATIONAL_QUESTIONS: [
            "иностранец", "иностранный", "гражданин узбекистана", "гражданин казахстана",
            "гражданство", "виза", "визовый", "нострификация", "признание диплома",
            "перевод паспорта", "intstudent"
        ],
        CallTopic.PROGRAM_CHOICE: [
            "проходной балл", "проходные баллы", "направления подготовки", "специальность",
            "бюджетные места", "какие предметы сдавать", "минимальный балл"
        ],
        CallTopic.MFC_SERVICES: [
            "справка", "справку", "пропуск", "студенческий", "военкомат", "приложение 4",
            "выпускник", "архив", "печать"
        ],
    }

    def classify_topic(self, text: str) -> Tuple[CallTopic, List[CallTopic]]:
        """Определяет основную и дополнительные темы обращения по тексту."""
        lowered = text.lower()
        topic_scores = {}

        for topic, keywords in self.TOPIC_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in lowered)
            if score > 0:
                topic_scores[topic] = score

        if not topic_scores:
            return CallTopic.OTHER, []

        sorted_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)
        primary_topic = sorted_topics[0][0]
        additional = [t for t, _ in sorted_topics[1:3]]
        return primary_topic, additional

    def classify_applicant_category(self, text: str) -> ApplicantCategory:
        """Определяет категорию заявителя (абитуриент РФ, иностранец, родитель, студент)."""
        lowered = text.lower()

        # Родители
        if any(w in lowered for w in ["мой сын", "моя дочь", "я мама", "я отец", "для дочери", "для сына", "родители"]):
            return ApplicantCategory.PARENT

        # Иностранные граждане
        if any(w in lowered for w in [
            "иностранный гражданин", "гражданин узбекистана", "гражданин таджикистана",
            "гражданин казахстана", "гражданин беларуси", "иностранный паспорт",
            "виза", "из другой страны", "intstudent"
        ]):
            return ApplicantCategory.APPLICANT_INT

        # Обучающиеся РУДН
        if any(w in lowered for w in ["я студент", "студентка", "учусь на", "курс филфака", "номер группы", "зачетка", "моя сессия"]):
            return ApplicantCategory.STUDENT

        # Сотрудники
        if any(w in lowered for w in ["я сотрудник", "преподаватель кафедры", "деканат звонит", "табельный номер"]):
            return ApplicantCategory.STAFF

        # Абитуриенты РФ
        if any(w in lowered for w in ["поступаю", "подал документы", "сдал егэ", "хочу поступить", "абитуриент", "мой аттестат"]):
            return ApplicantCategory.APPLICANT_RF

        return ApplicantCategory.APPLICANT_RF

    def classify_inquiry_type(self, text: str) -> InquiryType:
        """Определяет характер запроса."""
        lowered = text.lower()
        if any(w in lowered for w in ["жалоба", "возмутительно", "претензия", "безобразие", "почему так долго"]):
            return InquiryType.COMPLAINT
        if any(w in lowered for w in ["ошибка", "зависло", "не работает", "не нажимается", "технический сбой", "исчезло"]):
            return InquiryType.TECHNICAL_ISSUE
        if any(w in lowered for w in ["статус", "проверить заявление", "где посмотреть", "появился ли я в списке"]):
            return InquiryType.STATUS_CHECK
        if any(w in lowered for w in ["как оформить", "как подать", "какие документы нужны", "процедура", "алгоритм"]):
            return InquiryType.PROCEDURE
        if any(w in lowered for w in ["телефон", "адрес", "где находится", "как связаться", "номер кабинета"]):
            return InquiryType.CONTACTS
        return InquiryType.CONSULTATION

    def classify_outcome(self, utterances: List[Utterance]) -> CallOutcome:
        """Определяет итог консультации по ходу и финалу разговора."""
        if not utterances:
            return CallOutcome.UNKNOWN

        full_text = " ".join(u.text.lower() for u in utterances)
        last_operator_utterances = [u for u in utterances if u.speaker.value == "Оператор"]
        last_text = last_operator_utterances[-1].text.lower() if last_operator_utterances else ""

        # Признаки перевода
        if any(w in full_text for w in ["перевожу", "соединяю", "оставайтесь на линии", "переключаю на специалиста"]):
            return CallOutcome.TRANSFERRED

        # Сброс или грубый обрыв
        if any(w in last_text for w in ["читайте на сайте", "у меня очередь", "некогда", "бросила трубку"]):
            return CallOutcome.UNRESOLVED

        # Обещание обратного звонка
        if any(w in last_text for w in ["мы вам перезвоним", "уточню и свяжусь", "оставьте контактный номер"]):
            return CallOutcome.CALLBACK_PROMISED

        # Четкий следующий шаг
        if any(w in full_text for w in ["зайдите в личный кабинет", "прикрепите скан", "обратитесь с 25 августа", "нажмите сохранить"]):
            return CallOutcome.NEXT_STEP_PROVIDED

        # Решено в звонке
        if any(w in full_text for w in ["спасибо большое", "теперь понятно", "очень помогли", "рада помочь"]):
            return CallOutcome.RESOLVED_IN_CALL

        return CallOutcome.RESOLVED_IN_CALL
