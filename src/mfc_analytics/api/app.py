"""FastAPI веб-сервер и REST API аналитики контакт-центра МФЦ РУДН."""

import csv
from datetime import datetime
import io
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel

from mfc_analytics.analyzer.pipeline import MFCAnalyticsPipeline
from mfc_analytics.audio.anonymizer import PIIAnonymizer
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
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальное хранилище данных в памяти
generator = MFCDataGenerator(random_seed=42)
pipeline = MFCAnalyticsPipeline()
anonymizer = PIIAnonymizer()
transcriber = LocalWhisperTranscriber()

# Инициализация базы знаний
RULES_REGISTRY: Dict[str, ReferenceRule] = {r.rule_id: r for r in REFERENCE_RULES}
pipeline.rules = list(RULES_REGISTRY.values())

raw_calls = generator.generate_curated_calls()
PROCESSED_CALLS: Dict[str, Call] = {}
for c in raw_calls:
    analyzed = pipeline.analyze_call(c)
    PROCESSED_CALLS[analyzed.metadata.call_id] = analyzed

CMS_INTERVALS: List[CMSInterval] = generator.generate_cms_intervals()
cms_matcher = CallCMSMatcher(CMS_INTERVALS)

SYSTEMIC_SUMMARY: Dict = pipeline.systemic_detector.analyze_batch(list(PROCESSED_CALLS.values()))
ACTIONS: Dict[str, ManagerAction] = {
    a["action_id"]: ManagerAction(**a) for a in SYSTEMIC_SUMMARY.get("suggested_actions", [])
}


# Запросы для обновления статуса
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


@app.get("/api/overview")
def get_overview():
    """Сводная информация для дашборда руководителя."""
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

    match_stats = cms_matcher.calculate_match_stats(calls)

    return {
        "metrics": {
            "total_calls": total_calls,
            "average_quality_score": avg_score,
            "critical_violations_count": critical_count,
            "pending_review_count": pending_count,
            "transfers_count": transfers_count,
            "fcr_percent": SYSTEMIC_SUMMARY.get("fcr_percent", 78.5),
            "repeat_rate_percent": SYSTEMIC_SUMMARY.get("repeat_rate_percent", 14.3),
            "cms_total_offered": total_offered,
            "cms_total_answered": total_answered,
            "cms_total_abandoned": total_abandoned,
            "cms_avg_speed_of_answer_sec": avg_asa,
            "cms_match_rate_percent": match_stats["match_rate_percent"],
        },
        "topic_distribution": topic_counts,
        "category_distribution": cat_counts,
        "recent_critical_calls": [
            {
                "call_id": c.metadata.call_id,
                "timestamp": c.metadata.timestamp.isoformat(),
                "topic": c.topic.value,
                "score": c.overall_quality_score,
                "summary": c.critical_error_summary,
                "status": c.manager_status.value,
            }
            for c in calls if c.has_critical_error
        ],
    }


@app.get("/api/calls")
def get_calls(
    topic: Optional[str] = None,
    critical_only: bool = False,
    status: Optional[str] = None,
    load_regime: Optional[str] = None,
    search: Optional[str] = None,
):
    """Список звонков с фильтрацией и поиском."""
    calls = list(PROCESSED_CALLS.values())

    if topic:
        calls = [c for c in calls if c.topic.value == topic or c.topic.name == topic]
    if critical_only:
        calls = [c for c in calls if c.has_critical_error]
    if status:
        calls = [c for c in calls if c.manager_status.value == status or c.manager_status.name == status]
    if load_regime:
        calls = [c for c in calls if c.metadata.load_regime.value == load_regime or c.metadata.load_regime.name == load_regime]
    if search:
        s = search.lower()
        calls = [
            c for c in calls
            if s in c.metadata.call_id.lower()
            or s in c.full_transcript.lower()
            or s in c.metadata.applicant_pseudonym.lower()
        ]

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
        }
        for c in calls
    ]


@app.get("/api/calls/{call_id}")
def get_call_detail(call_id: str):
    """Детальная карточка звонка со всеми репликами, таймкодами и оценками."""
    call = PROCESSED_CALLS.get(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    
    # Поиск связанного интервала CMS
    matched_cms = cms_matcher.match_call(call)
    data = call.model_dump()
    data["matched_cms"] = matched_cms.model_dump() if matched_cms else None
    return data


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
    """Human-in-the-Loop корректировка оценки качества звонка экспертом."""
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
    }


@app.get("/api/cms/intervals")
def get_cms_intervals(limit: int = 50, peak_only: bool = False):
    """Данные интервалов Avaya CMS для построения графиков нагрузки."""
    intervals = CMS_INTERVALS
    if peak_only:
        intervals = [i for i in intervals if i.load_regime == LoadRegime.HIGH]
    return [i.model_dump() for i in intervals[:limit]]


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


@app.post("/api/calls/upload")
async def upload_call_transcript(
    caller_text: str = Form(...),
    operator_text: str = Form(...),
    call_id: Optional[str] = Form(None),
    operator_name: Optional[str] = Form("Оператор №10"),
):
    """Загрузка нового диалога, маскирование ПДн по 152-ФЗ и полный автоанализ."""
    now = datetime.now()
    cid = call_id or f"CALL-UP-{now.strftime('%m%d-%H%M%S')}"

    # Обезличивание ПДн
    clean_caller, stats_c = anonymizer.mask_text(caller_text)
    clean_operator, stats_o = anonymizer.mask_text(operator_text)

    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2500, text="Добрый день! Контакт-центр МФЦ РУДН. Чем могу помочь?"),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2800, end_ms=9000, text=clean_caller),
        Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=9500, end_ms=18000, text=clean_operator),
    ]

    meta = CallMetadata(
        call_id=cid,
        timestamp=now,
        duration_seconds=19,
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


# ==================== CRUD Базы знаний регламентов ====================

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


# ==================== Экспорт аналитического отчета ====================

@app.get("/api/reports/export")
def export_calls_csv():
    """Экспорт реестра звонков в CSV для руководства университета."""
    calls = list(PROCESSED_CALLS.values())
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    
    # Заголовки
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


# ==================== Управленческие меры ====================

@app.get("/api/actions")
def get_actions():
    """Список управленческих действий и мер."""
    return [a.model_dump() for a in ACTIONS.values()]


@app.post("/api/actions")
def create_action(action: ManagerAction):
    """Создание новой управленческой меры."""
    ACTIONS[action.action_id] = action
    return {"status": "created", "action": action.model_dump()}


@app.patch("/api/actions/{action_id}/status")
def update_action_status(action_id: str, status: ActionStatus):
    """Изменение статуса управленческой меры."""
    action = ACTIONS.get(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Мера не найдена")
    action.status = status
    return {"status": "ok", "action": action.model_dump()}


@app.post("/api/analyze-custom")
def analyze_custom(req: CustomAnalysisRequest):
    """Интерактивный анализ произвольного диалога в реальном времени."""
    now = datetime.now()
    clean_caller, _ = anonymizer.mask_text(req.caller_text)
    clean_operator, _ = anonymizer.mask_text(req.operator_text)

    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2500, text="Добрый день! Контакт-центр МФЦ РУДН, слушаю вас."),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2800, end_ms=8000, text=clean_caller),
        Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=8500, end_ms=15000, text=clean_operator),
    ]

    meta = CallMetadata(
        call_id=f"TEST-{now.strftime('%H%M%S')}",
        timestamp=now,
        duration_seconds=16,
        operator_pseudonym="Тестовый оператор",
        applicant_pseudonym="Тестовый заявитель",
    )

    test_call = Call(metadata=meta, utterances=utterances)
    analyzed = pipeline.analyze_call(test_call)
    return analyzed.model_dump()


@app.get("/", response_class=HTMLResponse)
def serve_index():
    """Отдает главную страницу дашборда."""
    index_path = Path(__file__).parent.parent / "web" / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Интерфейс инициализируется...</h1>")
