"""Тесты аудиодвижка телефонии и синтеза звука."""

from datetime import datetime
import io
import wave
from mfc_analytics.audio.audio_engine import TelephonyAudioEngine
from mfc_analytics.audio.transcriber import LocalWhisperTranscriber
from mfc_analytics.models.call import (
    Call,
    CallMetadata,
    SpeakerRole,
    Utterance,
)


def test_synthesize_call_audio():
    meta = CallMetadata(
        call_id="TEST-AUDIO-01",
        timestamp=datetime(2026, 8, 4, 11, 0, 0),
        duration_seconds=6,
    )
    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2500, text="МФЦ РУДН, здравствуйте!"),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2800, end_ms=5500, text="Здравствуйте, до скольких согласия?"),
    ]
    call = Call(metadata=meta, utterances=utterances)

    wav_bytes = TelephonyAudioEngine.synthesize_call_audio(call)
    assert len(wav_bytes) > 1000

    # Проверка формата через wave
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        assert wf.getnchannels() == 2  # Стерео
        assert wf.getsampwidth() == 2  # 16-bit PCM
        assert wf.getframerate() == 16000
        n_frames = wf.getnframes()
        duration_sec = n_frames / 16000.0
        assert duration_sec >= 6.0


def test_calculate_waveform_bars():
    meta = CallMetadata(
        call_id="TEST-WAVE-01",
        timestamp=datetime(2026, 8, 4, 11, 0, 0),
        duration_seconds=20,
    )
    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=8000, text="Оператор говорит"),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=8500, end_ms=18000, text="Заявитель говорит", is_key_evidence=True),
    ]
    call = Call(metadata=meta, utterances=utterances)

    bars = TelephonyAudioEngine.calculate_waveform_bars(call, num_bars=50)
    assert len(bars) == 50
    assert any(b["speaker"] == "OPERATOR" for b in bars)
    assert any(b["speaker"] == "APPLICANT" for b in bars)
    assert any(b["is_evidence"] is True for b in bars)


def test_transcriber_parse_text():
    transcriber = LocalWhisperTranscriber()
    raw = """
    Оператор: Добрый день, МФЦ РУДН!
    Заявитель: Здравствуйте, мой телефон +7 925 111-22-33, когда списки?
    Оператор: Списки будут опубликованы 27 июля.
    """
    utts = transcriber.parse_transcript_text(raw)
    assert len(utts) == 3
    assert utts[0].speaker == SpeakerRole.OPERATOR
    assert utts[1].speaker == SpeakerRole.APPLICANT
    assert "+7 925 111-22-33" not in utts[1].text
    assert "[ТЕЛЕФОН_СКРЫТ]" in utts[1].text
