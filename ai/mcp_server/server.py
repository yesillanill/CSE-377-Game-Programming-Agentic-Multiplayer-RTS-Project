"""Custom RTS MCP server ("RTS Strategic Commander").

Tools (all read-only; none of them changes game state):
    get_player_resources   live state  - own wood/food/gold + population
    get_army_status        live state  - own units and buildings
    get_visible_enemies    live state  - enemies visible RIGHT NOW (fog-of-war filtered by Unity)
    get_technology_status  live state  - own upgrade tiers, research in progress, next tier costs
    get_recent_events      live state  - recent safe events (losses, attacks, completions)
    estimate_plan_cost     deterministic calculator over the game catalog
    search_game_knowledge  RAG over ai/rag/knowledge (units, technologies, rules)

The server is created per request by the AI gateway with `build_server(session, index)`: the authenticated
session is captured in a closure, so no tool takes a player / match identifier.

Standalone (MCP Inspector / manual testing):
    cd ai
    python -m mcp_server.server --snapshot mcp_server/demo_snapshot.json          # stdio transport
    npx @modelcontextprotocol/inspector python -m mcp_server.server --snapshot mcp_server/demo_snapshot.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from mcp_server import catalog
from mcp_server.session import SafeSnapshot, SessionContext
from rag.retriever import KnowledgeIndex

SERVER_NAME = "RTS Strategic Commander"
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

# Scope / allow-list: the agent may only call these. Action proposals are NOT tools; they are returned in the
# ActionPlan and executed by Unity after player approval and GameActionValidator checks.
LIVE_STATE_TOOLS = ("get_player_resources", "get_army_status", "get_visible_enemies", "get_technology_status", "get_recent_events")
CALCULATOR_TOOLS = ("estimate_plan_cost",)
KNOWLEDGE_TOOLS = ("search_game_knowledge",)
ALL_TOOLS = LIVE_STATE_TOOLS + CALCULATOR_TOOLS + KNOWLEDGE_TOOLS


class PlanItem(BaseModel):
    kind: Literal["unit", "building", "tech"] = Field(description="unit, building or tech (tech = next tier of an upgrade line)")
    id: str = Field(min_length=1, max_length=40, description="Unit type (Spearman), building type (Barracks) or tech line (weapon/armor/wall)")
    count: int = Field(default=1, ge=1, le=20)


def _tech_levels(s: SafeSnapshot) -> dict[str, int]:
    return {"weapon": s.tech.weapon_level, "armor": s.tech.armor_level, "wall": s.tech.wall_level}


def _staleness(ctx: SessionContext) -> dict:
    return {"snapshot_age_s": round(ctx.age_seconds, 1), "stale": ctx.is_stale}


def build_server(ctx: SessionContext, index: KnowledgeIndex) -> MCPServer:
    """Creates an MCP server whose tools read only the given session's safe snapshot."""

    mcp = MCPServer(
        SERVER_NAME,
        instructions="Read-only tools over the current player's fog-of-war filtered RTS match state and game rulebook.",
    )
    snap = ctx.snapshot

    def names(kind: str, canonical: str) -> str:
        return catalog.display_name(kind, canonical, snap.game_mode)

    def free_population() -> int:
        p = snap.population
        return max(0, p.max - p.current - p.queued)

    @mcp.tool(annotations=READ_ONLY, structured_output=True)
    def get_player_resources() -> dict[str, Any]:
        """Return the current player's resources (wood, food, gold), population (current/max/queued) and how many
        of each unit type could be paid for right now."""
        p = snap.population
        res = snap.resources.model_dump()
        affordable = {}
        for unit in catalog.UNIT_TYPES:
            cost = catalog.cost_of("unit", unit)
            limits = [res[k] // cost[k] for k in cost if cost[k] > 0]
            affordable[unit] = min([free_population()] + limits)
        return {
            "resources": res,
            "population": {"current": p.current, "max": p.max, "queued_in_training": p.queued, "free": free_population()},
            "max_affordable_units_now": affordable,
            **_staleness(ctx),
        }

    @mcp.tool(annotations=READ_ONLY, structured_output=True)
    def get_army_status(include_workers: bool = True) -> dict[str, Any]:
        """Return the current player's own units grouped by type and map region, plus own buildings."""
        units = [u.model_dump() for u in snap.own_units if include_workers or u.type != "Worker"]
        military = sum(u.count for u in snap.own_units if u.type != "Worker")
        workers = sum(u.count for u in snap.own_units if u.type == "Worker")
        health_centers = sum(b.count - b.under_construction for b in snap.own_buildings if b.type == "HealthCenter")
        # Repair / demolish (one worker per job): deterministic summary so the model never guesses costs
        damaged = [{"type": b.type, "display_name": names("building", b.type), "damaged": b.damaged,
                    "lowest_hp_pct": b.min_hp_pct, "repair_cost": b.repair_cost.model_dump()}
                   for b in snap.own_buildings if b.damaged > 0]
        in_progress = [{"type": b.type, "repairing": b.repairing, "demolishing": b.demolishing}
                       for b in snap.own_buildings if b.repairing or b.demolishing]
        # Deterministic matchup of own unit types against currently visible enemy types (rulebook counters)
        visible_types = {e.type for e in snap.visible_enemies}
        matchups = {}
        for u in {g.type for g in snap.own_units if g.type != "Worker"}:
            rec = catalog.unit_record(u)
            strong = sorted(visible_types & set(rec.get("strengths", [])))
            weak = sorted(visible_types & set(rec.get("weaknesses", [])))
            matchups[u] = {"strong_against_visible": strong, "weak_against_visible": weak}
        return {
            "game_mode": snap.game_mode,
            "units": units,
            "military_total": military,
            "worker_total": workers,
            # Health Center: units below 30% HP go there automatically when idle and heal to full in a few seconds
            "wounded_total": sum(u.wounded for u in snap.own_units),
            "healing_total": sum(u.healing for u in snap.own_units),
            "health_centers_ready": max(0, health_centers),
            "damaged_buildings": damaged,
            "maintenance_in_progress": in_progress,
            "maintenance_rules": "REPAIR: one worker, pays repair_cost, restores full HP. DEMOLISH: one worker, refunds 50% "
                                 "of the build cost, never the Town Center. Burning buildings lose HP (not below 25%) and must "
                                 "be extinguished before repair.",
            "matchups_vs_visible_enemies": matchups,
            "buildings": [b.model_dump() for b in snap.own_buildings],
            "base_region": snap.base_region,
            **_staleness(ctx),
        }

    @mcp.tool(annotations=READ_ONLY, structured_output=True)
    def get_visible_enemies() -> dict[str, Any]:
        """Return ONLY enemy units and buildings that are visible to the player right now (fog-of-war filtered).
        Hidden enemies, enemy resources and enemy technology are never available."""
        units = []
        for e in snap.visible_enemies:
            row = e.model_dump()
            # Deterministic counter lookup from the rulebook (the unit type that deals 2x damage to this one)
            row["countered_by"] = next((u for u in catalog.UNIT_TYPES
                                        if e.type in catalog.unit_record(u).get("strengths", [])), None)
            units.append(row)
        return {
            "visible_units": units,
            "visible_buildings": [e.model_dump() for e in snap.visible_enemy_buildings],
            "visible_unit_total": sum(e.count for e in snap.visible_enemies),
            "note": "Fog of war: only currently visible enemies are listed. Anything else is unknown.",
            **_staleness(ctx),
        }

    @mcp.tool(annotations=READ_ONLY, structured_output=True)
    def get_technology_status() -> dict[str, Any]:
        """Return the player's upgrade tiers (weapon/armor/wall), research in progress and the next tier of each line."""
        levels = _tech_levels(snap)
        next_tiers = {}
        for line, level in levels.items():
            rec = catalog.tech_record(line, level + 1)
            next_tiers[line] = None if rec is None else {
                "tier": rec["level"],
                "name": rec["scifi_name"] if snap.game_mode == "SciFi" else rec["display_name"],
                "cost": rec["cost"], "effect": rec["effect"], "research_time_s": rec["research_time_s"],
            }
        has_blacksmith = any(b.type == "Blacksmith" and b.count > b.under_construction for b in snap.own_buildings)
        return {
            "levels": levels,
            "max_levels": {line: catalog.max_level(line) for line in catalog.TECH_LINES},
            "researching": snap.tech.researching or None,
            "research_progress": snap.tech.research_progress,
            "next_tiers": next_tiers,
            "research_building_ready": has_blacksmith,
            "research_building": names("building", "Blacksmith"),
            **_staleness(ctx),
        }

    @mcp.tool(annotations=READ_ONLY, structured_output=True)
    def get_recent_events(last_seconds: Annotated[int, Field(ge=5, le=600)] = 60) -> dict[str, Any]:
        """Return safe recent events of the player's own match (attacks, losses, completions) from the last N seconds."""
        events = [e.model_dump() for e in snap.recent_events if e.seconds_ago <= last_seconds]
        return {"last_seconds": last_seconds, "events": events, "count": len(events), **_staleness(ctx)}

    @mcp.tool(annotations=READ_ONLY, structured_output=True)
    def estimate_plan_cost(items: Annotated[list[PlanItem], Field(min_length=1, max_length=8)]) -> dict[str, Any]:
        """Calculate the total cost of a production plan and whether the player can afford it now.
        Example items: [{"kind": "unit", "id": "Spearman", "count": 5}, {"kind": "tech", "id": "weapon"}]"""
        total = {"wood": 0, "food": 0, "gold": 0}
        lines = []
        pop_needed = 0
        for item in items:
            if item.kind == "unit":
                ident = catalog.canonical_unit(item.id)
            elif item.kind == "building":
                ident = catalog.canonical_building(item.id)
            else:
                ident = item.id.strip().lower() if item.id.strip().lower() in catalog.TECH_LINES else None
            if ident is None:
                raise ToolError(f"Unknown {item.kind} id '{item.id}'.")
            try:
                cost = catalog.cost_of(item.kind, ident, item.count, _tech_levels(snap))
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            if item.kind == "unit":
                pop_needed += item.count
            for k in total:
                total[k] += cost[k]
            lines.append({"kind": item.kind, "id": ident, "count": item.count if item.kind != "tech" else 1, "cost": cost})
        available = snap.resources.model_dump()
        shortage = {k: total[k] - available[k] for k in total if total[k] > available[k]}
        p = snap.population
        free_pop = max(0, p.max - p.current - p.queued)
        return {
            "items": lines,
            "total": total,
            "available": available,
            "affordable": not shortage,
            "shortage": shortage,
            "population_needed": pop_needed,
            "population_free": free_pop,
            "population_ok": pop_needed <= free_pop,
        }

    @mcp.tool(annotations=READ_ONLY, structured_output=True)
    def search_game_knowledge(
        query: Annotated[str, Field(min_length=2, max_length=200)],
        top_k: Annotated[int, Field(ge=1, le=5)] = 3,
    ) -> dict[str, Any]:
        """Search the game rulebook (units, counters, costs, buildings, technologies, rules). Returns chunks with source ids."""
        hits = index.search(query, top_k)
        return {"query": query, "results": hits, "count": len(hits)}

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RTS MCP server over stdio with a fixed snapshot.")
    parser.add_argument("--snapshot", default=str(Path(__file__).with_name("demo_snapshot.json")))
    args = parser.parse_args()
    snapshot = SafeSnapshot.model_validate(json.loads(Path(args.snapshot).read_text(encoding="utf-8")))
    server = build_server(SessionContext("stdio-demo", snapshot), KnowledgeIndex.load())
    server.run("stdio")


if __name__ == "__main__":
    main()
