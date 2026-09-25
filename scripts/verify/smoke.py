"""Run the world for a while and fail loudly if anything about it stops making sense.

What it catches is what a change breaks without raising: a coordinate gone NaN, an entity
whose hp left its own range, an item id nothing resolves, a quest pointing at somebody who
is not there. Halfway through, villagers are handed one quest of every type and a caravan
comes down the road, since an idle world holds no quests to check; at the end the world is
saved, loaded into a fresh `Game`, and checked again, because half of what a change breaks
it breaks on disk. Exits non-zero with the reasons on stderr, so a runner never reads a
silent 1.

    uv run python scripts/verify/smoke.py [--frames 900] [--seed N]
"""

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness


def _finite(*values):
    return all(isinstance(v, int | float) and math.isfinite(v) for v in values)


def check(game):
    """Every assertion is about state the frame left behind, never about how it got there."""
    problems = []
    world, player = game.world, game.player

    if not _finite(player.x, player.y, player.hp):
        problems.append(f"player state not finite: x={player.x} y={player.y} hp={player.hp}")
    if player.hp > player.max_hp:
        problems.append(f"player hp {player.hp} over max {player.max_hp}")

    for name, group in (("npc", world.npcs), ("monster", world.monsters), ("item", world.items)):
        for entity in group:
            x = getattr(entity, "x", None)
            y = getattr(entity, "y", None)
            if x is not None and not _finite(x, y):
                problems.append(f"{name} {getattr(entity, 'name', '?')} at non-finite ({x}, {y})")
            hp = getattr(entity, "hp", None)
            if hp is not None and not _finite(hp):
                problems.append(f"{name} {getattr(entity, 'name', '?')} hp not finite: {hp}")

    # Anything handed to the player has to resolve on reload, which means being in the one
    # master list. A quest pointing at an id that is not there is a save that loads wrong.
    world_ids = {getattr(item, "id", None) for item in world.items}
    for item in getattr(player, "inventory", []):
        item_id = getattr(item, "id", None)
        if item_id is not None and item_id not in world_ids:
            problems.append(f"carried item {item_id} is not in world.items")

    equipped = {slot: item_id for slot, item_id in player.equipped_ids().items() if item_id is not None}
    carried_ids = {getattr(item, "id", None) for item in getattr(player, "inventory", [])}
    for slot, item_id in equipped.items():
        if item_id not in carried_ids:
            problems.append(f"{slot} slot holds {item_id}, which the player is not carrying")

    problems += check_quests(game, world_ids)
    return problems


def check_quests(game, world_ids):
    """What the bug hunts kept finding by reading: a quest nobody can hand in because its
    giver, its recipient or its item is gone, or one the log holds twice."""
    problems = []
    world = game.world
    active = game.dialogue_manager.quest_system.active_quests
    caravan = world.events.caravan()
    names = {npc.name for npc in world.npcs if npc.name and npc.hp > 0}

    if len({id(quest) for quest in active}) != len(active):
        problems.append("the same quest is in the log twice")
    for npc in world.npcs:
        if npc.has_active_quest and not any(quest is npc.quest for quest in active):
            problems.append(f"{npc.name} holds a quest the log does not")
        if npc.quest is not None and any(npc is member for member in caravan):
            problems.append(f"{npc.name} is in the caravan and holds a quest")

    for quest in active:
        label = f"{quest.quest_type} quest from {quest.npc_name}"
        givers = [npc for npc in world.npcs if npc.quest is quest]
        if len(givers) != 1:
            problems.append(f"{label} has {len(givers)} givers")
        elif givers[0].hp <= 0:
            problems.append(f"{label} has a dead giver")
        delivered = quest.quest_type == "deliver" and quest.kills_done >= quest.kill_count
        if quest.item is not None and not delivered and quest.item.id not in world_ids:
            problems.append(f"{label}: its {quest.item_name} is not in world.items")
        if quest.quest_type == "deliver" and not delivered:
            if quest.recipient_npc_name not in names:
                problems.append(f"{label}: recipient {quest.recipient_npc_name} is not in the world")
            elif any(npc.name == quest.recipient_npc_name for npc in caravan):
                problems.append(f"{label}: recipient {quest.recipient_npc_name} is in the caravan")
        if quest.quest_type == "recover_stolen" and quest.item is None and quest.thief_npc_name not in names:
            problems.append(f"{label}: thief {quest.thief_npc_name} is not in the world")

    quest_item_ids = [quest.item.id for quest in active if quest.item is not None]
    if len(set(quest_item_ids)) != len(quest_item_ids):
        problems.append("two quests share one item")
    return problems


# One offer per quest type, written the way `analyze_conversation_for_quest` returns them.
OFFERS = [
    {"quest_type": "fetch", "item_name": "a healing herb", "reward_item": "old dagger"},
    {"quest_type": "kill_mob", "monster_hint": "wolf", "kill_count": "3"},
    {"quest_type": "loot_mob", "item_name": "wolf pelt", "monster_hint": "wolf"},
    {"quest_type": "recover_stolen", "item_name": "my grandmother's locket"},
    {"quest_type": "deliver", "item_name": "a sealed letter"},
    {"quest_type": "steal", "item_name": "ledger"},
    {"quest_type": "clear_camp"},
    {"quest_type": "slay_boss"},
]


def hand_out_quests(game):
    """A caravan on the road, then every quest type given to a different villager, with
    everybody named so a delivery can be addressed to anyone, the caravan included."""
    game.world.events._spawn_wandering_merchant(game.player)
    quest_system = game.dialogue_manager.quest_system
    givers = [npc for npc in game.world.npcs if not npc.hostile and not npc.is_thief and npc.quest is None]
    for npc in givers:
        npc.assign_name(game.npc_name_generator)
    for npc, offer in zip(givers, OFFERS, strict=False):
        info = {"has_quest": True, "quest_description": f"test {offer['quest_type']}", "reward_item": "", **offer}
        quest_system.create_quest_from_analysis(npc, info, game.npc_name_generator)
    for npc in game.world.events.caravan():
        npc.assign_name(game.npc_name_generator)
    return len(quest_system.active_quests)


def named(world, leave_out=()):
    """Who in the world has a name, as a sorted list: what a save has to bring back."""
    return sorted(npc.name for npc in world.npcs if npc.name and not any(npc is other for other in leave_out))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=900)
    parser.add_argument("--seed", type=int, default=harness.SEED)
    parser.add_argument("--check-every", type=int, default=60)
    args = parser.parse_args()

    game, clock = harness.boot(seed=args.seed)
    problems = []
    given = 0
    for frame in range(0, args.frames, args.check_every):
        if not given and frame >= args.frames // 2:
            given = hand_out_quests(game)
        harness.step(game, clock, args.check_every)
        for problem in check(game):
            problems.append(f"frame {frame + args.check_every}: {problem}")

    before = len(game.dialogue_manager.quest_system.active_quests)
    # The caravan is passing through and is never saved; everybody else named comes back.
    expected = named(game.world, leave_out=game.world.events.caravan())
    game.save_data()
    game.world.close()

    game, clock = harness.boot(seed=args.seed, new_game=False)
    returned = named(game.world)
    if returned != expected:
        extra = sorted(set(returned) - set(expected))
        missing = sorted(set(expected) - set(returned))
        problems.append(f"after reload: the named npcs differ, back from nowhere {extra}, lost {missing}")
    harness.step(game, clock, args.check_every)
    problems += [f"after reload: {problem}" for problem in check(game)]
    after = len(game.dialogue_manager.quest_system.active_quests)
    if after != before:
        problems.append(f"after reload: {after} active quests, {before} before the save")
    game.world.close()

    if problems:
        print(f"FAIL: {len(problems)} problem(s) over {args.frames} frames", file=sys.stderr)
        for problem in problems[:40]:
            print(f"  {problem}", file=sys.stderr)
        return 1

    world = game.world
    print(
        f"OK: {args.frames} frames, {len(world.npcs)} npcs, {len(world.monsters)} monsters, "
        f"{len(world.buildings)} buildings, {len(world.items)} items, "
        f"{given} quests handed out and {after} still held after a reload"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
