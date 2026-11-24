"""Модели управленческих действий руководителя контакт-центра."""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ActionProblemType(str, Enum):
    """Тип выявленной проблемы."""
    FAQ_GAP = "Пробел в FAQ / базе знаний"
    OPERATOR_ERROR = "Систематическая ошибка операторов"
    ROUTING_BOTTLENECK = "Узкое горлышко маршрутизации"
    COMMUNICATION_STANDARD = "Нарушение стандартов коммуникации"
    TECHNICAL_SYSTEM_FAILURE = "Сбой в ИТ-системах университета"


class ActionStatus(str, Enum):
    """Статус управленческого действия."""
    OPEN = "Открыто"
    IN_PROGRESS = "В работе"
    VERIFICATION = "На проверке"
    RESOLVED = "Выполнено"
    CANCELLED = "Отклонено"


class ManagerAction(BaseModel):
    """Управленческое решение/действие, созданное на основе аналитики."""
    action_id: str
    title: str = Field(..., description="Краткая суть меры")
    problem_type: ActionProblemType
    description: str = Field(..., description="Подробное описание проблемы и необходимого решения")
    owner: str = Field(..., description="Ответственное подразделение (МФЦ, Приёмная комиссия, ИТ-департамент)")
    related_call_ids: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    target_date: Optional[datetime] = None
    status: ActionStatus = Field(default=ActionStatus.OPEN)
    expected_impact_metric: str = Field(..., description="Метрика оценки эффекта (например: 'Снижение повторных звонков по согласию на 50%')")
    actual_result_notes: Optional[str] = None
