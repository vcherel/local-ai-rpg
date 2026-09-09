"""The README's screenshots, drawn offscreen at the size the game actually runs at.

Not a check: nothing here passes or fails. It exists so the pictures on the front page can
be regenerated after the art or the HUD moves, instead of being a photograph of a build
nobody can reproduce. Same harness as everything else in this folder, so a shot is a
function of its seed.

    uv run python scripts/verify/shots.py --out assets

Three things the scenes have to work around, all of them consequences of the harness rather
than of the game:

- `harness.boot` opens 1280x720 and the HUD is laid out against `Screen.WIDTH/HEIGHT`, so a
  smaller surface crops the minimap and the equipped dock straight off the edge.
- The stubbed model answers every prompt with the world context, so anything named while
  these frames run (a village, an NPC, a boss) is called that whole sentence.
- The dummy video driver parks the cursor in the corner, and a swing goes towards it.
"""

import argparse
import math
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness

# 1800x900 is what `core.constants.Screen` says the game is.
GAME_SIZE = (1800, 900)

VILLAGE = (14574, 13467)
STARTING_TOWN = (2500, 2500)
WILDS = (16500, 11500)
DEEP_WILDS = (21000, 15200)

# Names for whatever was generated while the frames ran, in place of the stub's sentence.
VILLAGE_NAMES = ("Ashford", "Redmoor", "Hollowfen", "Greystile", "Larkhollow")
NPC_NAME = "Maren the Cooper"
MERCHANT_NAME = "Ivo the Peddler"
BOSS_NAME = "Vashek, the Sunken Crown"

CONVERSATION = (
    ("npc", "Well met, traveller. You are not from the valley, are you."),
    ("player", "I'm looking for work. Anything you need doing?"),
    (
        "npc",
        "Aye, you have the look of someone who walks. Then walk east, past the old ford, "
        "and find what is left of my brother's cart. Bandits took it three nights ago and "
        "nobody in this village will go near the treeline after dark. Bring me back his "
        "seal and I will make it worth the road.",
    ),
)

# A village empties its houses over the first few hundred frames, and everyone spends them
# stacked in their own doorway. This is how long it takes the street to spread out.
VILLAGE_SETTLE = 1860

# The boss banner fades in over `Events.BANNER_FADE_MS`, so the frame the climb finishes on
# catches it at a fraction of its opacity. `Boss.RISE_MS` is 1300ms, a frame is 16ms.
BOSS_RISE_FRAMES = 145


def kit_out(game):
    """Gear, coins and a bag, so the HUD in every shot is a HUD rather than empty slots."""
    from game.entities.items import Item

    player = game.player
    player.coins = 342
    carried = [
        Item(0, 0, "Steel Sword", "weapon", bonus=7, rarity="rare"),
        Item(0, 0, "Hunting Bow", "weapon", bonus=5, rarity="uncommon"),
        Item(0, 0, "Chainmail", "armor", bonus=6, rarity="rare"),
        Item(0, 0, "Round Shield", "shield", bonus=4, rarity="uncommon"),
        Item(0, 0, "Silver Ring", "accessory", bonus=3, rarity="epic"),
        Item(0, 0, "Arrows", "ammo", quantity=64, rarity="common"),
        Item(0, 0, "Smoke Bomb", "bomb", quantity=5, rarity="uncommon"),
        Item(0, 0, "Health Potion", "potion", rarity="uncommon", quantity=3),
        Item(0, 0, "Mana Potion", "potion", rarity="common", quantity=2),
        Item(0, 0, "Iron Dagger", "weapon", bonus=3, rarity="common"),
        Item(0, 0, "Gold Chalice", "misc", rarity="rare"),
        Item(0, 0, "Amber Gem", "misc", rarity="epic"),
        Item(0, 0, "Leather Armor", "armor", bonus=3, rarity="common"),
    ]
    for item in carried:
        game.world.items.append(item)
        player.add_item(item)
    player.select_weapon(0, carried[0])
    player.select_weapon(1, carried[1])
    for item in carried[2:8]:
        player.equip(item)


def settle(game, clock, spot, frames, night=False):
    """Stand the player somewhere and let the world catch up with them. Night is wound round
    on the day/night clock rather than set as a flag, so everything reading darkness reads
    the number it would in play."""
    import core.constants as c

    game.player.x, game.player.y = spot
    game.world.daynight.elapsed_ms = c.DayNight.CYCLE_LENGTH_MS * (0.78 if night else 0.12)
    game.world.prepare(game.player)
    harness.step(game, clock, frames)


def tidy(game, keep_banner=False):
    """Give the stub's sentence-named places real names and clear whatever is still on
    screen from the last scene. A boss banner runs for four seconds, which is long enough
    to still be over the next shot."""
    from core.screen_fx import get_banner

    for index, village in enumerate(game.world.villages):
        village.name = VILLAGE_NAMES[index % len(VILLAGE_NAMES)]
    game.loot_notification.active = False
    if not keep_banner:
        get_banner().remaining_ms = 0.0


def save(game, out: Path, name: str):
    import pygame

    game._draw_frame()
    path = out / f"{name}.png"
    pygame.image.save(game.screen, str(path))
    print(f"wrote {path}")


def shoot_village(game, clock, out):
    settle(game, clock, VILLAGE, VILLAGE_SETTLE)
    tidy(game)
    save(game, out, "village")


def shoot_talk(game, clock, out):
    settle(game, clock, STARTING_TOWN, 200)
    npc = min(game.world.npcs, key=lambda n: math.dist((n.x, n.y), (game.player.x, game.player.y)), default=None)
    if npc is None:
        return
    npc.x, npc.y = game.player.x + 6, game.player.y - 58
    harness.step(game, clock, 2)
    game.dialogue_manager.interact_with_npc(npc, game.npc_name_generator, game.world)
    npc.name = NPC_NAME
    # The opening line is already in flight against the stub; drop it and write the
    # exchange straight into the history instead.
    game.dialogue_manager.generator = None
    game.dialogue_manager.waiting_for_llm = False
    history = game.dialogue_manager.conversation
    history.clear()
    for speaker, line in CONVERSATION:
        if speaker == "player":
            history.add_user_message(line)
        else:
            history.add_assistant_message(line)
    tidy(game)
    save(game, out, "talk")
    game.dialogue_manager.close()


# A shelf worth drawing, since the stub answers a shop prompt with the world context and a
# real one is a dozen calls away. Every ware is priced and named here; the rarity, the bonus
# and the final price are still the shop's own rolls (`NPC.add_stock`).
SHOP_STOCK = (
    ("Iron Longsword", "weapon", 90),
    ("Yew Hunting Bow", "weapon", 110),
    ("Studded Leather", "armor", 75),
    ("Oak Buckler", "shield", 55),
    ("Copper Bracelet", "accessory", 65),
    ("Throwing Bomb", "bomb", 40),
    ("Healing Potion", "potion", 18),
    ("Mana Draught", "potion", 22),
    ("Quiver of Arrows", "ammo", 30),
)


def shoot_shop(game, clock, out):
    """A merchant's shelf, the counter the loot economy is spent at. The stub model answers
    a shop prompt with the world context, so the wares are written here and only their
    rarity, their bonus and their price are rolled, exactly as a real shop's are."""
    settle(game, clock, STARTING_TOWN, 60)
    merchant = min(game.world.npcs, key=lambda n: math.dist((n.x, n.y), (game.player.x, game.player.y)), default=None)
    if merchant is None:
        return
    merchant.is_merchant = True
    merchant.name = MERCHANT_NAME
    merchant.set_shop([{"name": name, "item_type": kind, "price": price} for name, kind, price in SHOP_STOCK])
    game.shop_menu.open(merchant, game.player, game.world.items, game.world)
    game.active_menu = True
    tidy(game)
    save(game, out, "shop")
    game.shop_menu.close()
    game.active_menu = False


def shoot_fight(game, clock, out, cursor):
    import core.constants as c
    from game.entities.monsters import Monster

    settle(game, clock, WILDS, 120)
    player = game.player
    kinds = [kind for kind in c.MONSTER_KINDS if kind.min_distance <= 9000]
    # One under the cursor for the swing to land on, the rest closing in around.
    for index, (angle, radius) in enumerate(((0.05, 72), (-0.8, 210), (0.8, 190), (2.4, 240), (3.7, 270), (4.9, 230))):
        spot = (player.x + math.cos(angle) * radius, player.y + math.sin(angle) * radius)
        game.world.monsters.append(Monster(*spot, kinds[index % len(kinds)]))
    harness.step(game, clock, 22)
    cursor(1180, 380)
    game.world.handle_attack(player, game.dialogue_manager.quest_system, 0)
    harness.step(game, clock, 3)
    tidy(game)
    save(game, out, "fight")


def shoot_boss(game, clock, out, cursor):
    """A boss on the frame its climb out of the ground finishes, banner and all. Stood up
    well off, because it covers about 200 world units walking in while the banner is still
    fading up, and lands on top of the player from anywhere nearer."""
    import core.constants as c

    settle(game, clock, DEEP_WILDS, 120)
    brute = next(kind for kind in c.BOSS_KINDS if kind.archetype == "brute")
    boss = game.world.spawn_boss(game.player.x + 430, game.player.y - 60, template=brute, name=BOSS_NAME)
    cursor(1250, 400)
    harness.step(game, clock, BOSS_RISE_FRAMES)
    game.world.handle_attack(game.player, game.dialogue_manager.quest_system, 0)
    harness.step(game, clock, 3)
    tidy(game, keep_banner=True)
    save(game, out, "boss")
    game.world.bosses.remove(boss)


def shoot_cave(game, clock, out):
    tunnel = game.world.tunnel_at((7, 5), "cave")
    game.world._go_underground(game.player, tunnel)
    harness.step(game, clock, 30)
    walk_the_cave(game, clock, tunnel)
    scatter_hoard(game)
    harness.step(game, clock, 3)
    tidy(game)
    save(game, out, "cave")
    game.world.leave_tunnel(game.player)


def walk_the_cave(game, clock, tunnel):
    """Walk the first rooms rather than jumping between them: the map only remembers a cell
    the player has crossed into, so a cave arrived at draws as one lit circle with nothing
    behind it. Capped per leg, since a room centre the world will not let the player stand
    on is pushed straight back out by `unstick` every frame and never arrived at."""
    player = game.player
    for target in [room.center for room in tunnel.rooms[:3]]:
        for _ in range(300):
            dx, dy = target[0] - player.x, target[1] - player.y
            length = math.hypot(dx, dy)
            if length <= 24:
                break
            player.x += dx / length * 24
            player.y += dy / length * 24
            harness.step(game, clock, 1)
    # Back a room, so what was walked is behind the player on the map rather than round them.
    player.x, player.y = tunnel.rooms[1].center
    harness.step(game, clock, 4)


def scatter_hoard(game):
    """Loot on the floor, in an arc off to one side rather than a ring: a hoard, not a drop.
    Laid outside `Player.MAGNET_RADIUS` and drawn a few frames later, or the magnet has the
    lot of it in the bag before the shutter."""
    from game.entities.items import Item

    player = game.player
    drops = (
        Item(0, 0, "Ancient Coffer", "lootbox", rarity="epic"),
        Item(0, 0, "Coins", "coins", quantity=180),
        Item(0, 0, "Runed Blade", "weapon", bonus=9, rarity="epic"),
        Item(0, 0, "Health Potion", "potion", rarity="rare"),
        Item(0, 0, "Silver Idol", "misc", rarity="rare"),
        Item(0, 0, "Gold Chalice", "misc", rarity="rare"),
    )
    for index, item in enumerate(drops):
        angle = -0.7 + index * 0.32
        reach = 155 + (index % 3) * 22
        item.x = player.x + math.cos(angle) * reach
        item.y = player.y + math.sin(angle) * reach
        game.world.items.append(item)


def shoot_inventory(game, out):
    game.inventory_menu.toggle()
    game.active_menu = True
    tidy(game)
    save(game, out, "inventory")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    import pygame

    opened = pygame.display.set_mode
    pygame.display.set_mode = lambda _size, *a, **kw: opened(GAME_SIZE, *a, **kw)

    def cursor(x, y):
        pygame.mouse.get_pos = lambda: (x, y)

    game, clock = harness.boot()
    kit_out(game)

    shoot_village(game, clock, args.out)
    shoot_talk(game, clock, args.out)
    shoot_shop(game, clock, args.out)
    shoot_fight(game, clock, args.out, cursor)
    shoot_boss(game, clock, args.out, cursor)
    shoot_cave(game, clock, args.out)
    shoot_inventory(game, args.out)

    game.world.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
