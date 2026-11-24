"""Модуль генерации и обработки звука телефонии для МФЦ РУДН.
Создает двухканальные стерео-аудиозаписи (Avaya VDN), рассчитывает звуковую волну и VAD.
"""

import io
import math
import struct
from typing import Dict, List, Optional, Tuple
import wave

from mfc_analytics.models.call import Call, SpeakerRole, Utterance


class TelephonyAudioEngine:
    """Движок синтеза и акустического анализа записей телефонных разговоров контакт-центра."""

    SAMPLE_RATE = 16000
    CHANNELS = 2  # Стерео: левый - оператор, правый - заявитель

    @classmethod
    def synthesize_call_audio(cls, call: Call) -> bytes:
        """Синтезирует двухканальную стерео-аудиозапись (WAV 16-bit PCM) на основе реплик диалога."""
        duration_ms = call.metadata.duration_seconds * 1000
        if call.utterances:
            max_end = max(u.end_ms for u in call.utterances)
            duration_ms = max(duration_ms, max_end + 1000)

        total_samples = int((duration_ms / 1000.0) * cls.SAMPLE_RATE)
        sample_rate = cls.SAMPLE_RATE

        # Массивы отсчетов для левого (оператор) и правого (заявитель) каналов
        left_samples = [0.0] * total_samples
        right_samples = [0.0] * total_samples

        # 1. Легкий комфортный шум телефонии (-42 дБ)
        for i in range(total_samples):
            # Псевдослучайный шум через синусоиды разной частоты
            noise = (math.sin(i * 0.05) + math.sin(i * 0.13) + math.sin(i * 0.29)) * 0.003
            left_samples[i] += noise
            right_samples[i] += noise

        # 2. Модуляция реплик
        for u in call.utterances:
            start_idx = max(0, int((u.start_ms / 1000.0) * sample_rate))
            end_idx = min(total_samples, int((u.end_ms / 1000.0) * sample_rate))
            if start_idx >= end_idx:
                continue

            # Акустические характеристики голоса
            is_operator = (u.speaker == SpeakerRole.OPERATOR)
            base_freq = 210.0 if is_operator else 135.0  # Основной тон F0 (Гц)
            f1 = 650.0 if is_operator else 500.0        # Форманта F1
            f2 = 1850.0 if is_operator else 1500.0      # Форманта F2

            # Длина реплики в сэмплах
            utt_len = end_idx - start_idx

            for idx in range(start_idx, end_idx):
                rel_idx = idx - start_idx
                t = rel_idx / sample_rate

                # Слоговая модуляция (слоги русской речи ~ 4-5 Гц)
                syllable_env = 0.5 * (1.0 + math.sin(2.0 * math.pi * 4.5 * t))
                # Огибающая нарастания и затухания реплики (attack/decay)
                fade_len = int(sample_rate * 0.08)
                attack_decay = 1.0
                if rel_idx < fade_len:
                    attack_decay = rel_idx / fade_len
                elif rel_idx > utt_len - fade_len:
                    attack_decay = max(0.0, (utt_len - rel_idx) / fade_len)

                # Гармонический состав речи
                signal = (
                    0.50 * math.sin(2.0 * math.pi * base_freq * t)
                    + 0.30 * math.sin(2.0 * math.pi * f1 * t)
                    + 0.20 * math.sin(2.0 * math.pi * f2 * t)
                ) * syllable_env * attack_decay * 0.35

                if is_operator:
                    left_samples[idx] += signal
                else:
                    right_samples[idx] += signal

        # 3. Упаковка в 16-bit PCM WAV
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(cls.CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)

            frames = bytearray()
            for i in range(total_samples):
                # Ограничение диапазона [-1.0, 1.0]
                l_val = max(-1.0, min(1.0, left_samples[i]))
                r_val = max(-1.0, min(1.0, right_samples[i]))

                l_int = int(l_val * 32767.0)
                r_int = int(r_val * 32767.0)
                frames.extend(struct.pack("<hh", l_int, r_int))

            wf.writeframes(frames)

        return buf.getvalue()

    @classmethod
    def calculate_waveform_bars(cls, call: Call, num_bars: int = 60) -> List[Dict]:
        """Рассчитывает амплитудную звуковую волну с разделением ролей для визуализации."""
        total_sec = max(1, call.metadata.duration_seconds)
        bars: List[Dict] = []

        sec_per_bar = total_sec / num_bars

        for b in range(num_bars):
            bar_start_ms = int(b * sec_per_bar * 1000)
            bar_end_ms = int((b + 1) * sec_per_bar * 1000)
            bar_center_ms = (bar_start_ms + bar_end_ms) // 2

            # Проверяем, чья реплика звучит в этом таймкоде
            speaker = "SILENCE"
            is_evidence = False
            for u in call.utterances:
                if u.start_ms <= bar_center_ms <= u.end_ms:
                    speaker = "OPERATOR" if u.speaker == SpeakerRole.OPERATOR else "APPLICANT"
                    is_evidence = u.is_key_evidence
                    break

            # Амплитуда
            if speaker == "OPERATOR":
                amp = 45 + int(35 * abs(math.sin(b * 0.8)))
            elif speaker == "APPLICANT":
                amp = 40 + int(30 * abs(math.cos(b * 0.7)))
            else:
                amp = 8 + int(6 * abs(math.sin(b * 1.5)))

            bars.append({
                "bar_index": b,
                "time_ms": bar_center_ms,
                "amplitude_percent": min(100, amp),
                "speaker": speaker,
                "is_evidence": is_evidence,
            })

        return bars
