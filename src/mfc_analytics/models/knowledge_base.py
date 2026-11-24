"""Модели базы знаний: эталоны, правила приёмной кампании РУДН и подразделения."""

from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class ReferenceRule(BaseModel):
    """Действующее эталонное правило для проверки корректности консультации."""
    rule_id: str
    category: str = Field(..., description="Тематика правила")
    title: str = Field(..., description="Краткое название")
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    exact_rule_text: str = Field(..., description="Официальная формулировка из регламента/приказа РУДН")
    source_document: str = Field(..., description="Источник (приказ, гайд абитуриента, положение)")
    version: str = Field(default="2026.1")
    critical_terms: List[str] = Field(default_factory=list, description="Ключевые слова и сроки (например: '12:00 МСК', 'Госуслуги')")
    common_errors: List[str] = Field(default_factory=list, description="Типичные ошибки операторов")
    mandatory_checklist: List[str] = Field(default_factory=list, description="Обязательные пункты ответа для полноты")
    target_department: str = Field(default="МФЦ РУДН")


class AdmissionStage(BaseModel):
    """Календарный этап приёмной кампании 2026 года."""
    stage_id: str
    name: str
    date_start: datetime
    date_end: datetime
    description: str
    key_deadlines: List[str]


class DepartmentInfo(BaseModel):
    """Справочник профильных подразделений РУДН для маршрутизации."""
    dept_id: str
    name: str
    short_name: str
    scope_of_competence: str
    contact_phone: str
    email: str
    is_mfc_internal: bool = False
