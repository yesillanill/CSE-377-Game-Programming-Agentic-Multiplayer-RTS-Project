# RTS game rules and strategy notes

Each `##` section is one retrievable knowledge chunk. The text after the heading id is indexed.
All numbers are this project's own game values (not Age of Empires data).

## rule_counter_triangle_v1
Counter triangle (both modes). Spearman beats Cavalry, Archer beats Spearman, Cavalry beats Archer.
A unit deals 2x damage to the unit type it counters. Sci-Fi names: Marine beats Tank, Sniper beats Marine,
Tank beats Sniper. To defend against cavalry/tanks train Spearmen/Marines; against spearmen use Archers;
against archers use Cavalry. Mixed armies are safer than a single unit type.

## rule_resources_v1
Resources are wood, food and gold. Workers gather from trees (wood), berry bushes and farms (food) and gold
deposits (gold), carry up to 10 units per trip and must return them to the Town Center (drop-off) before
the resource is added. More workers means faster income. Gold also comes from a Mine (+10 gold every 10 s
with one worker inside). Food also comes from farms (harvest returns 3x the food spent planting).

## rule_population_v1
Population: the Town Center gives 25 population capacity and every House (Habitat) adds +5.
Every unit costs 1 population, including units waiting in a training queue. If the population limit is
reached, training is rejected with "Population limit reached". Build Houses early to avoid blocking production.

## rule_building_prerequisites_v1
Building prerequisites: Workers build every building. Barracks (Armory) is required for Spearman and Archer;
Stable (Vehicle Bay) is required for Cavalry/Tank; Blacksmith (Tech Lab) is required for all upgrades;
the Town Center trains Workers. A building only works after construction is complete. Each production
building has a training queue of at most 5 units, and only one research can run at a time.

## rule_win_condition_v1
Win condition: destroy the opponent's Town Center (Command Center). If your Town Center is destroyed you lose.
If the opponent leaves the match, the remaining player wins. After the match both players may vote for a rematch.

## rule_fog_of_war_v1
Fog of war: a player only sees enemy units and buildings inside the vision radius of their own units and
buildings (units 5-7 cells, buildings about 8 cells). Hidden areas show nothing. Enemy resources, enemy
technology, enemy economy and enemy units under fog are never visible and cannot be known by the AI advisor.
Scouting with a fast unit (Cavalry) reveals more of the map.

## rule_combat_v1
Combat: units automatically attack visible enemies in range. Damage = attacker damage x weapon upgrade bonus
x 2 if the attacker counters the target, reduced by the target's armor upgrade (10-40%). Units die at 0 HP.
Ranged Archers (range 5) can hit melee units before they arrive. Workers are weak (3 damage, 40 HP).
Sci-Fi mode: every unit has 1.5x health and damage (Marine 120 HP, Engineer 60 HP).

## rule_towers_v1
Defense towers: Archer Tower (Medieval) and Rocket Turret (Sci-Fi) cost 100 gold and must be manned by one
soldier to fire (Archer in Medieval, Marine in Sci-Fi). Only Archers can damage an enemy Archer Tower, and
only Tanks can damage an enemy Rocket Turret. Towers are strong defensive anchors near the base or a gate.

## rule_health_center_v1
Healing: build a Health Center (Medieval) / Med Bay (Sci-Fi) for 100 wood and 50 gold. When one of your units
drops below 30% HP and has no active job (gathering, building, fire fighting, farming, mining, fighting, tower duty),
it walks to the nearest Health Center with room, stays inside for 5 seconds (hidden, cannot be attacked) and comes
out with full HP. Each Health Center holds 4 units at once. Units ordered elsewhere on the way cancel the trip.
Right-click your Health Center with wounded units selected to heal them at any HP. Keep it behind your army.

## rule_walls_v1
Walls: drawn segment by segment for 10 wood each. Walls block movement and protect workers and buildings.
The wall upgrade line (Stone/Brick, or Iron/Obsidian in Sci-Fi) increases the health of all walls.

## rule_upgrades_v1
Upgrades are researched at the Blacksmith (Tech Lab) one at a time. Weapons have 3 tiers (+15%, +30%, +50%
damage), Armor has 4 tiers (10%, 20%, 30%, 40% damage reduction), Walls have 2 tiers. Each tier requires the
previous tier of the same line. Upgrades affect soldiers only, not Workers. A cancelled research is refunded.

## rule_disasters_v1
Random disasters hit both sides independently, the computer opponent in single player included. The first one
comes 90-150 s into the match, then one every 100-200 s. Fire starts in a random completed building (never in walls; the
Town Center is picked less often when you have other buildings). Nearby buildings (within 4 cells) can catch fire at the
same time, and an unattended fire can jump to a nearby building every few seconds: up to 3 of your buildings can burn at
once. Spread your buildings out to limit it. While it burns the fire slowly burns about 10% of your stored wood, food and gold. Fire also damages the burning building: it
loses 1.5% of its maximum HP per second, but fire damage never takes a building below 25% HP (an unattended fire
burns longer and deals more damage). Repair the building after the fire. Plague lasts 20 seconds and kills 1-3 of
your units chosen at random (at least one unit always survives). Rain is only visual and has no gameplay effect.

## rule_disaster_response_v1
Fire response: all of your workers automatically stop working and spread over the burning buildings (at least one per
building) and fight the fire standing right next to the building; with at least one worker at a building its fire is out after 12 seconds, without workers it burns out five times slower and keeps
burning resources. Firefighting workers cannot take other orders until the fire is out. After the fire, repair the
damaged building with one worker (a burning building cannot be repaired). Plague response: there is no cure or
quarantine (the Health Center heals wounded units but does not stop the plague); replace the lost units by training
new ones and keep enough workers so the economy recovers.

## rule_repair_demolish_v1
Repair: any of your finished, damaged buildings (the Town Center too) can be repaired by exactly one worker. The
repair cost is paid when the repair starts: half of the building's build cost scaled by the missing HP (a building
at 50% HP costs 25% of its build cost; the Town Center is valued at 200 wood and 50 gold). The worker walks right next to
the building and works for up to 0.75 x the construction time (at least 2 s); the building then has full HP. If the
worker is taken away or dies, the unused part of the cost is refunded. Select the building and press Repair, or
right-click your damaged building with a worker selected.
Demolish: every finished building except the Town Center can be demolished by exactly one worker. The worker works
for half of the construction time (2-8 s); then 50% of the build cost is refunded (rounded down) and the building
is removed. The training queue must be empty, a burning building cannot be demolished and a demolition can be
cancelled before it ends. Demolishing a badly damaged building that is about to be destroyed saves half its cost.

## strategy_economy_v1
Economy strategy: keep the Town Center training Workers early, spread workers across wood, food and gold,
build Houses before reaching the population cap, add farms for steady food and a Mine for steady gold.
Avoid floating unspent resources; spend them on workers, production buildings or upgrades.

## strategy_defense_v1
Defense strategy: identify the visible enemy unit types first, then train their counter (Spearmen vs Cavalry,
Archers vs Spearmen, Cavalry vs Archers). Gather your soldiers near the threatened region, man an Archer
Tower / Rocket Turret, and use walls to funnel attackers. Keep workers away from the fight.

## strategy_attack_v1
Attack strategy: attack when your army is larger or counters the visible enemy army, ideally after a weapon
upgrade. Target the enemy Town Center to win. Do not attack blindly into fog: scout first. Bring Archers to
destroy an Archer Tower (or Tanks for a Rocket Turret).
