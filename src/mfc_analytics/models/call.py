"""Модели описания звонков, транскрипций и результатов контроля качества."""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ApplicantCategory(str, Enum):
    """Категория заявителя по материалам кейса РУДН."""
    APPLICANT_RF = "Абитуриент РФ"
    APPLICANT_INT = "Иностранный абитуриент"
    PARENT = "Родитель / законный представитель"
    STUDENT = "Обучающийся (студент/аспирант)"
    STAFF = "Сотрудник университета"
    OTHER = "Другое лицо"
    UNKNOWN = "Не установлено"


class CallTopic(str, Enum):
    """Словарь тем обращений на основе материалов РУДН."""
    PROGRAM_CHOICE = "Выбор программы и проходные баллы"
    APPLICATION_AND_STATUS = "Подача документов и статус заявления"
    SPECIAL_RIGHTS_QUOTAS = "Право на участие (квоты, льготы, БВИ)"
    ENTRANCE_EXAMS = "Вступительные испытания (ДВИ, экзамены)"
    COMPETITION_ENROLLMENT = "Конкурсные списки, согласие и зачисление"
    CONTRACT_AND_PAYMENT = "Договор и оплата обучения"
    DORMITORY = "Общежитие и первые шаги"
    INTERNATIONAL_QUESTIONS = "Международные вопросы (визы, признание документов)"
    MFC_SERVICES = "Другие услуги МФЦ (справки, пропуск, контакты)"
    OTHER = "Другое"


class InquiryType(str, Enum):
    """Характер запроса."""
    CONSULTATION = "Консультация / совет"
    PROCEDURE = "Административная процедура"
    STATUS_CHECK = "Проверка статуса"
    TECHNICAL_ISSUE = "Технический сбой"
    COMPLAINT = "Жалоба / претензия"
    CONTACTS = "Контакты и навигация"
    OTHER = "Другое"


class CallOutcome(str, Enum):
    """Итог консультации."""
    RESOLVED_IN_CALL = "Вопрос решен в пределах звонка"
    NEXT_STEP_PROVIDED = "Указан следующий шаг заявителю"
    TRANSFERRED = "Переведен в профильное подразделение"
    CALLBACK_PROMISED = "Обещано уточнение / обратный звонок"
    UNRESOLVED = "Вопрос остался без решения"
    UNKNOWN = "Не установлено"


class LoadRegime(str, Enum):
    """Режим нагрузки контакт-центра в момент звонка."""
    HIGH = "Высокая нагрузка (пик)"
    TYPICAL = "Типичная нагрузка"
    LOW = "Тихий интервал"


class ManagerStatus(str, Enum):
    """Статус проверки карточки руководителем."""
    PENDING = "Требует проверки"
    CONFIRMED = "Нарушение подтверждено"
    REJECTED = "Ложный сигнал (отклонено)"
    ACTION_ASSIGNED = "Назначено действие"
    RESOLVED = "Проверено, без замечаний"


class CriterionStatus(str, Enum):
    """Статус соблюдения критерия контроля качества."""
    COMPLIANT = "Выполнен"
    VIOLATED = "Нарушен"
    INSUFFICIENT_DATA = "Недостаточно данных"
    NOT_APPLICABLE = "Не применимо"


class SpeakerRole(str, Enum):
    """Роль говорящего в диалоге."""
    OPERATOR = "Оператор"
    APPLICANT = "Заявитель"
    UNKNOWN = "Неизвестно"


class Utterance(BaseModel):
    """Фрагмент речи / реплика с таймкодами."""
    id: int
    speaker: SpeakerRole
    start_ms: int = Field(..., description="Время начала реплики в миллисекундах")
    end_ms: int = Field(..., description="Время окончания реплики в миллисекундах")
    text: str = Field(..., description="Распознанный текст реплики")
    channel: Optional[int] = Field(default=None, description="Номер канала (0 - оператор, 1 - клиент при стерео)")
    is_key_evidence: bool = Field(default=False, description="Является ли реплика доказательством проблемы/ошибки")


class Evidence(BaseModel):
    """Доказательство оценки качества: цитата, таймкод, примененное правило."""
    criterion_id: str
    quote: str = Field(..., description="Обезличенная цитата из разговора")
    start_ms: int
    end_ms: int
    rule_id: Optional[str] = None
    rule_version: Optional[str] = None
    explanation: str = Field(..., description="Почему это считается нарушением или корректным действием")
    severity: str = Field(default="MEDIUM", description="CRITICAL, HIGH, MEDIUM, LOW")


class CriterionEvaluation(BaseModel):
    """Результат проверки по одному из 6 критериев контроля качества."""
    criterion_id: str = Field(..., description="understanding, accuracy, completeness, routing, communication, result")
    name: str = Field(..., description="Название критерия на русском языке")
    status: CriterionStatus
    score: float = Field(default=1.0, ge=0.0, le=1.0, description="Оценка от 0.0 до 1.0")
    evidences: List[Evidence] = Field(default_factory=list)
    comment: str = ""


class CallMetadata(BaseModel):
    """Метаданные входящего звонка из Avaya CMS / телефонии."""
    call_id: str
    ucid: Optional[str] = Field(default=None, description="Universal Call ID из Avaya")
    timestamp: datetime = Field(..., description="Дата и время начала звонка (МСК)")
    duration_seconds: int = Field(..., description="Длительность разговора в секундах")
    queue_name: str = Field(default="MFC_MAIN_QUEUE", description="Входная очередь / VDN")
    load_regime: LoadRegime = Field(default=LoadRegime.TYPICAL)
    operator_pseudonym: str = Field(default="Оператор №12", description="Обезличенный ID оператора")
    applicant_pseudonym: str = Field(default="Заявитель_4812", description="Обезличенный идентификатор заявителя")
    is_repeat_call: bool = Field(default=False, description="Повторный звонок в течение 7 дней")
    previous_call_id: Optional[str] = None


class Call(BaseModel):
    """Полная сущность звонка с метаданными, транскриптом и оценкой качества."""
    metadata: CallMetadata
    utterances: List[Utterance] = Field(default_factory=list)
    full_transcript: str = ""
    
    # Результаты анализа
    topic: CallTopic = Field(default=CallTopic.OTHER)
    additional_topics: List[CallTopic] = Field(default_factory=list)
    applicant_category: ApplicantCategory = Field(default=ApplicantCategory.UNKNOWN)
    inquiry_type: InquiryType = Field(default=InquiryType.CONSULTATION)
    target_department: str = Field(default="МФЦ РУДН")
    actual_transfer_department: Optional[str] = None
    outcome: CallOutcome = Field(default=CallOutcome.UNKNOWN)
    
    # Контроль качества
    overall_quality_score: float = Field(default=100.0, ge=0.0, le=100.0)
    has_critical_error: bool = False
    critical_error_summary: Optional[str] = None
    criteria_evaluations: List[CriterionEvaluation] = Field(default_factory=list)
    
    # Статус работы руководителя
    manager_status: ManagerStatus = Field(default=ManagerStatus.PENDING)
    manager_notes: Optional[str] = None
