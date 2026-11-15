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

## rule_towers_v1
Defense towers: Archer Tower (Medieval) and Rocket Turret (Sci-Fi) cost 100 gold and must be manned by one
soldier to fire (Archer in Medieval, Marine in Sci-Fi). Only Archers can damage an enemy Archer Tower, and
only Tanks can damage an enemy Rocket Turret. Towers are strong defensive anchors near the base or a gate.

## rule_walls_v1
Walls: drawn segment by segment for 10 wood each. Walls block movement and protect workers and buildings.
The wall upgrade line (Stone/Brick, or Iron/Obsidian in Sci-Fi) increases the health of all walls.

## rule_upgrades_v1
Upgrades are researched at the Blacksmith (Tech Lab) one at a time. Weapons have 3 tiers (+15%, +30%, +50%
damage), Armor has 4 tiers (10%, 20%, 30%, 40% damage reduction), Walls have 2 tiers. Each tier requires the
previous tier of the same line. Upgrades affect soldiers only, not Workers. A cancelled research is refunded.

## rule_disasters_v1
Random disasters: Fire starts in one of your buildings and slowly burns about 10% of your stored resources
while it burns; all workers stop working and run to extinguish it and cannot take other orders until it is out.
Plague lasts a while and kills 1-3 of your units. Rain is only visual and has no gameplay effect.

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
