"""FastAPI веб-сервер и REST API аналитики контакт-центра МФЦ РУДН."""

import csv
from datetime import datetime, timedelta
import io
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from mfc_analytics.analyzer.pipeline import MFCAnalyticsPipeline
from mfc_analytics.analyzer.operator_analytics import OperatorAnalyticsEngine, OperatorPerformanceProfile
from mfc_analytics.analyzer.correlation_engine import TelephonyCorrelationEngine, TelephonyCorrelationSummary
from mfc_analytics.audio.anonymizer import PIIAnonymizer
from mfc_analytics.audio.audio_engine import TelephonyAudioEngine
from mfc_analytics.audio.diarization import ChannelDiarizer
from mfc_analytics.audio.transcriber import LocalWhisperTranscriber
from mfc_analytics.cms.matcher import CallCMSMatcher
from mfc_analytics.cms.parser import AvayaCMSParser
from mfc_analytics.data.generator import MFCDataGenerator
from mfc_analytics.data.seed_rules import DEPARTMENTS, REFERENCE_RULES
from mfc_analytics.models.action import ActionProblemType, ActionStatus, ManagerAction
from mfc_analytics.models.call import (
    ApplicantCategory,
    Call,
    CallMetadata,
    CallOutcome,
    CallTopic,
    CriterionEvaluation,
    CriterionStatus,
    InquiryType,
    LoadRegime,
    ManagerStatus,
    SpeakerRole,
    Utterance,
)
from mfc_analytics.models.cms import CMSInterval
from mfc_analytics.models.kb_admin import RuleCreateRequest, RuleUpdateRequest
from mfc_analytics.models.knowledge_base import ReferenceRule


app = FastAPI(
    title="МФЦ РУДН — Интеллектуальная аналитика звонков",
    description="Система речевой аналитики, классификации обращений и контроля качества контакт-центра",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация сервисов и хранилища в памяти
generator = MFCDataGenerator(random_seed=42)
anonymizer = PIIAnonymizer()
transcriber = LocalWhisperTranscriber()

# Инициализация базы знаний
RULES_REGISTRY: Dict[str, ReferenceRule] = {r.rule_id: r for r in REFERENCE_RULES}
pipeline = MFCAnalyticsPipeline(rules=list(RULES_REGISTRY.values()))

# Генерация эталонных звонков и их комплексный анализ
raw_calls = generator.generate_curated_calls()
PROCESSED_CALLS: Dict[str, Call] = {}
for c in raw_calls:
    analyzed = pipeline.analyze_call(c)
    PROCESSED_CALLS[analyzed.metadata.call_id] = analyzed

# Генерация и сопоставление интервалов телефонии Avaya CMS
CMS_INTERVALS: List[CMSInterval] = generator.generate_cms_intervals()
cms_matcher = CallCMSMatcher(CMS_INTERVALS)

# Анализ системных проблем и формирование мер
SYSTEMIC_SUMMARY: Dict = pipeline.systemic_detector.analyze_batch(list(PROCESSED_CALLS.values()))
ACTIONS: Dict[str, ManagerAction] = {
    a["action_id"]: ManagerAction(**a) for a in SYSTEMIC_SUMMARY.get("suggested_actions", [])
}


# ==================== DTO Модели запросов ====================

class UpdateStatusRequest(BaseModel):
    manager_status: ManagerStatus
    manager_notes: Optional[str] = None


class ReviewOverrideRequest(BaseModel):
    manager_status: ManagerStatus
    score_override: Optional[float] = None
    manager_notes: Optional[str] = None


class CustomAnalysisRequest(BaseModel):
    caller_text: str
    operator_text: str
    topic_hint: Optional[str] = None


class CreateActionRequest(BaseModel):
    title: str
    problem_type: ActionProblemType
    description: str
    owner: str
    target_days: int = 3
    expected_impact_metric: str
    related_call_ids: List[str] = Field(default_factory=list)


# ==================== Аналитические эндпоинты ====================

@app.get("/api/overview")
def get_overview():
    """Сводные KPI и распределения для аналитического дашборда руководителя."""
    calls = list(PROCESSED_CALLS.values())
    total_calls = len(calls)
    avg_score = round(sum(c.overall_quality_score for c in calls) / max(1, total_calls), 1)
    critical_count = sum(1 for c in calls if c.has_critical_error)
    pending_count = sum(1 for c in calls if c.manager_status == ManagerStatus.PENDING)
    transfers_count = sum(1 for c in calls if c.outcome == CallOutcome.TRANSFERRED)

    # CMS показатели
    total_offered = sum(i.offered_calls for i in CMS_INTERVALS)
    total_answered = sum(i.answered_calls for i in CMS_INTERVALS)
    total_abandoned = sum(i.abandoned_calls for i in CMS_INTERVALS)
    avg_asa = round(sum(i.avg_speed_of_answer_sec for i in CMS_INTERVALS) / max(1, len(CMS_INTERVALS)), 1)
    service_level = round(100.0 * total_answered / max(1, total_offered), 1)

    # Распределение по темам
    topic_counts = {}
    for c in calls:
        t = c.topic.value
        topic_counts[t] = topic_counts.get(t, 0) + 1

    # Распределение по категориям
    cat_counts = {}
    for c in calls:
        cat = c.applicant_category.value
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    # Распределение по исходам
    outcome_counts = {}
    for c in calls:
        o = c.outcome.value
        outcome_counts[o] = outcome_counts.get(o, 0) + 1

    match_stats = cms_matcher.calculate_match_stats(calls)
    systemic_info = pipeline.systemic_detector.analyze_batch(calls)

    return {
        "metrics": {
            "total_calls": total_calls,
            "average_quality_score": avg_score,
            "critical_violations_count": critical_count,
            "pending_review_count": pending_count,
            "transfers_count": transfers_count,
            "fcr_percent": systemic_info.get("fcr_percent", 78.5),
            "repeat_rate_percent": systemic_info.get("repeat_rate_percent", 14.3),
            "cms_total_offered": total_offered,
            "cms_total_answered": total_answered,
            "cms_total_abandoned": total_abandoned,
            "cms_avg_speed_of_answer_sec": avg_asa,
            "cms_service_level_percent": service_level,
            "cms_match_rate_percent": match_stats["match_rate_percent"],
        },
        "topic_distribution": topic_counts,
        "category_distribution": cat_counts,
        "outcome_distribution": outcome_counts,
        "top_systemic_issues": systemic_info.get("top_systemic_issues", []),
        "recent_critical_calls": [
            {
                "call_id": c.metadata.call_id,
                "timestamp": c.metadata.timestamp.isoformat(),
                "topic": c.topic.value,
                "score": c.overall_quality_score,
                "summary": c.critical_error_summary,
                "status": c.manager_status.value,
                "operator": c.metadata.operator_pseudonym,
            }
            for c in calls if c.has_critical_error
        ],
    }


@app.get("/api/calls")
def get_calls(
    topic: Optional[str] = None,
    category: Optional[str] = None,
    critical_only: bool = False,
    status: Optional[str] = None,
    load_regime: Optional[str] = None,
    outcome: Optional[str] = None,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    search: Optional[str] = None,
):
    """Список звонков с многокритериальной фильтрацией и поиском."""
    calls = list(PROCESSED_CALLS.values())

    if topic:
        calls = [c for c in calls if c.topic.value == topic or c.topic.name == topic]
    if category:
        calls = [c for c in calls if c.applicant_category.value == category or c.applicant_category.name == category]
    if critical_only:
        calls = [c for c in calls if c.has_critical_error]
    if status:
        calls = [c for c in calls if c.manager_status.value == status or c.manager_status.name == status]
    if load_regime:
        calls = [c for c in calls if c.metadata.load_regime.value == load_regime or c.metadata.load_regime.name == load_regime]
    if outcome:
        calls = [c for c in calls if c.outcome.value == outcome or c.outcome.name == outcome]
    if min_score is not None:
        calls = [c for c in calls if c.overall_quality_score >= min_score]
    if max_score is not None:
        calls = [c for c in calls if c.overall_quality_score <= max_score]
    if search:
        s = search.lower()
        calls = [
            c for c in calls
            if s in c.metadata.call_id.lower()
            or s in c.full_transcript.lower()
            or s in c.metadata.applicant_pseudonym.lower()
            or s in c.metadata.operator_pseudonym.lower()
        ]

    # Сортировка: сначала критические ошибки, затем по времени убывания
    calls.sort(key=lambda x: (not x.has_critical_error, -x.metadata.timestamp.timestamp()))

    return [
        {
            "call_id": c.metadata.call_id,
            "timestamp": c.metadata.timestamp.isoformat(),
            "duration_seconds": c.metadata.duration_seconds,
            "topic": c.topic.value,
            "applicant_category": c.applicant_category.value,
            "outcome": c.outcome.value,
            "quality_score": c.overall_quality_score,
            "has_critical_error": c.has_critical_error,
            "critical_summary": c.critical_error_summary,
            "manager_status": c.manager_status.value,
            "load_regime": c.metadata.load_regime.value,
            "is_repeat_call": c.metadata.is_repeat_call,
            "operator_pseudonym": c.metadata.operator_pseudonym,
            "applicant_pseudonym": c.metadata.applicant_pseudonym,
        }
        for c in calls
    ]


@app.get("/api/calls/{call_id}")
def get_call_detail(call_id: str):
    """Детальная карточка звонка со всеми репликами, таймкодами, доказательствами и срезом CMS."""
    call = PROCESSED_CALLS.get(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Звонок не найден")

    # Поиск связанного интервала CMS
    matched_cms = cms_matcher.match_call(call)
    waveform = TelephonyAudioEngine.calculate_waveform_bars(call, num_bars=60)
    speech_metrics = ChannelDiarizer.calculate_talk_listen_metrics(call.utterances, call.metadata.duration_seconds)
    interruptions = ChannelDiarizer.detect_interruptions(call.utterances)

    data = call.model_dump()
    data["matched_cms"] = matched_cms.model_dump() if matched_cms else None
    data["waveform_bars"] = waveform
    data["speech_metrics"] = speech_metrics
    data["interruptions"] = interruptions
    return data


@app.get("/api/calls/{call_id}/audio.wav")
def get_call_audio(call_id: str):
    """Синтезирует и отдает реальную двухканальную аудиозапись звонка (16-bit PCM WAV)."""
    call = PROCESSED_CALLS.get(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Звонок не найден")

    wav_bytes = TelephonyAudioEngine.synthesize_call_audio(call)
    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'inline; filename="{call_id}.wav"',
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
        },
    )


@app.get("/api/calls/{call_id}/waveform")
def get_call_waveform(call_id: str):
    """Рассчитывает амплитудные бары звуковой волны звонка."""
    call = PROCESSED_CALLS.get(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    return TelephonyAudioEngine.calculate_waveform_bars(call, num_bars=60)


@app.post("/api/calls/{call_id}/status")
def update_call_status(call_id: str, req: UpdateStatusRequest):
    """Обновление статуса проверки звонка руководителем."""
    call = PROCESSED_CALLS.get(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    call.manager_status = req.manager_status
    if req.manager_notes:
        call.manager_notes = req.manager_notes
    return {"status": "ok", "call_id": call_id, "new_status": call.manager_status.value}


@app.post("/api/calls/{call_id}/review")
def review_call_with_override(call_id: str, req: ReviewOverrideRequest):
    """Human-in-the-Loop экспертная корректировка оценки качества звонка."""
    call = PROCESSED_CALLS.get(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    call.manager_status = req.manager_status
    if req.score_override is not None:
        call.overall_quality_score = max(0.0, min(100.0, req.score_override))
    if req.manager_notes:
        call.manager_notes = req.manager_notes
    return {
        "status": "ok",
        "call_id": call_id,
        "new_score": call.overall_quality_score,
        "manager_status": call.manager_status.value,
        "manager_notes": call.manager_notes,
    }


# ==================== Загрузка данных и 152-ФЗ ====================

@app.post("/api/calls/upload")
async def upload_call_transcript(
    caller_text: str = Form(...),
    operator_text: str = Form(...),
    call_id: Optional[str] = Form(None),
    operator_name: Optional[str] = Form("Оператор №10"),
    topic_override: Optional[str] = Form(None),
):
    """Загрузка нового диалога, маскирование ПДн по 152-ФЗ и полный автоанализ."""
    now = datetime.now()
    cid = call_id or f"CALL-UP-{now.strftime('%m%d-%H%M%S')}"

    # Обезличивание чувствительных данных
    clean_caller, stats_c = anonymizer.mask_text(caller_text)
    clean_operator, stats_o = anonymizer.mask_text(operator_text)

    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2500, text="Добрый день! Контакт-центр МФЦ РУДН. Чем могу помочь?"),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2800, end_ms=9000, text=clean_caller),
        Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=9500, end_ms=18000, text=clean_operator),
        Utterance(id=4, speaker=SpeakerRole.APPLICANT, start_ms=18500, end_ms=21000, text="Спасибо, всё понятно."),
        Utterance(id=5, speaker=SpeakerRole.OPERATOR, start_ms=21500, end_ms=24000, text="Пожалуйста! Хорошего дня, до свидания!"),
    ]

    meta = CallMetadata(
        call_id=cid,
        timestamp=now,
        duration_seconds=24,
        queue_name="VDN_MFC_RUDN",
        load_regime=LoadRegime.TYPICAL,
        operator_pseudonym=operator_name or "Оператор",
        applicant_pseudonym=anonymizer.generate_pseudonym(clean_caller),
        is_repeat_call=False,
    )

    new_call = Call(metadata=meta, utterances=utterances)
    analyzed = pipeline.analyze_call(new_call)
    PROCESSED_CALLS[cid] = analyzed

    total_stats = {k: stats_c.get(k, 0) + stats_o.get(k, 0) for k in stats_c}

    return {
        "status": "created",
        "call": analyzed.model_dump(),
        "anonymization_stats": total_stats,
    }


# ==================== Телефония Avaya CMS ====================

@app.get("/api/cms/intervals")
def get_cms_intervals(limit: int = 60, peak_only: bool = False):
    """Интервалы телефонии Avaya CMS для визуализации нагрузки и очередей."""
    intervals = CMS_INTERVALS
    if peak_only:
        intervals = [i for i in intervals if i.load_regime == LoadRegime.HIGH]
    return [i.model_dump() for i in intervals[:limit]]


@app.get("/api/cms/summary")
def get_cms_summary():
    """Сводные показатели и часовые распределения телефонии."""
    total_offered = sum(i.offered_calls for i in CMS_INTERVALS)
    total_answered = sum(i.answered_calls for i in CMS_INTERVALS)
    total_abandoned = sum(i.abandoned_calls for i in CMS_INTERVALS)
    avg_asa = round(sum(i.avg_speed_of_answer_sec for i in CMS_INTERVALS) / max(1, len(CMS_INTERVALS)), 1)
    avg_aht = round(sum(i.avg_handle_time_sec for i in CMS_INTERVALS) / max(1, len(CMS_INTERVALS)), 1)
    service_level = round(100.0 * total_answered / max(1, total_offered), 1)

    # Почасовая агрегация за весь период
    hourly_offered = {}
    hourly_abandoned = {}
    for i in CMS_INTERVALS:
        h = f"{i.interval_start.hour:02d}:00"
        hourly_offered[h] = hourly_offered.get(h, 0) + i.offered_calls
        hourly_abandoned[h] = hourly_abandoned.get(h, 0) + i.abandoned_calls

    return {
        "total_intervals": len(CMS_INTERVALS),
        "total_offered": total_offered,
        "total_answered": total_answered,
        "total_abandoned": total_abandoned,
        "average_speed_of_answer_sec": avg_asa,
        "average_handle_time_sec": avg_aht,
        "service_level_percent": service_level,
        "hourly_offered": hourly_offered,
        "hourly_abandoned": hourly_abandoned,
    }


@app.post("/api/cms/upload")
async def upload_cms_csv(file: UploadFile = File(...)):
    """Загрузка реального CSV отчета Avaya CMS Supervisor."""
    global CMS_INTERVALS, cms_matcher
    content = (await file.read()).decode("utf-8", errors="ignore")
    parsed_intervals = AvayaCMSParser.parse_csv(content)

    if not parsed_intervals:
        raise HTTPException(status_code=400, detail="Не удалось распознать интервалы CMS из переданного файла")

    CMS_INTERVALS = parsed_intervals
    cms_matcher = CallCMSMatcher(CMS_INTERVALS)

    return {
        "status": "success",
        "intervals_imported": len(parsed_intervals),
        "sample_interval": parsed_intervals[0].model_dump(),
    }


# ==================== База знаний регламентов (CRUD) ====================

@app.get("/api/rules")
def get_rules():
    """Справочник действующих эталонных правил РУДН."""
    return [r.model_dump() for r in RULES_REGISTRY.values()]


@app.post("/api/rules")
def create_rule(req: RuleCreateRequest):
    """Добавление нового эталонного правила в базу знаний."""
    if req.rule_id in RULES_REGISTRY:
        raise HTTPException(status_code=400, detail="Правило с таким ID уже существует")

    new_rule = ReferenceRule(
        rule_id=req.rule_id,
        category=req.category,
        title=req.title,
        valid_from=req.valid_from,
        valid_to=req.valid_to,
        exact_rule_text=req.exact_rule_text,
        source_document=req.source_document,
        critical_terms=req.critical_terms,
        common_errors=req.common_errors,
        mandatory_checklist=req.mandatory_checklist,
        target_department=req.target_department,
    )
    RULES_REGISTRY[req.rule_id] = new_rule
    pipeline.rules = list(RULES_REGISTRY.values())
    return {"status": "created", "rule": new_rule.model_dump()}


@app.put("/api/rules/{rule_id}")
def update_rule(rule_id: str, req: RuleUpdateRequest):
    """Изменение существующего эталонного правила."""
    rule = RULES_REGISTRY.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Правило не найдено")

    update_data = req.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        if val is not None:
            setattr(rule, field, val)

    pipeline.rules = list(RULES_REGISTRY.values())
    return {"status": "updated", "rule": rule.model_dump()}


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: str):
    """Удаление правила из базы знаний."""
    if rule_id not in RULES_REGISTRY:
        raise HTTPException(status_code=404, detail="Правило не найдено")
    deleted = RULES_REGISTRY.pop(rule_id)
    pipeline.rules = list(RULES_REGISTRY.values())
    return {"status": "deleted", "rule_id": rule_id}


# ==================== Управленческие меры руководителя ====================

@app.get("/api/actions")
def get_actions():
    """Список управленческих мер руководителя и статус их выполнения."""
    return [a.model_dump() for a in ACTIONS.values()]


@app.post("/api/actions")
def create_action(req: CreateActionRequest):
    """Создание нового управленческого действия руководителем."""
    now = datetime.now()
    action_id = f"ACT-2026-{len(ACTIONS) + 1:03d}"
    target_date = now + timedelta(days=req.target_days)

    action = ManagerAction(
        action_id=action_id,
        title=req.title,
        problem_type=req.problem_type,
        description=req.description,
        owner=req.owner,
        related_call_ids=req.related_call_ids,
        created_at=now,
        target_date=target_date,
        status=ActionStatus.OPEN,
        expected_impact_metric=req.expected_impact_metric,
    )
    ACTIONS[action_id] = action
    return {"status": "created", "action": action.model_dump()}


@app.patch("/api/actions/{action_id}/status")
def update_action_status(action_id: str, status: ActionStatus):
    """Изменение статуса управленческой меры."""
    action = ACTIONS.get(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Мера не найдена")
    action.status = status
    return {"status": "ok", "action": action.model_dump()}


@app.delete("/api/actions/{action_id}")
def delete_action(action_id: str):
    """Удаление управленческой меры."""
    if action_id not in ACTIONS:
        raise HTTPException(status_code=404, detail="Мера не найдена")
    ACTIONS.pop(action_id)
    return {"status": "deleted", "action_id": action_id}


# ==================== Тест-стенд / Речевая лаборатория ====================

@app.post("/api/analyze-custom")
def analyze_custom(req: CustomAnalysisRequest):
    """Интерактивный анализ произвольного диалога в реальном времени."""
    now = datetime.now()
    clean_caller, stats_c = anonymizer.mask_text(req.caller_text)
    clean_operator, stats_o = anonymizer.mask_text(req.operator_text)

    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2500, text="Добрый день! Контакт-центр МФЦ РУДН, слушаю вас."),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2800, end_ms=8000, text=clean_caller),
        Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=8500, end_ms=16000, text=clean_operator),
        Utterance(id=4, speaker=SpeakerRole.APPLICANT, start_ms=16500, end_ms=19000, text="Хорошо, спасибо."),
        Utterance(id=5, speaker=SpeakerRole.OPERATOR, start_ms=19500, end_ms=22000, text="Всего доброго! До свидания."),
    ]

    meta = CallMetadata(
        call_id=f"TEST-{now.strftime('%H%M%S')}",
        timestamp=now,
        duration_seconds=22,
        operator_pseudonym="Тестовый оператор",
        applicant_pseudonym="Тестовый заявитель",
    )

    test_call = Call(metadata=meta, utterances=utterances)
    analyzed = pipeline.analyze_call(test_call)
    data = analyzed.model_dump()
    data["anonymization_stats"] = {k: stats_c.get(k, 0) + stats_o.get(k, 0) for k in stats_c}
    return data


# ==================== Экспорт отчетов ====================

@app.get("/api/reports/export")
def export_calls_csv():
    """Экспорт реестра звонков в CSV для руководства университета."""
    calls = list(PROCESSED_CALLS.values())
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    writer.writerow([
        "ID звонка",
        "Время (МСК)",
        "Длительность (сек)",
        "Тематика",
        "Категория заявителя",
        "Итог консультации",
        "Оценка качества (%)",
        "Критическая ошибка",
        "Описание проблемы",
        "Статус проверки",
        "Режим нагрузки",
        "Оператор",
        "Псевдоним заявителя",
    ])

    for c in calls:
        writer.writerow([
            c.metadata.call_id,
            c.metadata.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            c.metadata.duration_seconds,
            c.topic.value,
            c.applicant_category.value,
            c.outcome.value,
            c.overall_quality_score,
            "Да" if c.has_critical_error else "Нет",
            c.critical_error_summary or "",
            c.manager_status.value,
            c.metadata.load_regime.value,
            c.metadata.operator_pseudonym,
            c.metadata.applicant_pseudonym,
        ])

    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mfc_rudn_calls_report.csv"},
    )


# ==================== Аналитика операторов ====================

@app.get("/api/operators")
def get_operators_leaderboard():
    """Рейтинг и профили качества операторов контакт-центра МФЦ РУДН."""
    calls = list(PROCESSED_CALLS.values())
    profiles = OperatorAnalyticsEngine.calculate_profiles(calls)
    return [p.model_dump() for p in profiles]


@app.get("/api/operators/{operator_name}")
def get_operator_detail(operator_name: str):
    """Детальная статистика конкретного оператора со списком звонков."""
    calls = [c for c in PROCESSED_CALLS.values() if c.metadata.operator_pseudonym == operator_name]
    if not calls:
        raise HTTPException(status_code=404, detail="Оператор не найден")

    profiles = OperatorAnalyticsEngine.calculate_profiles(calls)
    profile = profiles[0] if profiles else None

    return {
        "profile": profile.model_dump() if profile else None,
        "calls": [
            {
                "call_id": c.metadata.call_id,
                "timestamp": c.metadata.timestamp.isoformat(),
                "topic": c.topic.value,
                "score": c.overall_quality_score,
                "has_critical": c.has_critical_error,
                "outcome": c.outcome.value,
            }
            for c in calls
        ]
    }


# ==================== Корреляция нагрузки CMS и качества ====================

@app.get("/api/analytics/correlation")
def get_telephony_correlation():
    """Аналитика взаимосвязи перегрузки телефонии и частоты ошибок операторов."""
    calls = list(PROCESSED_CALLS.values())
    summary = TelephonyCorrelationEngine.analyze_correlation(calls, CMS_INTERVALS)
    return summary.model_dump()


# ==================== Исполнительный отчёт руководству ====================

@app.get("/api/reports/executive")
def get_executive_report():
    """Сводный структурированный отчёт по итогам аналитики для ректората РУДН."""
    calls = list(PROCESSED_CALLS.values())
    total_calls = len(calls)
    avg_score = round(sum(c.overall_quality_score for c in calls) / max(1, total_calls), 1)
    critical_count = sum(1 for c in calls if c.has_critical_error)

    # CMS сводка
    total_offered = sum(i.offered_calls for i in CMS_INTERVALS)
    total_answered = sum(i.answered_calls for i in CMS_INTERVALS)
    total_abandoned = sum(i.abandoned_calls for i in CMS_INTERVALS)
    avg_asa = round(sum(i.avg_speed_of_answer_sec for i in CMS_INTERVALS) / max(1, len(CMS_INTERVALS)), 1)

    systemic = pipeline.systemic_detector.analyze_batch(calls)
    correlation = TelephonyCorrelationEngine.analyze_correlation(calls, CMS_INTERVALS)

    return {
        "university": "Российский университет дружбы народов имени Патриса Лумумбы",
        "subdivision": "Многофункциональный центр РУДН (МФЦ РУДН)",
        "campaign": "Приёмная кампания 2026 года",
        "generated_at": datetime.now().isoformat(),
        "executive_summary": {
            "total_calls_analyzed": total_calls,
            "overall_qa_score": avg_score,
            "critical_incidents": critical_count,
            "first_contact_resolution_fcr": systemic.get("fcr_percent", 78.5),
            "repeat_call_rate": systemic.get("repeat_rate_percent", 14.3),
            "telephony_service_level": round(100.0 * total_answered / max(1, total_offered), 1),
            "telephony_avg_speed_of_answer_sec": avg_asa,
            "telephony_total_abandoned": total_abandoned,
        },
        "top_systemic_issues": systemic.get("top_systemic_issues", []),
        "load_regime_impact": [b.model_dump() for b in correlation.regime_breakdown],
        "key_findings": correlation.key_findings,
        "recommended_action_plan": [a.model_dump() for a in ACTIONS.values()],
    }


@app.get("/api/reports/print", response_class=HTMLResponse)
def get_printable_report():
    """Генерирует официальный печатный аналитический бриф для руководства РУДН."""
    data = get_executive_report()
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    issues_html = "".join(f"""
        <div style="margin-bottom: 12px; padding: 10px; border-left: 4px solid #d97706; background: #fdfaf6;">
            <strong>{iss['title']}</strong> ({iss['category']})<br>
            <span style="font-size: 13px; color: #555;">Причина: {iss['root_cause']}</span><br>
            <span style="font-size: 12px; color: #888;">Затронуто обращений: {iss['affected_calls_count']} ({iss['share_percent']}%)</span>
        </div>
    """ for iss in data['top_systemic_issues'])

    actions_html = "".join(f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-family: monospace;">{act['action_id']}</td>
            <td style="padding: 8px; border: 1px solid #ddd;"><strong>{act['title']}</strong><br><span style="font-size: 12px; color: #555;">{act['description']}</span></td>
            <td style="padding: 8px; border: 1px solid #ddd;">{act['owner']}</td>
            <td style="padding: 8px; border: 1px solid #ddd; color: #0284c7; font-weight: bold;">{act['expected_impact_metric']}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{act['status']}</td>
        </tr>
    """ for act in data['recommended_action_plan'])

    html = f"""<!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Аналитический отчёт МФЦ РУДН — Приёмная кампания 2026</title>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; color: #222; line-height: 1.5; }}
            h1, h2, h3 {{ color: #002B66; }}
            .header-bar {{ border-bottom: 3px solid #002B66; padding-bottom: 15px; margin-bottom: 25px; display: flex; justify-content: space-between; align-items: flex-end; }}
            .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }}
            .kpi-card {{ background: #f4f7fb; padding: 15px; border-radius: 8px; border: 1px solid #dce4ee; text-align: center; }}
            .kpi-card strong {{ font-size: 24px; color: #002B66; display: block; }}
            .kpi-card span {{ font-size: 11px; text-transform: uppercase; color: #666; font-weight: bold; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 13px; }}
            @media print {{
                body {{ margin: 15mm; }}
                .no-print {{ display: none; }}
            }}
        </style>
    </head>
    <body>
        <div class="no-print" style="margin-bottom: 20px; text-align: right;">
            <button onclick="window.print()" style="padding: 10px 20px; background: #002B66; color: white; border: none; border-radius: 6px; font-weight: bold; cursor: pointer;">
                Печать / Экспорт в PDF
            </button>
        </div>

        <div class="header-bar">
            <div>
                <h2>{data['university']}</h2>
                <h1 style="margin: 0; font-size: 22px;">{data['subdivision']}</h1>
                <p style="margin: 5px 0 0 0; color: #666;">Аналитический отчёт руководителя: Контроль качества телефонных консультаций</p>
            </div>
            <div style="text-align: right; font-size: 12px; color: #777;">
                Сезон: <strong>{data['campaign']}</strong><br>
                Дата выгрузки: {now_str}
            </div>
        </div>

        <h3>1. Сводные операционные показатели линии МФЦ</h3>
        <div class="kpi-grid">
            <div class="kpi-card">
                <strong>{data['executive_summary']['total_calls_analyzed']}</strong>
                <span>Анализ звонков</span>
            </div>
            <div class="kpi-card">
                <strong style="color: #059669;">{data['executive_summary']['overall_qa_score']}%</strong>
                <span>Индекс качества (QA)</span>
            </div>
            <div class="kpi-card">
                <strong style="color: #dc2626;">{data['executive_summary']['critical_incidents']}</strong>
                <span>Критические ошибки</span>
            </div>
            <div class="kpi-card">
                <strong>{data['executive_summary']['first_contact_resolution_fcr']}%</strong>
                <span>FCR (Решено на 1 линии)</span>
            </div>
        </div>

        <h3>2. Влияние нагрузки телефонии Avaya CMS на качество сервиса</h3>
        <p style="font-size: 13px; color: #444;">
            Сравнение телефонных консультаций в интервалы пиковой (HIGH), штатной (TYPICAL) и минимальной (LOW) нагрузки:
        </p>
        <ul style="font-size: 13px; color: #333; line-height: 1.8;">
            {''.join(f'<li>{f}</li>' for f in data['key_findings'])}
        </ul>

        <h3>3. Топ системных инцидентов и информационных пробелов</h3>
        {issues_html}

        <h3 style="margin-top: 30px;">4. Утверждённый план управленческих мер (Action Plan)</h3>
        <table>
            <thead>
                <tr style="background: #002B66; color: white;">
                    <th style="padding: 8px; border: 1px solid #002B66;">ID</th>
                    <th style="padding: 8px; border: 1px solid #002B66;">Наименование меры и описание</th>
                    <th style="padding: 8px; border: 1px solid #002B66;">Ответственный</th>
                    <th style="padding: 8px; border: 1px solid #002B66;">Целевой эффект</th>
                    <th style="padding: 8px; border: 1px solid #002B66;">Статус</th>
                </tr>
            </thead>
            <tbody>
                {actions_html}
            </tbody>
        </table>

        <div style="margin-top: 50px; padding-top: 20px; border-top: 1px solid #ccc; display: flex; justify-content: space-between; font-size: 12px; color: #555;">
            <div>Отчёт сформирован интеллектуальным комплексом МФЦ РУДН по 152-ФЗ.</div>
            <div>Подпись руководителя МФЦ: ____________________</div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/", response_class=HTMLResponse)
def serve_index():
    """Отдает главную страницу SPA дашборда."""
    index_path = Path(__file__).parent.parent / "web" / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Интерфейс инициализируется...</h1>")
