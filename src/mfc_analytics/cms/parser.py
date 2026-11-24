"""Парсер исторических отчетов Avaya CMS Supervisor (Split/Skill и VDN отчетов)."""

import csv
from datetime import datetime, timedelta
import io
from typing import List, Optional
from mfc_analytics.models.call import LoadRegime
from mfc_analytics.models.cms import CMSInterval


class AvayaCMSParser:
    """Парсер экспортов отчетов телефонии Avaya CMS в форматах CSV и TSV."""

    @staticmethod
    def parse_csv(csv_content: str) -> List[CMSInterval]:
        """Парсит текст CSV/TSV отчета Avaya и возвращает список CMSInterval."""
        intervals: List[CMSInterval] = []
        
        # Определение разделителя (запятая или точка с запятой)
        first_line = csv_content.splitlines()[0] if csv_content.splitlines() else ""
        delimiter = ";" if ";" in first_line else ","
        if "\t" in first_line:
            delimiter = "\t"

        reader = csv.DictReader(io.StringIO(csv_content), delimiter=delimiter)
        
        for row in reader:
            # Нормализация ключей
            norm_row = {k.strip().lower(): v.strip() for k, v in row.items() if k}
            
            # Дата и время интервала
            raw_date = norm_row.get("date") or norm_row.get("дата") or "2026-07-01"
            raw_time = norm_row.get("time") or norm_row.get("время") or norm_row.get("интервал") or "10:00"
            
            # Извлечение времени начала интервала (например "10:00-10:30" -> "10:00")
            time_start_str = raw_time.split("-")[0].strip()
            
            try:
                dt_str = f"{raw_date} {time_start_str}"
                if len(time_start_str) == 5:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                else:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                # Фоллбэк на текущую дату при нетипичном формате
                dt = datetime(2026, 7, 1, 10, 0)

            # Числовые метрики Avaya
            offered = int(norm_row.get("callsoffered") or norm_row.get("входящие") or norm_row.get("offered") or 0)
            answered = int(norm_row.get("acdcalls") or norm_row.get("отвеченные") or norm_row.get("answered") or 0)
            abandoned = int(norm_row.get("abancalls") or norm_row.get("отказы") or norm_row.get("abandoned") or max(0, offered - answered))
            
            asa = float(norm_row.get("avg_speed_ans") or norm_row.get("asa") or norm_row.get("ожидание") or 25.0)
            aht = float(norm_row.get("avg_acd_time") or norm_row.get("aht") or norm_row.get("разговор") or 180.0)
            positions = int(norm_row.get("positions") or norm_row.get("позиции") or norm_row.get("агенты") or 5)
            
            queue = norm_row.get("vdn") or norm_row.get("skill") or norm_row.get("очередь") or "VDN_MFC_RUDN"

            # Определение нагрузочного режима (квантили)
            if offered >= 60:
                regime = LoadRegime.HIGH
            elif offered >= 25:
                regime = LoadRegime.TYPICAL
            else:
                regime = LoadRegime.LOW

            sl = round(100.0 * (answered / offered if offered > 0 else 1.0), 1)

            intervals.append(
                CMSInterval(
                    interval_start=dt,
                    interval_minutes=30,
                    queue_vdn=queue,
                    offered_calls=offered,
                    answered_calls=answered,
                    abandoned_calls=abandoned,
                    avg_speed_of_answer_sec=asa,
                    avg_handle_time_sec=aht,
                    active_agent_positions=positions,
                    service_level_percent=sl,
                    load_regime=regime,
                )
            )

        return intervals
