# -*- coding: utf-8 -*-
"""末日地堡生存 —— 核心引擎的可测试纯逻辑，验证资源守恒、危机决策、结局判定。

注意：测试使用独立内存级 Session，需清空表。为隔离，这里用 engine 建临时表。
"""
import pytest
from sqlalchemy.orm import Session

from app.core.database import Base, engine, SessionLocal
from app.core.config import INITIAL_RESOURCES, SURVIVAL_TARGET_DAY
from app.models import GameSession, Resident, Facility
from app.services.engine import (
    BunkerEngine,
    BunkerEngineError,
    CRISIS_POOL,
    FACILITY_ZH,
    FOOD,
    OXY,
    POWER,
    WATER,
)


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    s = SessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


def make_session(db, residents=3, resources=None):
    gs = GameSession(
        name="测试",
        day=1,
        target_day=SURVIVAL_TARGET_DAY,
        status="running",
        resources=resources or dict(INITIAL_RESOURCES),
        survivors=residents,
        score=0,
    )
    db.add(gs)
    db.flush()
    for i in range(residents):
        db.add(Resident(session_id=gs.id, name=f"人{i}", job="general", health=90, morale=80, alive=1, joined_day=1))
    for cat in ("power", "farm", "water", "oxygen"):
        db.add(Facility(session_id=gs.id, name=FACILITY_ZH[cat], category=cat, level=1, status="active", built_day=1))
    db.commit()
    db.refresh(gs)
    return gs


class FixedRand:
    """固定值随机 —— 每个 .random() 返回 0.9（不触发危机，因 0.9 > 0.45）。"""

    def random(self):
        return 0.9

    def choice(self, seq):
        return seq[0]


def test_advance_increments_day(db):
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    eng.advance_day()
    assert gs.day == 2


def test_resources_change_with_population(db):
    """资源应有产出-消耗的净变化（守恒循环运行）。"""
    gs = make_session(db, residents=3)
    before = dict(gs.resources)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    eng.advance_day()
    after = gs.resources
    # 至少一个资源发生变化
    assert any(abs(after[k] - before[k]) > 0.01 for k in ("food", "water", "power", "oxygen"))


def test_build_deducts_cost(db):
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    food_before = gs.resources[FOOD]
    eng.build_facility("med")
    assert gs.resources[FOOD] < food_before
    assert any(f.category == "med" for f in gs.facilities)


def test_build_fails_when_poor(db):
    gs = make_session(db)
    gs.resources = {FOOD: 1, WATER: 1, POWER: 1, OXY: 1}
    eng = BunkerEngine(db, gs, rand=FixedRand())
    with pytest.raises(BunkerEngineError):
        eng.build_facility("farm")


def test_upgrade_increases_level(db):
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    fac = [f for f in gs.facilities if f.category == "farm"][0]
    eng.upgrade_facility(fac.id)
    assert fac.level == 2


def test_crisis_applies_resource_effects(db):
    """选择翻倍食物选项应减食物。"""
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    # 直接调用危机池里第一个事件的效果
    event = CRISIS_POOL[0]
    food_before = gs.resources[FOOD]
    eng._apply_crisis(event)  # 仅生成待决策
    choice = event["choices"][0]
    eff = choice["effects"].get("resources", {}).get(FOOD, 0)
    eng.resolve_crisis(event["key"], choice["key"])
    assert gs.resources[FOOD] <= food_before + eff + 1


def test_job_assignment_changes_resident(db):
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    r = gs.residents[0]
    eng.set_job(r.id, "farmer")
    assert r.job == "farmer"


def test_win_at_target_day(db):
    gs = make_session(db, resources={FOOD: 9999, WATER: 9999, POWER: 9999, OXY: 9999})
    gs.day = SURVIVAL_TARGET_DAY  # 目标天数
    eng = BunkerEngine(db, gs, rand=FixedRand())
    eng._check_end()
    assert gs.status == "win"


def test_population_zero_ends_game(db):
    gs = make_session(db)
    for r in gs.residents:
        r.alive = 0
    gs.survivors = 0
    eng = BunkerEngine(db, gs, rand=FixedRand())
    eng._check_end()
    assert gs.status == "over"


def test_advance_rejected_after_game_end(db):
    gs = make_session(db)
    gs.status = "over"
    eng = BunkerEngine(db, gs, rand=FixedRand())
    with pytest.raises(BunkerEngineError):
        eng.advance_day()


def test_morale_recovery_toward_75(db):
    gs = make_session(db)
    for r in gs.residents:
        r.morale = 40
    gs.resources = {FOOD: 999, WATER: 999, POWER: 999, OXY: 999}
    eng = BunkerEngine(db, gs, rand=FixedRand())
    eng._apply_health_morale()
    assert all(r.morale > 40 for r in gs.residents)


# ---- 目标归属校验：防止跨档案数据污染 ----

def test_foreign_archive_target_rejected(db):
    """提交其他档案的居民编号：报错且本档案居民/资源均不受影响。"""
    gs = make_session(db)
    other = make_session(db)
    foreign_id = other.residents[0].id

    eng = BunkerEngine(db, gs, rand=FixedRand())
    health_before = [r.health for r in gs.residents]
    food_before = gs.resources[FOOD]
    # 疫病·隔离：扣食物且对目标造成健康 -5
    with pytest.raises(BunkerEngineError):
        eng.resolve_crisis("sick", "quarantine", target_id=foreign_id)
    # 本档案无人受到伤害
    assert [r.health for r in gs.residents] == health_before
    # 目标校验在资源结算之前，资源也不应被扣减
    assert gs.resources[FOOD] == food_before


def test_nonexistent_target_rejected(db):
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    missing_id = max(r.id for r in gs.residents) + 9999
    health_before = [r.health for r in gs.residents]
    with pytest.raises(BunkerEngineError):
        eng.resolve_crisis("sick", "quarantine", target_id=missing_id)
    assert [r.health for r in gs.residents] == health_before


def test_dead_target_rejected(db):
    gs = make_session(db)
    dead = gs.residents[0]
    dead.alive = 0
    eng = BunkerEngine(db, gs, rand=FixedRand())
    with pytest.raises(BunkerEngineError):
        eng.resolve_crisis("sick", "quarantine", target_id=dead.id)


def test_valid_target_only_affects_that_resident(db):
    """有效本档案目标：健康效果只作用于其本人，不波及其他居民。"""
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    target = gs.residents[1]
    others = [r for r in gs.residents if r.id != target.id]
    others_before = [r.health for r in others]
    # 盗匪·武装抵抗：健康 -8
    eng.resolve_crisis("raid", "defend", target_id=target.id)
    assert target.health == 82  # 90 - 8
    assert [r.health for r in others] == others_before


def test_no_target_applies_to_all_alive(db):
    """未提供目标时，士气类全体效果仍按原语义作用于全体存活者。"""
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    eng.resolve_crisis("mutiny", "double_ration")  # 士气 +20
    assert all(r.morale == 100 for r in gs.residents if r.alive)


# ---- 危机目标语义：全体/单人由事件定义决定，前端回传不得改变结算范围 ----

def test_all_event_ignores_echoed_target(db):
    """全体事件：即使客户端无条件回传 target_id，士气效果仍作用于全体存活者。

    回归场景：前端曾把触发时随机选出的 target_id 无条件回传，导致
    内讧「加倍发放食物」的全体士气 +20 只作用于一名随机居民。
    """
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    echoed = gs.residents[0].id
    eng.resolve_crisis("mutiny", "double_ration", target_id=echoed)  # 士气 +20
    assert all(r.morale == 100 for r in gs.residents if r.alive)


def test_all_event_negative_morale_hits_everyone(db):
    """全体事件的负面士气效果同样作用于全体（暴雪·集中避寒 士气 -10）。"""
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    eng.resolve_crisis("blizzard", "huddle", target_id=gs.residents[0].id)
    assert all(r.morale == 70 for r in gs.residents if r.alive)


def test_single_event_without_target_falls_back_to_random(db):
    """单人事件缺省目标时随机选取一名存活者，且仅其一人受影响。"""
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())  # choice -> 序列首个
    eng.resolve_crisis("raid", "defend")  # 健康 -8
    hurt = [r for r in gs.residents if r.health == 82]
    assert len(hurt) == 1
    assert hurt[0] is gs.residents[0]


def test_crisis_payload_target_semantics(db):
    """危机载荷：全体事件不携带目标，单人事件携带受影响者与 target_mode。"""
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    mutiny = next(e for e in CRISIS_POOL if e["key"] == "mutiny")
    payload = eng._apply_crisis(mutiny)
    assert payload["target_mode"] == "all"
    assert payload["target_id"] is None
    assert payload["target_name"] is None
    sick = next(e for e in CRISIS_POOL if e["key"] == "sick")
    payload = eng._apply_crisis(sick)
    assert payload["target_mode"] == "single"
    assert payload["target_id"] is not None
    assert payload["target_name"] is not None


def test_resolve_detail_reflects_settlement_scope(db):
    """结算描述（即日志 detail）如实反映作用范围：全体 vs 具名居民。"""
    gs = make_session(db)
    eng = BunkerEngine(db, gs, rand=FixedRand())
    detail = eng.resolve_crisis("mutiny", "double_ration")
    assert "全体士气 +20" in detail
    target = gs.residents[1]
    detail = eng.resolve_crisis("raid", "defend", target_id=target.id)
    assert f"{target.name}健康 -8" in detail


# ---- 结算边界：已结束档案拒绝一切状态变更 ----

def test_actions_rejected_after_game_end(db):
    gs = make_session(db)
    gs.status = "over"
    eng = BunkerEngine(db, gs, rand=FixedRand())
    rid = gs.residents[0].id
    fid = gs.facilities[0].id
    with pytest.raises(BunkerEngineError):
        eng.resolve_crisis("sick", "quarantine", target_id=rid)
    with pytest.raises(BunkerEngineError):
        eng.build_facility("med")
    with pytest.raises(BunkerEngineError):
        eng.upgrade_facility(fid)
    with pytest.raises(BunkerEngineError):
        eng.set_job(rid, "farmer")