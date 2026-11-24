"""Модуль связки и сопоставления звонков с интервалами Avaya CMS."""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from mfc_analytics.models.call import Call
from mfc_analytics.models.cms import CMSInterval


class CallCMSMatcher:
    """Сопоставляет аудиозаписи звонков с телеметрией и отчетами Avaya CMS."""

    def __init__(self, intervals: List[CMSInterval]):
        self.intervals = intervals

    def match_call(self, call: Call) -> Optional[CMSInterval]:
        """Находит соответствующий 30-минутный интервал CMS для звонка."""
        call_time = call.metadata.timestamp

        for interval in self.intervals:
            interval_end = interval.interval_start + timedelta(minutes=interval.interval_minutes)
            if interval.interval_start <= call_time < interval_end:
                return interval

        return None

    def calculate_match_stats(self, calls: List[Call]) -> Dict[str, float]:
        """Вычисляет статистику связки аудиозаписей с интервалами CMS."""
        if not calls:
            return {"total_calls": 0, "matched_calls": 0, "match_rate_percent": 0.0}

        matched = 0
        for call in calls:
            if self.match_call(call) is not None:
                matched += 1

        rate = round(matched / len(calls) * 100.0, 1)
        return {
            "total_calls": len(calls),
            "matched_calls": matched,
            "match_rate_percent": rate,
        }
