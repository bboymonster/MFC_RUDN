"""Модуль диаризации и разделения каналов телефонии."""

from typing import List, Optional
from mfc_analytics.models.call import SpeakerRole, Utterance


class ChannelDiarizer:
    """Разделение ролей говорящих по каналам стерео-записи телефонии Avaya."""

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
        # Сортировка по времени начала реплики
        utterances.sort(key=lambda u: u.start_ms)
        return utterances
