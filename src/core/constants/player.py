from dataclasses import dataclass


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

    SPEED: int = 5
    RUN_SPEED: int = 7

    INTERACTION_DISTANCE: int = 30
    # Loot is picked up from a bit farther out than an NPC is talked to: the prompt over a
    # dropped item should show while walking past it, not only when standing on it.
    PICKUP_DISTANCE: int = 70
    ATTACK_REACH: int = 17
    ATTACK_DAMAGE: int = 5

    # Weapons on the number-key bar. Deliberately short: the point is switching between a
    # couple of answers mid-fight, not carrying an armoury on the HUD.
    WEAPON_SLOTS: int = 3


@dataclass(frozen=True)
class Death:
    """Dying doesn't reload the save at the same spot with full HP for free: it costs
    coins and leaves the player weakened for a while after respawning at world spawn.

    The weakness is meant to reshape the next few minutes rather than tickle them: a
    third of the run's coins gone, and three minutes of hitting softer, moving slower
    and carrying less health. A fire or an inn bed is what shakes it off early."""

    COIN_LOSS_PCT: float = 0.45
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
    FALLBACK_TAUNTS: tuple = (
        "The worms send their thanks.",
        "Even the crows looked away.",
        "That was over quickly.",
        "The world will manage without you.",
    )


@dataclass(frozen=True)
class Stats:
    # Character progression is use-based: every stat starts at level 1 and gains XP
    # from a matching action. Effects are pure functions of the level, so growing a
    # stat never touches the save format.
    NAMES: tuple = ("strength", "resistance", "speed", "vitality", "bartering", "persuasion")

    # XP needed for level 1 -> 2, scaled by XP_GROWTH for each further level.
    BASE_XP: float = 35.0
    XP_GROWTH: float = 1.45

    # Combat stats level from very frequent actions (per hit, per frame moved) compared
    # to persuasion/bartering, so they get an extra multiplier on top of the shared curve.
    COMBAT_STAT_NAMES: tuple = ("strength", "resistance", "speed", "vitality")
    COMBAT_XP_GROWTH_MULTIPLIER: float = 3.0

    # Effect increment per level above 1.
    STRENGTH_PER_LEVEL: int = 2  # flat attack damage
    RESISTANCE_PER_LEVEL: int = 1  # flat damage reduction
    SPEED_PER_LEVEL: float = 0.04  # +4% move speed
    VITALITY_HP_PER_LEVEL: int = 15  # extra max HP
    VITALITY_REGEN_PER_LEVEL: float = 0.0001
    BARTER_PER_LEVEL: float = 0.03  # 3% better prices per level

    # Quest reward weight shifted from "rare" to "legendary" per level above 1, capped so
    # even a maxed-out persuasion character still sees a legendary reward well under a
    # fifth of the time, rather than persuasion alone trivialising legendary drop odds.
    PERSUASION_WEIGHT_SHIFT_PER_LEVEL: float = 0.8
    PERSUASION_MAX_WEIGHT_SHIFT: float = 10.0

    # Effect per point of an equipped accessory's bonus, on top of trained stats.
    ACCESSORY_SPEED_PER_BONUS: float = 0.01  # +1% move speed per bonus point
    ACCESSORY_REGEN_PER_BONUS: float = 0.0005  # extra HP regen per bonus point
    ACCESSORY_LUCK_PER_BONUS: float = 0.01  # +1% better prices per bonus point
    ACCESSORY_CRIT_PER_BONUS: float = 0.012  # +1.2% crit chance per bonus point
    ACCESSORY_LIFESTEAL_PER_BONUS: float = 0.01  # +1% of damage healed per bonus point
    ACCESSORY_COINFIND_PER_BONUS: float = 0.06  # +6% coins from loot per bonus point
    ACCESSORY_XP_PER_BONUS: float = 0.04  # +4% xp from all actions per bonus point

    # Shops buy loot below its worth; bartering raises the fraction toward SELL_CEILING.
    SELL_BASE: float = 0.6
    # Prices can move at most this far from their base value.
    BUY_FLOOR: float = 0.5
    SELL_CEILING: float = 1.4

    # XP granted per action.
    XP_PER_HIT: float = 4.0
    XP_PER_DAMAGE_TAKEN: float = 2.0
    XP_PER_KILL: float = 8.0
    XP_PER_RUN_FRAME: float = 0.015
    XP_PER_TALK: float = 6.0  # persuasion
    XP_PER_TALK_BARTERING: float = 1.5  # small bartering trickle from talking
    XP_PER_TRADE: float = 8.0  # bartering, per shop buy/sell


# Display name per Stats.NAMES key, shared by the stats menu and the level-up popup.
STAT_LABELS: dict[str, str] = {
    "strength": "Strength",
    "resistance": "Resistance",
    "speed": "Speed",
    "vitality": "Vitality",
    "bartering": "Bartering",
    "persuasion": "Persuasion",
}


@dataclass(frozen=True)
class Affinity:
    # Per-NPC relationship level. Starts neutral, moves from concrete player
    # actions toward that NPC rather than an LLM judgment of conversation tone.
    START: float = 50.0
    MIN: float = 0.0
    MAX: float = 100.0

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
