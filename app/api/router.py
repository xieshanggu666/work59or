# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.config import INITIAL_RESOURCES, SURVIVAL_TARGET_DAY
from ..models import GameSession, Resident, Facility
from ..services.engine import (
    BunkerEngine,
    BunkerEngineError,
    RESOURCE_KEYS,
    FACILITY_OUTPUT,
    FACILITY_COST,
    FACILITY_ZH,
    JOB_EFFICIENCY,
)
from ..schemas import (
    SessionCreate,
    SessionBrief,
    SessionDetail,
    AdvanceResult,
    CrisisChoice,
    JobAssign,
    BuildRequest,
    BuildableInfo,
    EngineConfig,
    Message,
)

router = APIRouter(prefix="/api")


# ---- 会话 ----
@router.get("/sessions")
def list_sessions(db: Session = Depends(get_db)):
    rows = (
        db.query(GameSession)
        .order_by(GameSession.created_at.desc())
        .all()
    )
    return [SessionBrief.model_validate(r) for r in rows]


@router.post("/sessions", response_model=SessionDetail, status_code=201)
def create_session(body: SessionCreate, db: Session = Depends(get_db)):
    gs = GameSession(
        name=body.name,
        day=1,
        target_day=SURVIVAL_TARGET_DAY,
        status="running",
        resources=dict(INITIAL_RESOURCES),
        survivors=3,
        score=0,
    )
    db.add(gs)
    db.flush()
    # 初始三名幸存者
    for name, job in (("林粤", "engineer"), ("夏岚", "farmer"), ("老周", "general")):
        db.add(
            Resident(
                session_id=gs.id,
                name=name,
                job=job,
                health=90.0,
                morale=80.0,
                alive=1,
                joined_day=1,
            )
        )
    # 初始设施
    for cat in ("power", "farm", "water", "oxygen"):
        db.add(
            Facility(
                session_id=gs.id,
                name=FACILITY_ZH[cat],
                category=cat,
                level=1,
                status="active",
                built_day=1,
            )
        )
    db.commit()
    db.refresh(gs)
    return get_session_detail(gs, db)


@router.get("/sessions/{sid}", response_model=SessionDetail)
def get_session(sid: int, db: Session = Depends(get_db)):
    gs = db.get(GameSession, sid)
    if not gs:
        raise HTTPException(404, "档案不存在")
    return get_session_detail(gs, db)


def _serialize_resident(r):
    return {
        "id": r.id,
        "name": r.name,
        "job": r.job,
        "job_zh": JOB_ZH.get(r.job, r.job),
        "health": r.health,
        "morale": r.morale,
        "alive": r.alive,
        "joined_day": r.joined_day,
    }


def get_session_detail(gs, db):
    residents = [
        _serialize_resident(r)
        for r in gs.residents
    ]
    facilities = [
        {
            "id": f.id,
            "name": f.name,
            "category": f.category,
            "level": f.level,
            "status": f.status,
            "built_day": f.built_day,
        }
        for f in gs.facilities
    ]
    logs = [
        {
            "id": l.id,
            "day": l.day,
            "event_type": l.event_type,
            "title": l.title,
            "detail": l.detail,
            "decision": l.decision,
        }
        for l in gs.logs
    ]
    return SessionDetail(
        id=gs.id,
        name=gs.name,
        day=gs.day,
        target_day=gs.target_day,
        status=gs.status,
        resources={k: gs.resources.get(k, 0) for k in RESOURCE_KEYS},
        survivors=gs.survivors,
        score=gs.score,
        outcome=gs.outcome,
        residents=residents,
        facilities=facilities,
        logs=logs,
    )


# ---- 游戏动作 ----
@router.post("/sessions/{sid}/advance", response_model=AdvanceResult)
def advance(sid: int, db: Session = Depends(get_db)):
    gs = db.get(GameSession, sid)
    if not gs:
        raise HTTPException(404, "档案不存在")
    eng = BunkerEngine(db, gs)
    try:
        crisis = eng.advance_day()
        db.commit()
        db.refresh(gs)
    except BunkerEngineError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    # crisis 需带 target 显示名
    if crisis and crisis.get("target_id"):
        tgt = db.get(Resident, crisis["target_id"])
        if tgt:
            crisis["target_name"] = tgt.name
    return AdvanceResult(session=get_session_detail(gs, db), crisis=crisis)


@router.post("/sessions/{sid}/resolve", response_model=SessionDetail)
def resolve_crisis(sid: int, body: CrisisChoice, db: Session = Depends(get_db)):
    gs = db.get(GameSession, sid)
    if not gs:
        raise HTTPException(404, "档案不存在")
    eng = BunkerEngine(db, gs)
    try:
        eng.resolve_crisis(body.event_key, body.choice_key, body.target_id)
        db.commit()
        db.refresh(gs)
    except BunkerEngineError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    return get_session_detail(gs, db)


@router.post("/sessions/{sid}/build", response_model=SessionDetail)
def build(sid: int, body: BuildRequest, db: Session = Depends(get_db)):
    gs = db.get(GameSession, sid)
    if not gs:
        raise HTTPException(404, "档案不存在")
    if body.category not in FACILITY_OUTPUT:
        raise HTTPException(400, "未知设施类别")
    eng = BunkerEngine(db, gs)
    try:
        eng.build_facility(body.category)
        db.commit()
        db.refresh(gs)
    except BunkerEngineError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    return get_session_detail(gs, db)


@router.post("/sessions/{sid}/upgrade/{fid}", response_model=SessionDetail)
def upgrade(sid: int, fid: int, db: Session = Depends(get_db)):
    gs = db.get(GameSession, sid)
    if not gs:
        raise HTTPException(404, "档案不存在")
    eng = BunkerEngine(db, gs)
    try:
        eng.upgrade_facility(fid)
        db.commit()
        db.refresh(gs)
    except BunkerEngineError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    return get_session_detail(gs, db)


@router.post("/sessions/{sid}/resident/{rid}/job", response_model=SessionDetail)
def set_job(sid: int, rid: int, body: JobAssign, db: Session = Depends(get_db)):
    gs = db.get(GameSession, sid)
    if not gs:
        raise HTTPException(404, "档案不存在")
    eng = BunkerEngine(db, gs)
    try:
        eng.set_job(rid, body.job)
        db.commit()
        db.refresh(gs)
    except BunkerEngineError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    return get_session_detail(gs, db)


@router.delete("/sessions/{sid}", response_model=Message)
def delete_session(sid: int, db: Session = Depends(get_db)):
    gs = db.get(GameSession, sid)
    if not gs:
        raise HTTPException(404, "档案不存在")
    db.delete(gs)
    db.commit()
    return Message(detail="已删除")


# ---- 配置信息 ----
@router.get("/config", response_model=EngineConfig)
def get_config():
    return EngineConfig(
        resources=dict(INITIAL_RESOURCES),
        facility_costs=FACILITY_COST,
        facility_names=FACILITY_ZH,
        job_options=list(JOB_EFFICIENCY.keys()),
        status="running",
    )


@router.get("/buildings", response_model=list)
def list_buildable():
    return [
        BuildableInfo(
            category=k,
            name=FACILITY_ZH[k],
            cost=FACILITY_COST[1],
            level_scale=1.6,
        )
        for k in ("farm", "water", "power", "oxygen", "med", "storage")
    ]


JOB_ZH = {"engineer": "工程师", "farmer": "农民", "general": "杂工"}