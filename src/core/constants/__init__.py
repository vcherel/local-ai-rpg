"""Every tuning number in the game, grouped by what it tunes.

Split into one module per domain purely for size; the package is the flat namespace it
has always been, so `import core.constants as c` then `c.Player.HP` still works and no
call site knows which module a constant lives in. Adding a constant means picking the
module by subject, not appending to the end of one long file.

`Fonts` is the one entry rebound at runtime: `rpg_ai.__main__` replaces the class with a
loaded instance once pygame's font system is up, which works because every consumer reads
it off this package rather than importing the name directly.
"""

from core.constants.bestiary import (
    BOSS_KINDS,
    CRITTER_KINDS,
    CRITTER_KINDS_BY_NAME,
    MONSTER_KINDS,
    MONSTER_MAX_SIZE,
    Boss,
    BossKind,
    Charge,
    CritterKind,
    Entities,
    Flank,
    MonsterArt,
    MonsterKind,
    Wildlife,
)
from core.constants.combat import (
    UNARMED,
    WEAPON_ARCHETYPES,
    Combat,
    DamageFx,
    Decals,
    Explosion,
    Projectile,
    Shield,
    WeaponArchetype,
    weapon_archetype,
)
from core.constants.items import QUEST_COIN_BANDS, Affixes, LootBox, Potions, Quests, Rarity, RarityTier
from core.constants.player import STAT_LABELS, Affinity, Death, Player, Stats
from core.constants.ui import TARGET_FPS, Colors, Fonts, Hyperparameters, Minimap, Screen
from core.constants.world import (
    Breakables,
    Buildings,
    Crime,
    DayNight,
    Events,
    Fog,
    PointsOfInterest,
    Scenery,
    Traps,
    Tunnels,
    Villages,
    World,
)

__all__ = [
    "Affinity",
    "Affixes",
    "BOSS_KINDS",
    "Boss",
    "BossKind",
    "Breakables",
    "Buildings",
    "CRITTER_KINDS",
    "CRITTER_KINDS_BY_NAME",
    "Charge",
    "Colors",
    "Combat",
    "Crime",
    "CritterKind",
    "DamageFx",
    "DayNight",
    "Death",
    "Decals",
    "Entities",
    "Events",
    "Explosion",
    "Flank",
    "Fog",
    "Fonts",
    "Hyperparameters",
    "LootBox",
    "MONSTER_KINDS",
    "MONSTER_MAX_SIZE",
    "Minimap",
    "MonsterArt",
    "MonsterKind",
    "Player",
    "PointsOfInterest",
    "Potions",
    "QUEST_COIN_BANDS",
    "Quests",
    "Projectile",
    "Rarity",
    "RarityTier",
    "STAT_LABELS",
    "Scenery",
    "Screen",
    "Shield",
    "Stats",
    "TARGET_FPS",
    "Traps",
    "Tunnels",
    "UNARMED",
    "Villages",
    "WEAPON_ARCHETYPES",
    "WeaponArchetype",
    "Wildlife",
    "World",
    "weapon_archetype",
]
