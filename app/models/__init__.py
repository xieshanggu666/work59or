# -*- coding: utf-8 -*-
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    DateTime,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..core.database import Base


class GameSession(Base):
    __tablename__ = "game_sessions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False, default="末日地堡档案")
    day = Column(Integer, nullable=False, default=1)
    target_day = Column(Integer, nullable=False, default=120)
    status = Column(String(16), nullable=False, default="running")  # running/over/win
    resources = Column(JSON, nullable=False, default=dict)  # {food,water,power,oxygen}
    survivors = Column(Integer, nullable=False, default=0)
    outcome = Column(JSON, nullable=True)  # 结局详情
    score = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    residents = relationship("Resident", back_populates="session", cascade="all, delete-orphan")
    facilities = relationship("Facility", back_populates="session", cascade="all, delete-orphan")
    logs = relationship("EventLog", back_populates="session", cascade="all, delete-orphan")


class Resident(Base):
    __tablename__ = "residents"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("game_sessions.id"), nullable=False)
    name = Column(String(32), nullable=False)
    job = Column(String(32), nullable=False)  # 岗位: farmer/gardener/medic/engineer/general...
    health = Column(Float, nullable=False, default=100.0)  # 0-100
    morale = Column(Float, nullable=False, default=80.0)  # 0-100
    alive = Column(Integer, nullable=False, default=1)
    joined_day = Column(Integer, nullable=False, default=1)

    session = relationship("GameSession", back_populates="residents")


class Facility(Base):
    __tablename__ = "facilities"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("game_sessions.id"), nullable=False)
    name = Column(String(32), nullable=False)
    # 类别: farm(产食物), water(产水), power(产电), oxygen(产氧), storage(仓库), med(医疗)
    category = Column(String(16), nullable=False)
    level = Column(Integer, nullable=False, default=1)
    status = Column(String(16), nullable=False, default="active")  # active/offline
    built_day = Column(Integer, nullable=False, default=1)

    session = relationship("GameSession", back_populates="facilities")


class EventLog(Base):
    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("game_sessions.id"), nullable=False)
    day = Column(Integer, nullable=False)
    event_type = Column(String(32), nullable=False)  # crisis/update/system
    title = Column(String(64), nullable=False)
    detail = Column(Text, nullable=False, default="")
    decision = Column(String(64), nullable=True)

    session = relationship("GameSession", back_populates="logs")