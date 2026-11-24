"""Модели интервальных отчетов Avaya CMS."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from mfc_analytics.models.call import LoadRegime


class CMSInterval(BaseModel):
    """Интервальная запись отчета Avaya CMS (стандартные 30-минутные слоты)."""
    interval_start: datetime
    interval_minutes: int = 30
    queue_vdn: str = Field(default="VDN_MFC_RUDN", description="Входная точка / VDN")
    
    offered_calls: int = Field(..., ge=0, description="Предложенные входящие вызовы")
    answered_calls: int = Field(..., ge=0, description="Отвеченные вызовы")
    abandoned_calls: int = Field(default=0, ge=0, description="Отказы (сбросы) в очереди")
    
    avg_speed_of_answer_sec: float = Field(default=0.0, description="Среднее время ожидания ответа (ASA)")
    avg_handle_time_sec: float = Field(default=0.0, description="Среднее время обработки звонка (AHT)")
    active_agent_positions: int = Field(default=5, ge=0, description="Число операторских позиций на линии")
    
    service_level_percent: float = Field(default=85.0, description="Процент звонков, отвеченных в норматив (SL)")
    load_regime: LoadRegime = Field(default=LoadRegime.TYPICAL)


class CMSReportSummary(BaseModel):
    """Агрегированная сводка по нагрузке контакт-центра за выбранный период."""
    period_start: datetime
    period_end: datetime
    total_offered: int
    total_answered: int
    total_abandoned: int
    answer_rate_percent: float
    abandonment_rate_percent: float
    avg_speed_of_answer_sec: float
    avg_handle_time_sec: float
    intervals_count: int
    high_load_intervals_count: int
    peak_offered_in_interval: int
