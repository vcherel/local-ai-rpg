from dataclasses import dataclass


@dataclass(frozen=True)
class Shield:
    """The offhand shield and the guard it holds (game/entities/player.py).

    A shield is worn in its own slot and raised by holding the block key. Raised, it eats
    a share of any hit coming from the front and drains the guard meter by what it stopped;
    run the meter out and the guard breaks, leaving the player wide open for a moment. So a
    shield rewards blocking the blow you saw coming, not standing behind it forever.
    """

    BLOCK_BASE: float = 0.45  # fraction of a frontal hit stopped by a plain shield
    BLOCK_PER_BONUS: float = 0.03  # ...plus this per point of the shield's bonus
    BLOCK_MAX: float = 0.85
    # Only hits arriving within this cone of the player's facing are blocked at all.
    ARC_DEG: float = 150.0
    SPEED_MULT: float = 0.55  # movement while the shield is up

    GUARD_MAX: float = 60.0
    GUARD_REGEN_PER_S: float = 12.0
    # Guard only comes back once the shield has been down (or unhit) this long.
    GUARD_REGEN_DELAY_MS: int = 1200
    # Running the guard out breaks it: no blocking at all until this passes.
    GUARD_BREAK_MS: int = 2500
    GUARD_BREAK_SHAKE: float = 12.0


@dataclass(frozen=True)
class Projectile:
    SPEED: int = 14
    # How far a shot carries. The player's bow reaches most of the way across the screen,
    # which is the whole point of carrying one: an archer picks its fight at a distance and
    # pays for it in damage per hit. A monster's shot deliberately falls short of that, so
    # closing the gap on an archer stays the answer rather than a foot race under fire.
    RANGE: int = 980
    MONSTER_RANGE: int = 700
    SIZE: int = 6


@dataclass(frozen=True)
class Combat:
    CRIT_MULT: float = 1.8
    # Extra screen shake added on top of a weapon's base shake when a hit crits.
    CRIT_SHAKE_BONUS: float = 6.0
    PLAYER_HURT_SHAKE: float = 5.0
    # Kick when a shop crate is smashed.
    CRATE_SHAKE: float = 5.0
    # Softer kicks for the smaller outdoor breaks: a decorative pot/bush, or a window pane.
    DECOR_BREAK_SHAKE: float = 3.0
    WINDOW_SHAKE: float = 3.5
    # Camera never shakes more than this, so heavy hits stay readable rather than nauseating.
    MAX_SHAKE: float = 30.0
    SHAKE_DECAY: float = 0.82  # per-60fps-frame multiplier

    # Hit-stop: gameplay dt is multiplied by this for a few frames after a heavy hit,
    # a near-freeze that sells impact without new animation work.
    HITSTOP_SLOW_FACTOR: float = 0.06
    HITSTOP_CRIT_MS: float = 45.0
    HITSTOP_KILL_MS: float = 55.0
    HITSTOP_BOSS_MS: float = 110.0

    # Player-hurt screen vignette: triggered amount decays back to 0 at this rate.
    VIGNETTE_DECAY: float = 0.90  # per-60fps-frame multiplier
    PLAYER_HURT_VIGNETTE: float = 0.7

    # A cleaving swing does not hit everything it reaches equally. What stands where the
    # weapon is pointed takes it all; what is caught at the edge of the arc or at the end of
    # the reach takes as little as CLEAVE_MIN of it. So a cleave is worth swinging into a
    # crowd and still worth aiming, and the falling damage numbers say which was which.
    CLEAVE_MIN: float = 0.4
    # How much of the loss comes from being off to one side, the rest from being far out.
    CLEAVE_ANGLE_SHARE: float = 0.55

    # The arc drawn along a swing (core/swing_arcs.py). It spans the weapon's `arc_deg`
    # at its `reach`, so a cleaving sweep visibly covers the crowd it is about to hit.
    SWING_ARC_MS: float = 170.0
    SWING_ARC_WIDTH: int = 7
    SWING_ARC_COLOR: tuple = (235, 235, 220)
    SWING_ARC_CLEAVE_COLOR: tuple = (255, 210, 130)


@dataclass(frozen=True)
class Explosion:
    """A powder keg going off (game/combat.py `explode`).

    The one thing in the world that kills a crowd without a swing: the player shoots or
    smashes a keg standing in the middle of one. It hurts whoever is near it, the player
    included, so it is a decision rather than free damage.
    """

    RADIUS: float = 165.0
    DAMAGE: int = 55
    # Damage falls off from full at the centre to this share of it at the rim.
    EDGE_DAMAGE_FRAC: float = 0.35
    # The blast is not choosy: it takes this much of its damage off the player too.
    PLAYER_DAMAGE_MULT: float = 0.7
    KNOCKBACK: float = 34.0
    SHAKE: float = 22.0
    # A keg inside the blast of another one goes off as well, which is what makes a
    # cluster of them worth lining up.
    CHAIN_RADIUS: float = 150.0


@dataclass(frozen=True)
class DamageFx:
    """How a prop that has been hit but not yet broken shows it (core/damage_fx.py)."""

    # A struck prop flinches away from the blow and flashes, for this long.
    FLASH_MS: float = 130.0
    FLASH_OFFSET: float = 3.0
    FLASH_COLOR: tuple = (255, 240, 210)
    # Cracks drawn over a damaged hard prop: none at full health, this many at a sliver.
    MAX_CRACKS: int = 4
    CRACK_COLOR: tuple = (38, 26, 18)


@dataclass(frozen=True)
class WeaponArchetype:
    """Feel profile for a weapon family, resolved from the weapon name's keyword.

    Multipliers apply to the base melee values (`Player.ATTACK_REACH/ATTACK_DAMAGE`,
    `Entities.SWING_SPEED`). `shake` and `knockback` are in world pixels.
    """

    name: str
    reach_mult: float
    # Polearm blind spot: a living target whose centre is closer than this many world
    # pixels to the player is missed entirely, so a spear hits at the end of its shaft
    # instead of stabbing something pressed against the player's chest. 0 disables it.
    min_hit_distance: float
    swing_mult: float  # >1 swings faster (cosmetic animation speed)
    damage_mult: float
    cooldown_ms: int  # minimum time between swings
    knockback: float  # pixels the target is shoved on a hit
    crit_chance: float
    cleave: bool  # hit every target in the swing radius, not just the nearest
    cleave_radius_mult: float  # widens the hit radius for cleave weapons
    shake: float  # base screen shake on a hit
    ranged: bool  # fires a projectile instead of swinging
    uses_ammo: bool  # ranged weapons only: consume an ammo item per shot
    # The wedge a swing actually covers, measured across the facing. It is both what the
    # arc drawn on screen spans and what the hit test accepts, so the picture never
    # promises a reach the swing does not have. A cleaving weapon sweeps wide; a thrust
    # or a poke covers a narrow slice of the same disc.
    arc_deg: float = 100.0


UNARMED = WeaponArchetype("unarmed", 1.0, 0.0, 1.0, 1.0, 350, 8, 0.08, False, 1.0, 2.0, False, False, 90.0)

WEAPON_ARCHETYPES: dict[str, WeaponArchetype] = {
    "dagger": WeaponArchetype("dagger", 0.8, 0.0, 1.8, 0.7, 180, 4, 0.30, False, 1.0, 2.0, False, False, 90.0),
    "sword": WeaponArchetype("sword", 1.0, 0.0, 1.0, 1.0, 350, 10, 0.12, True, 1.4, 4.0, False, False, 130.0),
    "axe": WeaponArchetype("axe", 1.05, 0.0, 0.7, 1.25, 520, 14, 0.10, True, 1.8, 7.0, False, False, 160.0),
    # The hammer earns its 620ms cooldown by clearing a crowd: a wide, slow sweep that
    # catches everything in front of it rather than one target at a time.
    "hammer": WeaponArchetype("hammer", 0.9, 0.0, 0.55, 1.6, 620, 26, 0.05, True, 1.5, 14.0, False, False, 150.0),
    # The spear trades the whole close range for reach and a heavy thrust: nothing within
    # 46px of the player is hit at all, and the ring it does cover runs out past 85px.
    "spear": WeaponArchetype("spear", 2.2, 46.0, 0.9, 1.35, 380, 14, 0.12, False, 1.0, 5.0, False, False, 75.0),
    "staff": WeaponArchetype("staff", 1.0, 0.0, 1.0, 1.0, 420, 6, 0.10, False, 1.0, 2.0, True, False, 90.0),
    "bow": WeaponArchetype("bow", 1.0, 0.0, 1.0, 1.0, 400, 4, 0.10, False, 1.0, 1.0, True, True, 90.0),
}

# Weapon-name keyword -> archetype key. Keywords mirror items.WEAPON_KEYWORDS.
_KEYWORD_TO_ARCHETYPE = {
    "dagger": "dagger",
    "knife": "dagger",
    "sword": "sword",
    "blade": "sword",
    "axe": "axe",
    "club": "hammer",
    "mace": "hammer",
    "hammer": "hammer",
    "spear": "spear",
    "lance": "spear",
    "staff": "staff",
    "bow": "bow",
}


def weapon_archetype(name: str | None) -> WeaponArchetype:
    """Resolve a weapon name to its feel profile; generic/unknown weapons swing like a sword."""
    if not name:
        return UNARMED
    lower = name.lower()
    for keyword, key in _KEYWORD_TO_ARCHETYPE.items():
        if keyword in lower:
            return WEAPON_ARCHETYPES[key]
    return WEAPON_ARCHETYPES["sword"]


@dataclass(frozen=True)
class Decals:
    """Blood splats left on the ground by hits and kills (core/decals.py)."""

    LIFE_MS: float = 18_000.0
    # Oldest decal is dropped once the list grows past this, so a long fight
    # never leaves an unbounded number of splats to draw.
    MAX_COUNT: int = 300

    HIT_RADIUS: int = 7
    KILL_RADIUS: int = 22
    BOSS_KILL_RADIUS: int = 38
    PLAYER_HURT_RADIUS: int = 11

    # A kill throws a fan of droplets out along the killing blow rather than leaving one
    # tidy circle: the pool marks where it died, the spray says how it went.
    SPRAY_SPREAD_DEG: float = 110.0
    KILL_SPRAY_COUNT: int = 10
    KILL_SPRAY_DISTANCE: tuple = (16.0, 105.0)
    KILL_SPRAY_RADIUS: tuple = (3.0, 9.0)
    # A boss bleeds across half the arena.
    BOSS_SPRAY_COUNT: int = 24
    BOSS_SPRAY_DISTANCE: tuple = (25.0, 210.0)
    BOSS_SPRAY_RADIUS: tuple = (5.0, 15.0)
    # Deep arterial red, darker than the bright particle spray so the two read as
    # "still in the air" versus "already on the ground".
    BLOOD_COLOR: tuple = (128, 16, 16)
