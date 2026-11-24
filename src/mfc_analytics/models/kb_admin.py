"""Модели администрирования базы знаний и правил контроля качества."""

from datetime import date
from typing import List, Optional
from pydantic import BaseModel, Field


class RuleCreateRequest(BaseModel):
    """Запрос на создание нового эталонного правила."""
    rule_id: str = Field(..., description="Уникальный идентификатор правила (например, RULE_NEW_01)")
    category: str = Field(..., description="Тематика правила")
    title: str = Field(..., description="Краткое название")
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    exact_rule_text: str = Field(..., description="Текст официального регламента РУДН")
    source_document: str = Field(..., description="Источник (приказ, положение, регламент)")
    critical_terms: List[str] = Field(default_factory=list, description="Ключевые сроки и обязательные понятия")
    common_errors: List[str] = Field(default_factory=list, description="Типичные ошибки операторов")
    mandatory_checklist: List[str] = Field(default_factory=list, description="Обязательные пункты ответа")
    target_department: str = Field(default="МФЦ РУДН", description="Профильное подразделение")


class RuleUpdateRequest(BaseModel):
    """Запрос на изменение существующего правила."""
    category: Optional[str] = None
    title: Optional[str] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    exact_rule_text: Optional[str] = None
    source_document: Optional[str] = None
    critical_terms: Optional[List[str]] = None
    common_errors: Optional[List[str]] = None
    mandatory_checklist: Optional[List[str]] = None
    target_department: Optional[str] = None
