"""FastAPI веб-сервер и REST API аналитики контакт-центра МФЦ РУДН."""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from mfc_analytics.analyzer.pipeline import MFCAnalyticsPipeline
from mfc_analytics.data.generator import MFCDataGenerator
from mfc_analytics.data.seed_rules import DEPARTMENTS, REFERENCE_RULES
from mfc_analytics.models.action import ActionProblemType, ActionStatus, ManagerAction
from mfc_analytics.models.call import (
    Call,
    CallMetadata,
    CallOutcome,
    CallTopic,
    LoadRegime,
    ManagerStatus,
    SpeakerRole,
    Utterance,
)
from mfc_analytics.models.cms import CMSInterval


app = FastAPI(
    title="МФЦ РУДН — Интеллектуальная аналитика звонков",
    description="Система речевой аналитики, классификации обращений и контроля качества контакт-центра",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальное хранилище данных (в памяти для быстродействия)
generator = MFCDataGenerator(random_seed=42)
pipeline = MFCAnalyticsPipeline()

raw_calls = generator.generate_curated_calls()
PROCESSED_CALLS: Dict[str, Call] = {}
for c in raw_calls:
    analyzed = pipeline.analyze_call(c)
    PROCESSED_CALLS[analyzed.metadata.call_id] = analyzed

CMS_INTERVALS: List[CMSInterval] = generator.generate_cms_intervals()
SYSTEMIC_SUMMARY: Dict = pipeline.systemic_detector.analyze_batch(list(PROCESSED_CALLS.values()))
ACTIONS: Dict[str, ManagerAction] = {
    a["action_id"]: ManagerAction(**a) for a in SYSTEMIC_SUMMARY.get("suggested_actions", [])
}


# Запросы для обновления статуса
class UpdateStatusRequest(BaseModel):
    manager_status: ManagerStatus
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

    # Сортировка: сначала критические ошибки, затем по убыванию времени
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
    return call.model_dump()


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


@app.get("/api/cms/intervals")
def get_cms_intervals(limit: int = 50, peak_only: bool = False):
    """Данные интервалов Avaya CMS для построения графиков нагрузки."""
    intervals = CMS_INTERVALS
    if peak_only:
        intervals = [i for i in intervals if i.load_regime == LoadRegime.HIGH]
    return [i.model_dump() for i in intervals[:limit]]


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


@app.get("/api/rules")
def get_rules():
    """Справочник действующих эталонных правил РУДН."""
    return [r.model_dump() for r in REFERENCE_RULES]


@app.post("/api/analyze-custom")
def analyze_custom(req: CustomAnalysisRequest):
    """Интерактивный анализ произвольного диалога в реальном времени."""
    now = datetime.now()
    utterances = [
        Utterance(id=1, speaker=SpeakerRole.OPERATOR, start_ms=0, end_ms=2500, text="Добрый день! Контакт-центр МФЦ РУДН, слушаю вас."),
        Utterance(id=2, speaker=SpeakerRole.APPLICANT, start_ms=2800, end_ms=8000, text=req.caller_text),
        Utterance(id=3, speaker=SpeakerRole.OPERATOR, start_ms=8500, end_ms=15000, text=req.operator_text),
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
