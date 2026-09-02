from dataclasses import dataclass

from core.constants.ui import Screen


@dataclass(frozen=True)
class Player:
    HP: int = 100
    # Passive regen is a slow between-fights trickle, not a heal button: it only starts
    # REGEN_DELAY_MS after the last hit taken, so a fight is won with potions, lifesteal
    # and positioning rather than by backing off for two seconds. A regen potion is
    # deliberately exempt from the delay, it's what you drink when you're already hurt.
    REGEN_RATE: float = 0.00025
    REGEN_DELAY_MS: int = 12000
    SIZE: int = 30

    # Walking and running pace, in pixels per frame at TARGET_FPS. Deliberately unhurried:
    # the world is read at this speed, a monster is outrun by a small margin rather than
    # left standing, and a shove or a root costs real ground because ground is expensive.
    SPEED: float = 4.0
    RUN_SPEED: float = 5.6

    # Where the player's own health bar hangs under the body, and how tall it is. Read by
    # `Player.draw` and by everything the HUD stacks around it (the potion quickbar above,
    # the mana and guard bars below), so the stack moves as one rather than off three
    # copies of the same number.
    HEALTH_BAR_OFFSET: int = 330
    HEALTH_BAR_HEIGHT: int = 30
    HEALTH_BAR_WIDTH: int = 800

    INTERACTION_DISTANCE: int = 30
    # Loot is not picked up by a key at all: anything lying within MAGNET_RADIUS flies to
    # the player and is collected on contact. It starts slow and accelerates well past
    # running pace, so it always catches up rather than trailing behind for ever, and the
    # speeds are per-frame pixels at TARGET_FPS like every other movement number.
    MAGNET_RADIUS: int = 130
    MAGNET_SPEED_START: float = 1.5
    MAGNET_SPEED_MAX: float = 14.0
    MAGNET_ACCEL: float = 0.03  # per millisecond
    MAGNET_CATCH: int = 16  # close enough to count as collected
    ATTACK_REACH: int = 17
    ATTACK_DAMAGE: int = 5
    # How long the player's arm is out for. Theirs is a flick rather than a wind-up: the
    # blow is resolved on the click that asked for it (`WorldCombat.handle_attack`) and the
    # cooldown of whatever they are holding is what paces them, so the animation only has to
    # keep up with the fastest weapon in the game. What an enemy swings is the other thing
    # entirely (`Entities.SWING_MS` and the cadence each of them carries).
    SWING_MS: float = 145.0

    # The player has two weapon hands, one weapon in each: hand one is the left mouse
    # button, hand two the right. Key 1 swaps the two over, so a fight is fought out of the
    # two answers chosen before it started.
    HANDS: int = 2


@dataclass(frozen=True)
class Magic:
    """The mana a staff spends (game/projectiles.py `_fire_ranged`).

    A staff used to be the only weapon in the game with no cost at all: no ammo to buy, no
    swing to close the distance for, so carrying one made every other family a worse choice.
    Mana is that cost. It is a pool rather than a stock: it comes back on its own, so magic
    is paced instead of rationed, and what decides how deep and how fast is the magic stat.
    """

    # Pool at magic level 1, and what one bolt costs out of it. Two casts and a little,
    # so a wand found in the first hour is an opening move rather than the whole answer:
    # the untrained caster fires, then has to close or run while the pool comes back.
    POOL: int = 34
    BOLT_COST: int = 14
    # Mana per millisecond, held off for REGEN_DELAY_MS after the last cast so emptying the
    # pool is felt: a staff carries a fight, it does not carry it alone. At level 1 a bolt
    # costs about three and a half seconds of standing there, which is a whole fight's worth
    # of decision; the magic stat is what buys that time back.
    REGEN_RATE: float = 0.004
    REGEN_DELAY_MS: int = 1400
    BAR_COLOR: tuple = (120, 150, 255)
    EMPTY_COLOR: tuple = (150, 120, 220)
    # The pool drawn as a second bar under the health bar, always shown: a bolt that does
    # not come out because the pool is empty must be something the player saw coming. Sized
    # off the screen rather than in bare pixels, since it is centred on it.
    BAR_WIDTH: int = Screen.WIDTH * 4 // 9
    BAR_HEIGHT: int = 14


@dataclass(frozen=True)
class Death:
    """Dying doesn't reload the save at the same spot with full HP for free: it costs
    coins and things carried, and leaves the player weakened for a while after respawning
    at world spawn.

    Nothing dying takes is destroyed: the coins and the items land on the ground where the
    body fell, and the walk back out to fetch them is the real price. The minimap keeps the
    spot until the player is standing on it again.

    The weakness is meant to reshape the next few minutes rather than tickle them: hitting
    softer, moving slower and carrying less health. It is worst on the frame the player
    stands back up and eases off to nothing over DEBUFF_DURATION_S, so the multipliers below
    are what the penalty is at its worst rather than a flat state that snaps off at the end.
    A fire or an inn bed is what shakes it off early."""

    # The share of the purse left behind, rolled per death so a death is never a sum the
    # player can do in their head before it happens.
    COIN_LOSS_RANGE: tuple = (0.3, 0.5)
    # How many things fall out of the bag with it. Anything carried can go, equipped
    # included: a weapon left lying in the wilds is what makes the walk back matter.
    DROP_ITEMS: tuple = (1, 3)
    # How far the drop scatters around the spot, so it reads as things falling rather than
    # as one pile.
    DROP_SCATTER: float = 26.0
    DEBUFF_DURATION_S: float = 180.0
    DEBUFF_DAMAGE_MULT: float = 0.6
    DEBUFF_SPEED_MULT: float = 0.85
    DEBUFF_MAX_HP_MULT: float = 0.8
    # How long the death screen holds before the player is put back at world spawn.
    RESPAWN_DELAY_S: float = 2.5

    # Nothing lands on the player for this long after they spawn or respawn, so a death can
    # never chain into the next one before they have their bearings. It ends the moment they
    # swing or shoot: the window is there to get out of trouble, not to open a fight for free.
    SPAWN_GRACE_S: float = 3.0

    # The death screen mocks the player with an LLM-written line. Generated ahead of time
    # into a buffer (llm/death_taunts.py), because the screen is blocking and waiting on
    # the model there would turn a death into a stall; these are what it says if the
    # buffer is empty (a fresh save, or the model still busy with the first one).
    TAUNT_BUFFER: int = 3
    # The canned death-screen lines, used whenever the model has not written one ahead of
    # need. One tier per death milestone (`Milestones.DEATHS`): the first is there from the
    # first death and the rest are unlocked by dying, so a player who keeps dying is mocked
    # in more ways rather than the same four ways. `Record.taunt_pool` is what assembles it.
    TAUNT_TIERS: tuple = (
        (
            "The worms send their thanks.",
            "Even the crows looked away.",
            "That was over quickly.",
            "The world will manage without you.",
        ),
        (
            "Again? The ground here knows your shape by now.",
            "You are getting good at this part.",
            "Nobody is counting. That is a lie, something is.",
        ),
        (
            "The gravediggers have stopped asking your name.",
            "Even the wolves have started to feel bad about it.",
            "You have died more times than most people have travelled.",
        ),
        (
            "There is a song about you. It is short and it is unkind.",
            "Death has begun leaving the door open for you.",
            "You are less an adventurer than a recurring event.",
        ),
    )


@dataclass(frozen=True)
class Milestones:
    """What the playthrough tally pays out at (game/record.py).

    Quests pay in loot, deaths pay in words: crossing a quest milestone opens a lootbox of
    the named rarity, crossing a death milestone unlocks the next tier of `Death.TAUNT_TIERS`.
    Both are deliberately sparse. A reward every third quest is a salary; a reward at the
    tenth is something to remember.
    """

    QUESTS: tuple = ((3, "rare"), (10, "epic"), (25, "epic"), (50, "legendary"), (100, "legendary"))
    DEATHS: tuple = (3, 10, 25)


@dataclass(frozen=True)
class Stats:
    # Character progression is use-based: every stat starts at level 1 and gains XP
    # from a matching action. Effects are pure functions of the level, so growing a
    # stat never touches the save format.
    NAMES: tuple = (
        "strength",
        "resistance",
        "speed",
        "vitality",
        "magic",
        "bartering",
        "persuasion",
        "swimming",
    )

    # XP needed for level 1 -> 2, scaled by XP_GROWTH for each further level.
    BASE_XP: float = 35.0
    XP_GROWTH: float = 1.45

    # Combat stats level from very frequent actions (per hit, per frame moved) compared
    # to persuasion/bartering, so they get an extra multiplier on top of the shared curve.
    COMBAT_STAT_NAMES: tuple = ("strength", "resistance", "speed", "vitality", "magic")
    COMBAT_XP_GROWTH_MULTIPLIER: float = 3.0

    # Effect increment per level above 1.
    STRENGTH_PER_LEVEL: int = 2  # flat attack damage
    RESISTANCE_PER_LEVEL: int = 1  # flat damage reduction
    SPEED_PER_LEVEL: float = 0.04  # +4% move speed
    VITALITY_HP_PER_LEVEL: int = 15  # extra max HP
    VITALITY_REGEN_PER_LEVEL: float = 0.0001
    # Magic is strength's opposite number and nothing about it overlaps: a bolt's damage
    # comes off this ladder instead of strength's, and the same level also buys the pool it
    # is spent from and how fast that pool comes back. So a caster is built by casting, and
    # a swordsman picking up a staff is holding a beginner's weapon.
    MAGIC_DAMAGE_PER_LEVEL: int = 3  # flat damage on anything a staff puts in the air
    MAGIC_POOL_PER_LEVEL: int = 10  # extra mana
    MAGIC_REGEN_PER_LEVEL: float = 0.0014  # extra mana per millisecond
    BARTER_PER_LEVEL: float = 0.03  # 3% better prices per level
    # How much of the water penalty each level of swimming buys back, from Scenery.SWIM_SPEED
    # toward SWIM_SPEED_MAX. The only stat with no effect on land: it turns a river from a
    # barrier into a shortcut, and it never quite matches walking, so a bridge keeps its job.
    SWIM_PER_LEVEL: float = 0.05

    # Quest reward weight shifted from "rare" to "legendary" per level above 1, capped so
    # even a maxed-out persuasion character still sees a legendary reward well under a
    # fifth of the time, rather than persuasion alone trivialising legendary drop odds.
    PERSUASION_WEIGHT_SHIFT_PER_LEVEL: float = 0.8
    PERSUASION_MAX_WEIGHT_SHIFT: float = 10.0

    # Effect per point of an equipped accessory's bonus, on top of trained stats.
    ACCESSORY_SPEED_PER_BONUS: float = 0.01  # +1% move speed per bonus point
    ACCESSORY_REGEN_PER_BONUS: float = 0.0005  # extra HP regen per bonus point
    # Luck leans the rarity ladder up (items.roll_rarity): each step is this much more
    # likely per bonus point, so 5 points roughly doubles the odds of a legendary. It is
    # deliberately not a price effect any more, that being what bartering is for.
    ACCESSORY_LUCK_PER_BONUS: float = 0.05
    ACCESSORY_CRIT_PER_BONUS: float = 0.012  # +1.2% crit chance per bonus point
    ACCESSORY_LIFESTEAL_PER_BONUS: float = 0.01  # +1% of damage healed per bonus point
    ACCESSORY_COINFIND_PER_BONUS: float = 0.06  # +6% coins from loot per bonus point
    ACCESSORY_XP_PER_BONUS: float = 0.04  # +4% xp from all actions per bonus point

    # Shops buy loot below its worth; bartering raises the fraction toward SELL_CEILING.
    # Deliberately punishing: hoovering every rusty dagger into the nearest shop used to be
    # the fattest income in the game, which made quests, caches and risk pointless.
    SELL_BASE: float = 0.35
    # Prices can move at most this far from their base value. A shop never pays what a
    # thing is worth, however good a haggler the player becomes.
    BUY_FLOOR: float = 0.5
    SELL_CEILING: float = 0.8

    # XP granted per action.
    XP_PER_HIT: float = 4.0
    XP_PER_DAMAGE_TAKEN: float = 2.0
    XP_PER_KILL: float = 8.0
    XP_PER_RUN_FRAME: float = 0.015
    XP_PER_SWIM_FRAME: float = 0.06  # swimming, per frame moved in water
    XP_PER_CAST: float = 5.0  # magic, per bolt actually paid for
    XP_PER_TALK: float = 6.0  # persuasion
    XP_PER_TALK_BARTERING: float = 1.5  # small bartering trickle from talking
    XP_PER_TRADE: float = 8.0  # bartering, per shop buy/sell


# Display name per Stats.NAMES key, shared by the stats menu and the level-up popup.
STAT_LABELS: dict[str, str] = {
    "strength": "Strength",
    "resistance": "Resistance",
    "speed": "Speed",
    "vitality": "Vitality",
    "magic": "Magic",
    "bartering": "Bartering",
    "persuasion": "Persuasion",
    "swimming": "Swimming",
}


@dataclass(frozen=True)
class Affinity:
    # Per-NPC relationship level. Starts neutral, moves from concrete player
    # actions toward that NPC rather than an LLM judgment of conversation tone.
    START: float = 50.0
    MIN: float = 0.0
    MAX: float = 100.0
    # Where an NPC's affinity lands once their anger runs out. Well short of START: the
    # village stops swinging, it does not forget who swung first.
    FORGIVEN: float = 15.0

    # Affinity gained from completing this NPC's quest, and from each trade at
    # a merchant's shop.
    QUEST_COMPLETE_BONUS: float = 15.0
    TRADE_BONUS: float = 1.0

    # Quest reward weight shifted from "rare" to "legendary" per point of affinity
    # above START, capped like persuasion's shift.
    WEIGHT_SHIFT_PER_POINT: float = 0.9
    MAX_WEIGHT_SHIFT: float = 45.0

    # Shop buy/sell price swing between MIN and MAX affinity, on top of bartering.
    MAX_PRICE_SWING: float = 0.15
