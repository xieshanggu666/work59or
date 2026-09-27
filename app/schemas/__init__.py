# -*- coding: utf-8 -*-
from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class SessionCreate(BaseModel):
    name: str = "末日地堡档案"


class SessionBrief(BaseModel):
    id: int
    name: str
    day: int
    target_day: int
    status: str
    survivors: int
    score: int

    class Config:
        from_attributes = True


class ResidentOut(BaseModel):
    id: int
    name: str
    job: str
    job_zh: Optional[str] = None
    health: float
    morale: float
    alive: int
    joined_day: int

    class Config:
        from_attributes = True


class FacilityOut(BaseModel):
    id: int
    name: str
    category: str
    level: int
    status: str
    built_day: int

    class Config:
        from_attributes = True


class LogOut(BaseModel):
    id: int
    day: int
    event_type: str
    title: str
    detail: str
    decision: Optional[str] = None

    class Config:
        from_attributes = True


class SessionDetail(BaseModel):
    id: int
    name: str
    day: int
    target_day: int
    status: str
    resources: Dict[str, float]
    survivors: int
    score: int
    outcome: Optional[Dict[str, Any]] = None
    residents: List[ResidentOut] = []
    facilities: List[FacilityOut] = []
    logs: List[LogOut] = []


class AdvanceResult(BaseModel):
    session: SessionDetail
    crisis: Optional[Dict[str, Any]] = None


class CrisisChoice(BaseModel):
    event_key: str
    choice_key: str
    target_id: Optional[int] = None


class JobAssign(BaseModel):
    job: str


class BuildRequest(BaseModel):
    category: str


class BuildableInfo(BaseModel):
    category: str
    name: str
    cost: Dict[str, float]
    level_scale: float


class EngineConfig(BaseModel):
    resources: Dict[str, float]
    facility_costs: Dict[int, Dict[str, float]]
    facility_names: Dict[str, str]
    job_options: List[str]
    status: str


class Message(BaseModel):
    detail: str = "ok"