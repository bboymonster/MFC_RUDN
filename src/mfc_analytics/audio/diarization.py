"""Модуль диаризации, разделения каналов телефонии и хронометрического анализа речи."""

from typing import Dict, List, Optional
from mfc_analytics.models.call import SpeakerRole, Utterance


class ChannelDiarizer:
    """Разделение ролей говорящих по каналам стерео-записи телефонии Avaya и речевая хронометрия."""

    def __init__(self, operator_channel: int = 0, applicant_channel: int = 1):
        self.operator_channel = operator_channel
        self.applicant_channel = applicant_channel

    def assign_speaker_by_channel(self, channel: int) -> SpeakerRole:
        """Определяет роль говорящего по номеру аудиоканала стерео-записи."""
        if channel == self.operator_channel:
            return SpeakerRole.OPERATOR
        elif channel == self.applicant_channel:
            return SpeakerRole.APPLICANT
        return SpeakerRole.UNKNOWN

    def separate_stereo_utterances(self, raw_segments: List[dict]) -> List[Utterance]:
        """Преобразует список сегментов с указанием канала в структурированные реплики."""
        utterances: List[Utterance] = []
        for idx, seg in enumerate(raw_segments, start=1):
            channel = seg.get("channel", 0)
            role = self.assign_speaker_by_channel(channel)
            utterances.append(
                Utterance(
                    id=idx,
                    speaker=role,
                    start_ms=seg.get("start_ms", 0),
                    end_ms=seg.get("end_ms", 0),
                    text=seg.get("text", "").strip(),
                    channel=channel,
                )
            )
        utterances.sort(key=lambda u: u.start_ms)
        return utterances

    @staticmethod
    def calculate_talk_listen_metrics(utterances: List[Utterance], total_duration_seconds: int) -> Dict[str, float]:
        """Рассчитывает баланс говорения (Talk-to-Listen Ratio), паузы и темп речи."""
        total_ms = max(1, total_duration_seconds * 1000)
        op_ms = 0
        app_ms = 0
        op_words = 0
        app_words = 0

        for u in utterances:
            dur = max(0, u.end_ms - u.start_ms)
            word_count = len(u.text.split())
            if u.speaker == SpeakerRole.OPERATOR:
                op_ms += dur
                op_words += word_count
            elif u.speaker == SpeakerRole.APPLICANT:
                app_ms += dur
                app_words += word_count

        op_pct = round(op_ms / total_ms * 100.0, 1)
        app_pct = round(app_ms / total_ms * 100.0, 1)
        silence_pct = round(max(0.0, 100.0 - op_pct - app_pct), 1)

        # Расчет темпа речи (слов в минуту, WPM)
        op_min = max(0.01, op_ms / 60000.0)
        app_min = max(0.01, app_ms / 60000.0)
        op_wpm = round(op_words / op_min, 1)
        app_wpm = round(app_words / app_min, 1)

        return {
            "operator_talk_percent": op_pct,
            "applicant_talk_percent": app_pct,
            "silence_pause_percent": silence_pct,
            "operator_talk_pct": op_pct,
            "applicant_talk_pct": app_pct,
            "silence_pct": silence_pct,
            "operator_speech_rate_wpm": op_wpm,
            "operator_wpm": op_wpm,
            "applicant_wpm": app_wpm,
            "talk_ratio_label": f"{int(op_pct)}% / {int(app_pct)}%",
        }

    @staticmethod
    def detect_interruptions(utterances: List[Utterance], min_overlap_ms: int = 300) -> List[Dict]:
        """Выявляет факты перебивания (одновременной речи в обоих каналах)."""
        interruptions = []
        op_utts = [u for u in utterances if u.speaker == SpeakerRole.OPERATOR]
        app_utts = [u for u in utterances if u.speaker == SpeakerRole.APPLICANT]

        for op_u in op_utts:
            for app_u in app_utts:
                # Проверка пересечения временных интервалов
                overlap_start = max(op_u.start_ms, app_u.start_ms)
                overlap_end = min(op_u.end_ms, app_u.end_ms)
                overlap_dur = overlap_end - overlap_start

                if overlap_dur >= min_overlap_ms:
                    interrupter = "Заявитель" if app_u.start_ms > op_u.start_ms else "Оператор"
                    interruptions.append({
                        "start_ms": overlap_start,
                        "end_ms": overlap_end,
                        "duration_ms": overlap_dur,
                        "overlap_ms": overlap_dur,
                        "interrupter": interrupter,
                        "operator_text": op_u.text,
                        "applicant_text": app_u.text,
                    })

        return interruptions
