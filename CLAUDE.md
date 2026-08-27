# rpg-ai

A 2D open-world RPG where all AI runs locally. NPCs generate dialogue via an LLM, quests are created dynamically from conversations, and the world context is AI-generated at startup.

## How to run

```bash
uv run game
```

Requires CUDA drivers and the model at `models/Qwen2.5-7B-Instruct-Q2_K.gguf`. See README for setup.

## Design notes

The rules behind the systems (why a village turns hostile as a whole, why a tunnel is ordinary world space, why healing is scarce) live in `docs/design/`, one file per subject with an index in `docs/design/README.md`. Read the one that covers what you are changing. This file holds the map and the short rules; that folder holds the reasoning.

## File map

One line per file, saying what it owns. Update this when adding, removing or substantially repurposing a file: this list is what keeps lookups fast instead of requiring a codebase search. Keep entries to a line; anything longer belongs in `docs/design/`.

`saves/save.json`: persisted game state (gitignored). `models/`: GGUF model files (gitignored).

### rpg_ai
- `src/rpg_ai/__main__.py`: entry point; Pygame and LLM queue setup, main menu to game loop, a fresh `SaveSystem` per session

### game
- `src/game/game.py`: `Game`, the main loop, input handling and state orchestration; `_build_action_tables` holds the three tables a press or a click is answered from (`key_actions`, `dock_actions`, `interact_actions`), `current_interaction`/`_interact` are the one prompt and the one E, `_swap_hands` is key 1 and `_use_bomb` is G, `_sweep_loot` the loot magnet, `save_data` the one path to disk, `_respawn` and `_sleep_until_dawn` the two things that move the player without walking, `_music_context` what the score is told the world is doing
- `src/game/world.py`: `World`, the state everything reads (entity lists, buildings, shops, saving) plus the per-frame `update`; five jobs are mixed in from `combat.py`, `projectiles.py`, `streaming.py`, `places.py` and `navigation.py`. Also here: chunk-bucketed building lookup, `blocked` and what is solid where, spawn caps and safe placement (`ring_search` is the one outward search every placement goes through), terrain speed, village defence orders, the night routine (`_npc_sleeps`, `_home_for`, `_households_in`, `_wake_up`) and the gates it shuts (`_work_gates`), impulses and `unstick`
- `src/game/combat.py`: `WorldCombat`, every blow and its aftermath: `handle_attack` (by hand, the archetype deciding swing or shot), the target-group table, cleave falloff, thrust lanes, knockback, crits, gore (`blow_style` is the weapon family a wound is drawn from), weapon affixes and elements, breakables/windows/gates/props, bear traps, felling a tree (`_chop_tree`), breaking a boulder (`_smash_boulder`) or a signpost (`_wreck_poi`), bombs (`use_bomb`, `update_bombs`) and `explode`
- `src/game/projectiles.py`: `WorldProjectiles`, everything in flight: `_fire_ranged` (mana, ammo, style), monster shots, and what each projectile strikes
- `src/game/places.py`: `WorldPlaces`, what the player does at a place once they have walked to it: camps, campfire rest, shrines, wells and caves, tunnels and what is waiting in one (`_populate_tunnel`, `_populate_cave`: the garrison, the hoard's luck by distance, the bats, the vault and its warden), theft and witnesses (`theft_witness`, `squatter_witness`), setting a shut bear trap again (`sprung_trap_in_reach`, `rearm_trap`), the per-offence warning ladder (`strike_village`, `shout_warning`, `warnings_at`) and village anger (`provoke_village`, `hold_grudge`, `pacify_village`, `yield_to_player`, `call_for_help`), the barred gate the player can heave open (`barred_gate_in_reach`), directions and rumours, explored cells, `pass_time`
- `src/game/streaming.py`: `WorldStreaming`, how the map appears around the player: chunk load/unload, scenery reindexing, village creation, `prepare`, and the background naming/lore threads
- `src/game/navigation.py`: `WorldNavigation`, how anything gets from where it is to where it wants to be: `line_of_sight`, `walls_near`, `chase_waypoint`, `_detour_corner` and the corner it commits to, `unwedge` (the body standing on legal ground it cannot get off), `assign_surround_slots`, and who may let themselves through a shut door or a barred gate (`open_door_for`, `pass_gate_for`, `clear_gateways`); `Point` is the bare coordinate a chase can be aimed at
- `src/game/events.py`: `EventSystem`, random world events (travelling merchant, treasure, blood night, rumours, village crisis); `blood_intensity` is the one number the blood night is read through
- `src/game/quest.py`: `Quest` dataclass (fetch/kill_mob/loot_mob/recover_stolen/slay_boss/clear_camp/steal/deliver) and its (de)serialisation; `COUNTED_QUEST_TYPES` is the one list of counter-finished types
- `src/game/record.py`: `Record`, the playthrough tally (deaths, quests handed in) and the milestones each pays out at
- `src/game/loot.py`: every loot roll (lootbox, crate, POI cache, villager purse, quest reward, shop stock), all drawing from one `_roll_loot_item` table and taking the player's `loot_luck`

### game/entities
- `src/game/entities/entities.py`: `Entity` base (hp, damage, attack anim, `root`, `chill`), impulses and stagger, `push_apart`, `step_along`/`step_towards` (the one wall slide everything walks by), `Gait` (the one walk cycle), `draw_human` and the body sprite it keeps (`_body_sprite`)
- `src/game/entities/gear.py`: drawing the gear a character visibly wears: one weapon per hand by its own silhouette (`_WEAPON_PARTS`, picked by `c.weapon_look`), the shield worn on the body's offhand side, armour ring, accessory gem
- `src/game/entities/player.py`: `Player`, movement, inventory and stacking, equip slots (one weapon per hand, bomb, shield, armor, accessory, ammo), `hand_weapon`/`select_weapon`/`swap_hands`, `_best_pair` behind Equip best, an older save's four weapons cut down to the best two, and the potion quickbar, potions and buffs, mana, shield block, affix effects, death weakness, spawn grace, `gear()`
- `src/game/entities/npcs.py`: `NPC`, villagers: timed hostility and grudges, the shout that comes before them (`warn`), hunting/routing/stone throwing, surrender and its white flag (`surrender`, `surrendered`, `yielded`), `aim_at` (the one place facing and firing are decided together), `threaten` (fighting back against whatever bit them) and `melee_standoff` (their own weapon's reach), the vision cone, militia, guard and tower-archer roles, weapons rolled off the home seed by settlement tier, affinity, shop stock and restock clock, wandering
- `src/game/entities/wander.py`: `Wander`, the idle-then-stroll movement shared by NPCs, critters and the monsters that have seen nobody
- `src/game/entities/monsters.py`: `Monster`, `pick_monster_kind` (spawn by distance, fading kinds out again), chasing and ring slots, steering, ranged kinds that keep distance, charge/flank/detonate behaviours, the disguise a husk drops (`reveal`), the roam it does while it has seen nobody (`post_at` for anything holding a post), burn ticks
- `src/game/entities/monster_art.py`: the vector art per silhouette (`humanoid`, `goblin`, `hulk`, `skeleton`, `wraith`, `blob`, `beast`, `robed`, `creeper`, `husk`/`husk_open`) behind `draw_monster`; shadow, breath and eyes are shared by all of them
- `src/game/entities/boss.py`: `Boss(Monster)`, a named LLM-titled boss: the climb out of the ground it arrives by (`rising`, `draw_rise`), an enrage phase, the bands a shrinking one walks down (`_apply_shrink`), and telegraphed abilities (slam, bolt volley, summons marked on the ground before they arrive)
- `src/game/entities/village.py`: `Village`, `village_site`, `generate_village`, `generate_starting_world`; grid layout round a plaza with the specials spread by `_assign_slots` and every doorstep kept clear, the lanes between the houses (`plan_streets`, routed round the footprints on `_StreetGrid` and run out to `gateways`, where the roads stop), `defences()` (wall, gates, towers, outworks), the gates' bar, the night shutting that is not a bar (`shut_for_night`, `push_open`), swing (slow shut, quick open, its own going-over animation once beaten down) and `gate_between`, `tier` (the wall, the extra buildings, the towers, the banners and the braziers all read it), `grounds_radius`; also the site registry (`register_world_sites`) the starting town and its ruin are put on the map through
- `src/game/entities/buildings.py`: `Building`, one building's footprint (one rect or an L, the wing snapped flush to its block), facade offsets, interior layout and furniture, front door and its `doorstep`, whether it is `locked` and how it is unbarred from inside, windows and the holes broken ones leave in the wall (`window_gaps`), `covers` (what the building stands on, as against `blocks`), the settlement tier that lights its windows after dark (`village_tier`); the footprint, floors and wall shell are worked out once and kept (`reset_geometry` drops them); `set_active_buildings`
- `src/game/entities/building_art.py`: `BuildingArt`, mixed into `Building`: everything a building's look is made of, from the roof and its texture to the awning, the ruin, the open door leaf, the broken pane, the lamp behind a lit one (`_lit_windows`) and the furniture in the cutaway; `style()` rolls the whole look off the building's id, `_shell()` paints the walls and the roof onto a surface of their own and keeps it
- `src/game/entities/scenery.py`: `Scenery`, one piece of wilderness (tree, boulder, pond, road, bridge, grass): what it covers, what it blocks, what shades it casts, how it draws, and the two the player can argue with: a tree's hp, `fell()` and stump, a boulder's hp, `smash()` and rubble
- `src/game/entities/terrain.py`: where all of it stands: per-chunk biome clumps, roads and footpaths between settlements and landmarks (`RoadBlob`, `road_ends_at`), rivers and their crossings (`Deck`, one per ford and never two together), `water_near`, `generate_chunk_scenery`, and the collision and water indexes
- `src/game/entities/traps.py`: `BearTrap`, `traps_for_chunk`, the hunters' traps laid in a band around settlements, never on anything solid (`_open_ground`); persisted only as which ones have shut
- `src/game/entities/tunnel.py`: `Tunnel`, `has_tunnel`, the rooms dug far out in world space, reached by a village well or a wilderness cave; floor-based collision, the exit shaft, the vault at the far end of a cave, and the player's own light, clipped to the floor they stand on so it never shines through rock
- `src/game/entities/bomb.py`: `Bomb`, the mine laid on the ground and the grenade thrown at the cursor; both end in `WorldCombat.explode`
- `src/game/entities/breakables.py`: `Breakable`, `generate_breakables`, outdoor props near buildings (barrel, powder keg, planted decoration), each with persisted hp
- `src/game/entities/poi.py`: `PointOfInterest`, `pois_for_chunk`, `poi_site`, `poi_footprint` (how much ground one covers, which is what a road and a footpath keep off), wilderness landmarks generated per chunk (ruins, shrine, camp, farmstead, graveyard, watchtower, stones, signpost, cave), and which of them is a prop that can be put through (`wreckable`); only `state()` is saved
- `src/game/entities/critter.py`: `Critter`, `pick_critter_kind`, all wildlife: temperament-driven behaviour, fleeing with stamina, quadruped drawing
- `src/game/entities/items.py`: `Item` and everything about one: types, stacking, potions, rarity and affix rolling, accessory flavors, `base_value`, inventory sections, `icon_shape`, coin purses, the ground marker and magnet
- `src/game/entities/item_icons.py`: `draw_shape_with_border`, the vector art behind every item icon, one function per shape in `_SHAPES`
- `src/game/entities/projectile.py`: `Projectile`, an arrow/bolt/stone/boomerang in flight; hops no longer than it is wide, `hostile`/`by_player`/`from_npc`/`over_walls`/`pierce` flags, the `hand` and `weapon_id` it was loosed from, the `skill` a hit trains, boomerang return
- `src/game/entities/stats.py`: `Stats`, use-based progression (xp, training, derived bonuses, magic and swimming), queueing `pending_levelups`

### llm
- `src/llm/llm_request_queue.py`: `LLMRequestQueue`, all LLM calls serialised onto a worker thread, interactive categories first; `generate_response_queued` / `generate_response_stream_queued`, `poll=True` for the main thread, `llm_busy()`
- `src/llm/dialogue_manager.py`: `DialogueManager`, the NPC dialogue window: streaming replies, the merchant Shop button and purse, end-of-conversation detection, quest analysis on close
- `src/llm/quest_system.py`: `QuestSystem`, conversation analysis into quests, one `_build_*` per type and one completion hook per type, reward coins clamped into `QUEST_COIN_BANDS`
- `src/llm/merchant_system.py`: `generate_shop_inventories`, one batched call stocking every merchant in a town, with a local fallback per shop
- `src/llm/name_generator.py`: `NPCNameGenerator`, background NPC name generation buffered in the save
- `src/llm/death_taunts.py`: `DeathTauntGenerator`, the death-screen line, written ahead of need and buffered like names

### core
- `src/core/constants/`: all game constants in one flat namespace (`import core.constants as c`), split into `ui.py`, `player.py`, `combat.py`, `bestiary.py`, `world.py`, `villages.py` and `items.py`, so a constant is filed by what it tunes. `Fonts` is the one name rebound at runtime by `__main__`
- `src/core/save.py`: `SaveSystem`, atomic thread-safe JSON saving; the key list at the top is the record of what the save owns
- `src/core/settings.py`: `Settings`, the preferences that outlive a playthrough (music on/off, sound on/off), written to `saves/settings.json`
- `src/core/camera.py`: `Camera` world-to-screen translation plus `ScreenShake`/`get_shake`
- `src/core/screen_fx.py`: `Hitstop`, `HurtVignette`, `ScreenFlash`, `TrapSnap` and `EventBanner`, the full-screen effects read once a frame in `Game.run`, plus `draw_blood_veil`, the red a blood night is seen through
- `src/core/damage_fx.py`: the flinch, flash and cracks drawn on a struck prop, keyed by string in a session-only registry
- `src/core/swing_arcs.py`: the trail a melee attack leaves, over exactly the wedge or lane the hit test accepts; `SwingArc` is the sweep, `ThrustTrail` the lunge a spear is drawn as
- `src/core/impact_fx.py`: `ImpactPulse`, the wave of particles an area effect throws out to its own damage radius plus a bolt to each thing it caught, so several damage numbers have something visible behind them
- `src/core/daynight.py`: `DayNightCycle`, elapsed time in the cycle, `darkness`/`is_night`/`curfew`/`phase`/`time_until`, and the ambient night tint
- `src/core/decals.py`: capped session-only ground blood, each splat a torn shape painted once at spawn: `_SPLAT_STYLES` (one recipe per weapon family) behind `splash`, the directional `spawn_spray` and the long `spawn_arcs` a kill throws, plus `track_walkers`, the prints anything walking through fresh blood leaves behind it
- `src/core/floating_text.py`: rising damage numbers, bigger and gold on a crit
- `src/core/utils.py`: `ConversationHistory`, `frames(dt)` (the one definition of a delta in frames), random helpers, and the LLM response parsers
- `src/core/dialogue_log.py`: `write_conversation`, finished conversations written to `logs/dialogues/`
- `src/core/llm_log.py`: `log_call` / `log_parse_failure`, every generation appended to `logs/llm_calls.jsonl`
- `src/core/particles.py`: world-space particle bursts, omnidirectional or in a cone, with optional gravity and shard shapes; `emit_over` is the same burst kept up for as long as something takes
- `src/core/audio.py`: `SoundManager`, procedural sound effects synthesised in memory (`_SOUND_SPECS` is the whole list), silent while the sound preference is off
- `src/core/music.py`: `MusicPlayer`, a chord pad per context (`CONTEXTS`: day, night, village, combat, boss, blood) with several progressions each, rendered in memory on a worker thread and crossfaded on two reserved channels; what is playing is resolved by `Game._music_context`
- `src/core/status_fx.py`: `emit_status` and the `EFFECTS` table, the particles drifting around anything carrying a timed effect, one look per effect
- `src/core/text_fx.py`: `draw_outlined_text`, world-space text readable without a panel behind it

### ui
- `src/ui/widgets.py`: shared menu/HUD draw primitives (panels, buttons, slots, icons), `EQUIP_SLOTS`/`WEAPON_SLOTS`/`ACTION_SLOTS` as the one definition of the equip slots and `SLOT_KEYS` of what uses each, `wrap_text`, `draw_scrollbar`
- `src/ui/game_renderer.py`: `GameRenderer`, drawing the world and the HUD: entities and buildings in range, the underground branch, health/mana/guard bars, potion bar and buff chips, the two-row equipped paper-doll (the two hands and the bomb, then what is worn), the icon dock (`dock_buttons` rows), witness cones, the one interaction prompt, the quest-target arrow drawn last of all, the save marker
- `src/ui/minimap.py`: `Minimap`, explored cells and what stands on them plus rumour marks, with the village-name, mood, warning-countdown, paces-from-home and day/night strips under it; `content_bottom` is where whatever stacks below hangs from
- `src/ui/conversation_ui.py`: `ConversationUI`, the dialogue box: rendering, scrolling, text input, close button
- `src/ui/notification.py`: `ToastNotification`, word-wrapped on-screen popups
- `src/ui/quest_tracker.py`: `QuestTracker`, the HUD widget showing one tracked quest plus swap chips for the rest
- `src/ui/loading_indicator.py`: `LoadingIndicator`, the spinner shown while the LLM is generating

### ui/menus
- `src/ui/menus/base_menu.py`: `BaseMenu`, shared menu scaffolding and the reused dim overlay; `EQUIP_BEST_KEY`/`SELL_VALUABLES_KEY`/`SELL_GEAR_KEY`, the keys the repeated one-click actions answer to wherever their button is drawn
- `src/ui/menus/menu_scene.py`: `MenuScene`, the live village the title screen stands over, rolled fresh per launch and holding no save and no player
- `src/ui/menus/main_menu.py`: `MainMenu`, `run_main_menu`, the title screen; returns "new_game"/"continue" and leaves save handling to `__main__`
- `src/ui/menus/pause_menu.py`: `PauseMenu`, with a manual Save game button and the music and sound toggles
- `src/ui/menus/context_menu.py`: `ContextMenu`, the world lore: written onto black as an intro at session start, an ordinary panel when asked for with L
- `src/ui/menus/inventory_menu.py`: `InventoryMenu`, the sectioned item grid, equip/unequip, drinking a potion, right-click bar assignment, Equip best, the paper-doll and the hover tooltip
- `src/ui/menus/shop_menu.py`: `ShopMenu`, buy/sell with bartering and affinity pricing, restock countdown, bulk-sell buttons, two independently scrolling columns
- `src/ui/menus/quest_menu.py`: `QuestMenu`, the active/completed quest list
- `src/ui/menus/stats_menu.py`: `StatsMenu`, character stats and progression, plus the playthrough tally (quests handed in, deaths) and the next milestone of each
- `src/ui/menus/help_menu.py`: `HelpMenu`, the controls screen; `CONTROLS` is the only written record of the key map
- `src/ui/menus/game_over.py`: `run_game_over`, the death screen: what killed the player, a taunt, the penalty and what Weakened costs

## Rules

The short version. `docs/design/` explains each of these.

- The LLM runs on a background thread via `LLMRequestQueue`. Never call `llama_cpp` directly from the main thread.
- A settlement is asked of the model only once the player walks up to it (`WorldStreaming._prepare_settlements_near`, `Villages.PREPARE_DISTANCE`): its name, its shops' stock and the next villager's name are prepared there and nowhere else. Generating a village is not a reason to spend a call on it, and neither is loading a save.
- The world's lore is guarded rather than trusted (`parse_world_context`): an answer with no sentence in it is asked again, and then shown as nothing at all. Only lore the model actually wrote is written to the save; `World.FALLBACK_CONTEXT` is what the other prompts quote when there is none, and it is never displayed.
- A frame builds at most `World.CHUNK_LOADS_PER_FRAME` chunks, nearest first, except the ones the player could walk onto (`World.CHUNK_URGENT_RADIUS`). Crossing a border brings a whole edge into range and building it on that one frame is felt; `prepare` is the exception, because nothing is on screen yet.
- `src/` is the package root; all imports are relative to it (e.g. `import core.constants as c`).
- No tests exist; skip the pre-push hook accordingly.
- Don't launch the game (`uv run game`, or any script that opens a pygame window) to verify a change, and don't ask Valentin to launch it. To self-check a rendering change, a throwaway script that renders to an offscreen `Surface` is fine, with `SDL_VIDEODRIVER=dummy` set before `pygame.init()`.
- `World` is one class split across five files by mixin (`world.py` state, `combat.py` blows, `streaming.py` the map, `places.py` what happens at a place, `navigation.py` getting there). They share the same entity lists; pick the file by what you are changing, not by defaulting to `world.py`.
- A settlement's lanes and the roads outside it are one network: `plan_streets` routes every lane round the building footprints off one flood fill from the plaza, and lays one out to each point a road from a neighbour stops at (`terrain.road_ends_at`). A lane is never laid over a footprint, and never out of a gate no road came to.
- Ground that overlaps itself is drawn in passes over the chunk, never layer by layer per blob: a road's verge and a river's three colours are kinds of their own in `Scenery.GROUND_KINDS`.
- A landmark covers what it draws (`poi_footprint`), not the point it stands on: a footpath stops at that edge, and where a road would cross it the landmark stands down rather than the road bending.
- The map is endless and deterministic, what stands on it is generated on demand and kept. Anything regenerated from a chunk seed must stay a pure function of `(cx, cy)`, with player changes in `World.poi_state`. Villages are the exception and go through `World._ensure_village`.
- Difficulty is distance from the world centre, pulled by four levers (which kinds, how many, what has a name, and what a town sells through `NPC.stock_luck`). Nothing scales a monster's own stat block.
- The spawn point is protected three ways at once: nothing hostile spawned near it, the player placed by `safe_spot_near`, and `Death.SPAWN_GRACE_S` of grace.
- Healing is scarce and each source has one job (potion, campfire, bed, slow passive trickle). New healing goes through one of the four, not beside them.
- A crowd surrounds rather than queues: everything chasing one target goes through `World.assign_surround_slots`. Only the villagers the player is standing among join it (`Villages.MOB_ENGAGE_RANGE`); the rest of an angry village goes on with its day.
- Violence against a villager is a whole-settlement event through `WorldCombat._resolve_npc_hit`, and every settlement warns once per kind of offence before it turns (`WorldPlaces.strike_village`, one ledger per `Villages.OFFENCES` entry, each with its own wording and its own visible countdown). Theft, trespass and damage (a room wrecked, a window put through) are the exceptions and turn exactly one witness, on the same ladder. Striking somebody who has yielded skips it entirely. Dying to a settlement is it getting its own back, so that one forgets (`pacify_village`).
- Nothing the player did not do pays the player: `by_player=False` withholds every reward and consequence, never the kill.
- Nothing in the world breaks in a single hit, and every hit-point pool draws its own wear through `core/damage_fx.py`.
- A wound is drawn from the weapon that made it: one recipe per family in `core/decals.py`, picked through `WorldCombat.blow_style`, and a kill is that recipe several times over.
- The music answers what is happening (`Game._music_context` into `core/music.py`), as a priority and never a blend.
- A settlement is a landmark, not scenery: one per eight-chunk region at most, with `Villages.MIN_GAP` of wilderness between any two, and the roads (`Scenery.ROAD_MAX_LENGTH`) sized off that gap so a village always reaches its neighbour.
- A village keeps hours: past `DayNight.CURFEW_DARKNESS` everyone not fighting goes home and stays in (`World._npc_sleeps`, the door shut by the last one in) and the gates lean shut. Shutting for the night is not barring: a shut gate opens to one press from either side (`Village.push_open`) and answers no weapon; only a grudge or a real mob puts the beam across.
- A tier is something the player can see before they can count anything: the wall itself, how many buildings there are, how big the towers are, and what is hung and lit on the wall after dark. A new difference between settlements is a row indexed by tier.
- A door (and a gate) is the only obstacle a chaser may break. If a monster cannot reach the player, the answer is navigation, not demolition. Its own people let themselves through instead of breaking it (`World.open_door_for`, `World.pass_gate_for`), and the player heaves the bar up (`Game._lift_gate`, held not pressed). Gates only bar on a grudge or a real mob (`Villages.BAR_GATES_MOB`); shutting for the night is the other thing entirely.
- Nothing is ever sealed inside a leaf: whatever stands in a doorway or a gateway is stepped out of it before it shuts, and every mover unsticks each frame, the player included. A villager who means to move and cannot is prised out too (`World.unwedge`); a tower archer is the one body exempt from both, because the tower is where they belong.
- A weapon family answers a question rather than being a bigger number; a bigger number is a rarity roll.
- The player has two hands and one weapon in each: hand one is the left mouse button, hand two the right, and key 1 swaps the two over. Either weapon goes in either hand (melee defaults left, ranged right) and the archetype decides what the click does, so nothing outside `Player` may ask whether a weapon is melee or ranged. Read a hand through `hand_weapon` and fill one through `select_weapon`, never a slot by name, and pass the hand to every on-hit effect. An empty hand is bare hands, which is a loadout and not a missing weapon.
- Equip best takes gear off as well as putting it on: a slot `Player._best_loadout` does not want is emptied, and the best weapon carried goes on the left button whatever its family, the best of the other family on the right (`_best_pair`).
- The shield is worn on the offhand side, and that side is where it works: the wedge `draw_shield` shows is the wedge `Player.shield_side_hit` reads. A shot arriving there is turned away and costs guard, never health.
- A bomb is spent rather than wielded, so it has a slot of its own and a key of its own (G) instead of costing a hand. Both kinds end in `WorldCombat.explode`, so nothing about a blast is ever written twice.
- Felling a tree and breaking a boulder are what the wilderness remembers (`World.felled` and `World.smashed`, keyed by chunk and index): the chunk stays a pure function of its seed and the wreck is laid over the top, exactly as `poi_state` is. A landmark that is a prop rather than a place (`PointsOfInterest.WRECKABLE`) comes down the same way, kept in its own `poi_state`.
- Some houses are locked, rolled off the building's id: the door never opens for the player from the street, the window beside it is the way in (a broken pane is a hole in the wall shell, not a decoration), and the bar comes off for good from the inside.
- Deaths and quests handed in are a tally, not a stat: they live in `game/record.py`, and their milestones pay in loot and in taunts respectively.
- Exactly one interaction prompt is on screen at a time, drawn from `Game.current_interaction`.
- A playthrough goes in the save, a preference goes in `core/settings.py`: New game wipes one and must not touch the other.
- The player's own health bar is HUD drawn in world space, so it goes over the canopies (`Player.draw_health_bar_overlay`), never inside the entity pass.
- No boss is stood up near the start, within `Boss.MIN_DIST_FROM_VILLAGE` of any settlement's grounds (asked of the site registry, so a town not yet generated still counts) or on somebody's floor: every spawn goes through `World.boss_spawn_ok`, the landmark guardian included. How many exist at once and how often one is rolled are both ramps on distance from the centre (`World.boss_cap`).
- A boss arrives rather than appearing: `Boss.rising` is the climb out of the ground, and the roar, the flash, the shake and the banner land on the frame it finishes. A settlement answers one on its grounds like any intruder, only from further off, and everything a boss does to a village is `by_player=False`.
- A disguised monster (`MonsterKind.disguise`) is drawn as what it is pretending to be, unmasks only for the player, and gives its tells in the silhouette rather than in behaviour.
- A monster that has seen nobody roams its own patch; one with a post to hold roams it on a short leash (`Monster.post_at`). Nothing stands still waiting to be triggered.
- Underground, light is clipped to floor the player can actually reach (`Tunnel._lit_floor`: what is stood on plus whatever opens onto it): it never crosses rock, it never snaps at a doorway, and what is past it is not dimmer, it is unseen.
- A cave is worth the walk and a well is a cellar: the hoard's luck, the vault's guaranteed box, the bats and the warden are all `WorldPlaces._populate_cave`, and nothing is stood up within `Tunnels.ENTRANCE_CLEARANCE` of the shaft.
- A quest sends the player out of town (`World.quest_target_spot`) and the walk is what the coins pay for (`quest_system.coin_band`).
- The minimap draws memory, not radar: explored cells only, plus rumour marks. Underground those cells are finer, lantern-wide and floor-only, so a cave unfolds as it is walked and is saved like any other ground. What is stacked under it (village name and mood, warnings, paces from home or from the way in, the clock) hangs off `Minimap.content_bottom`.
- The quest arrow is drawn last of everything, after the HUD: an arrow nobody can see is worth nothing.
- Nothing walks the whole building list per frame; go through `buildings_near`/`buildings_in_range`. The same rule for what is drawn: a frame asks for the chunks it can see (`floor_details_in_range`, `scenery_*_in_range`) and measures the rest against the view before drawing it.
- What holds still is painted once and kept: a building's walls and roof (`BuildingArt._shell`, dropped by `reset_geometry`), a body facing up its own sprite (`_body_sprite`, keyed on everything it is made of with the stride and the swing in whole steps). What changes is drawn live over the top, in the order it always was.
- A monster's look is its kind's `shape`, an animal's behaviour is its `temperament`, an item's icon is derived from its name and type. Adding one means adding a table row, not a branch.
- Anything handed to the player must end up in `world.items` or its id will not resolve on reload.
