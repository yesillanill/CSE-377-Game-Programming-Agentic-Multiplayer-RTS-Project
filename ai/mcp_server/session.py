"""Safe, visibility-filtered match snapshot sent by Unity and the per-session store the MCP tools read from.

Security notes
- Unity builds the snapshot AFTER fog-of-war filtering (AiSnapshotBuilder.cs): it only contains the local
  player's own state and enemies that are visible right now. There is no field for opponent resources,
  opponent technology or hidden enemy positions, and unknown fields are rejected (extra="forbid").
- The session (match + player) is bound by the gateway from the X-RTS-Session header. MCP tools receive the
  bound SessionContext through a closure; no tool accepts a player_id / match_id argument, so the model cannot
  switch identities by changing text arguments.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

UnitName = Literal["Worker", "Spearman", "Archer", "Cavalry"]
BuildingName = Literal["TownCenter", "House", "Barracks", "Stable", "Blacksmith", "Mine", "DefenseTower", "Wall", "Farm"]
Region = Literal["NorthWest", "North", "NorthEast", "West", "Center", "East", "SouthWest", "South", "SouthEast", "Unknown"]

MAX_LIST = 64


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=80)


class Resources(_Strict):
    wood: int = Field(ge=0, le=1_000_000)
    food: int = Field(ge=0, le=1_000_000)
    gold: int = Field(ge=0, le=1_000_000)


class Population(_Strict):
    current: int = Field(ge=0, le=10_000)
    max: int = Field(ge=0, le=10_000)
    queued: int = Field(default=0, ge=0, le=10_000)


class UnitGroup(_Strict):
    type: UnitName
    display_name: str = ""
    count: int = Field(ge=0, le=10_000)
    region: Region = "Unknown"
    idle: int = Field(default=0, ge=0, le=10_000)


class BuildingGroup(_Strict):
    type: BuildingName
    display_name: str = ""
    count: int = Field(ge=0, le=10_000)
    under_construction: int = Field(default=0, ge=0, le=10_000)
    queued_units: int = Field(default=0, ge=0, le=10_000)
    region: Region = "Unknown"


class EnemyUnitGroup(_Strict):
    type: UnitName
    display_name: str = ""
    count: int = Field(ge=0, le=10_000)
    region: Region = "Unknown"


class EnemyBuildingGroup(_Strict):
    type: BuildingName
    display_name: str = ""
    count: int = Field(ge=0, le=10_000)
    region: Region = "Unknown"


class TechStatus(_Strict):
    weapon_level: int = Field(default=0, ge=0, le=3)
    armor_level: int = Field(default=0, ge=0, le=4)
    wall_level: int = Field(default=0, ge=0, le=2)
    researching: str = ""
    research_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    researched: list[str] = Field(default_factory=list, max_length=16)


class RecentEvent(_Strict):
    type: Literal["UNIT_LOST", "BUILDING_LOST", "UNDER_ATTACK", "ENEMY_SPOTTED", "UNIT_TRAINED",
                  "BUILDING_COMPLETED", "RESEARCH_COMPLETED", "ENEMY_UNIT_KILLED", "DISASTER"]
    detail: str = ""
    region: Region = "Unknown"
    seconds_ago: float = Field(ge=0, le=100_000)


class MapSize(_Strict):
    x: int = Field(ge=1, le=1024)
    y: int = Field(ge=1, le=1024)


class SafeSnapshot(_Strict):
    match_id: str = Field(min_length=1, max_length=64)
    game_mode: Literal["Medieval", "SciFi"] = "Medieval"
    ui_language: Literal["en", "tr"] = "en"
    game_time_seconds: float = Field(default=0.0, ge=0)
    map_size: MapSize = MapSize(x=64, y=64)
    base_region: Region = "Unknown"
    resources: Resources
    population: Population
    own_units: list[UnitGroup] = Field(default_factory=list, max_length=MAX_LIST)
    own_buildings: list[BuildingGroup] = Field(default_factory=list, max_length=MAX_LIST)
    visible_enemies: list[EnemyUnitGroup] = Field(default_factory=list, max_length=MAX_LIST)
    visible_enemy_buildings: list[EnemyBuildingGroup] = Field(default_factory=list, max_length=MAX_LIST)
    tech: TechStatus = TechStatus()
    recent_events: list[RecentEvent] = Field(default_factory=list, max_length=MAX_LIST)


@dataclass
class SessionContext:
    """Snapshot bound to one authenticated (match, player) session for the duration of one AI request."""

    session_id: str
    snapshot: SafeSnapshot
    received_at: float = field(default_factory=time.time)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.received_at

    @property
    def is_stale(self) -> bool:
        return self.age_seconds > 120.0


class SessionStore:
    """In-memory session table. A session token is bound to the first match_id it was used with."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionContext] = {}

    def bind(self, session_id: str, snapshot: SafeSnapshot) -> SessionContext:
        existing = self._sessions.get(session_id)
        if existing is not None and existing.snapshot.match_id != snapshot.match_id:
            raise PermissionError("Session token is bound to a different match.")
        ctx = SessionContext(session_id, snapshot)
        self._sessions[session_id] = ctx
        if len(self._sessions) > 256:  # drop the oldest sessions
            for key in sorted(self._sessions, key=lambda k: self._sessions[k].received_at)[:64]:
                self._sessions.pop(key, None)
        return ctx

    def get(self, session_id: str) -> SessionContext | None:
        return self._sessions.get(session_id)
