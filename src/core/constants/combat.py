from dataclasses import dataclass, replace

from core.constants.player import Magic
from core.constants.ui import Screen


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
    # The shield is strapped to one side of the body rather than held out in front of it,
    # so where a blow arrives from matters as much as whether it came from the front: what
    # comes at the shield side is met squarely, what comes at the other is caught by its
    # edge. Turning the shield onto the blow is the whole skill of carrying one.
    SIDE_ARC_DEG: float = 120.0
    OFF_SIDE_MULT: float = 0.35
    # A raised shield turns a shot away instead of taking it, but only one arriving on the
    # shield side: the deflected arrow keeps flying, harmless, off the face of the shield.
    DEFLECT_COLOR: tuple = (200, 220, 255)
    # Turning a shot aside is not free: it comes out of the same guard meter a blow does,
    # so an archer can still wear a shield down.
    DEFLECT_GUARD_COST: float = 8.0
    SPEED_MULT: float = 0.55  # movement while the shield is up

    # The guard meter drawn just under the mana bar and only while a shield is carried. It
    # brightens while the block is up and turns red once the guard breaks, so the player can
    # see what holding block is costing them.
    GUARD_BAR_WIDTH: int = Screen.WIDTH * 2 // 9
    GUARD_BAR_HEIGHT: int = 10
    GUARD_BAR_COLOR: tuple = (90, 130, 175)
    GUARD_BAR_BLOCKING_COLOR: tuple = (150, 210, 255)
    GUARD_BAR_BROKEN_COLOR: tuple = (200, 70, 60)
    GUARD_BROKEN_TEXT_COLOR: tuple = (255, 150, 140)

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
    # And on the blow that finishes something off, so a kill lands harder than the four
    # hits that led to it.
    KILL_SHAKE_BONUS: float = 7.0
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
    # The white wash of a blast (core/screen_fx.py `ScreenFlash`) decays faster than the
    # vignette: it is a flashbulb, not an injury.
    FLASH_DECAY: float = 0.80
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

    # A thrust is a lane, not a wedge (`WeaponArchetype.pierce_melee`). Anything whose
    # centre is within this far of the line the weapon is pointed along, out to its reach
    # and past its blind spot, is skewered, so a spear standing off a pack is rewarded for
    # lining two of them up. Each body behind the first takes this much less of the blow.
    THRUST_LANE_WIDTH: float = 26.0
    THRUST_FALLOFF: float = 0.7

    # A shove is an impulse, not a teleport. A weapon's `knockback` is the ground the blow
    # is worth in total; the body is given a velocity that carries it exactly that far as it
    # decays (v0 = distance * (1 - KNOCKBACK_DECAY)), stepped every frame with collision like
    # any other movement. So the pole visibly throws somebody across a room and they slide to
    # a halt, instead of blinking to the far end of it.
    KNOCKBACK_DECAY: float = 0.82  # per-60fps-frame multiplier on the shove's velocity
    # Below this much velocity left the shove is over and the body is walking again.
    KNOCKBACK_REST_SPEED: float = 0.35
    # ...and above this much it is still going somewhere it did not choose: it keeps facing
    # and swinging, but its own step is skipped, which is the follow-through.
    KNOCKBACK_STAGGER_SPEED: float = 1.6
    # A shove worth this much ground kicks up dust where it started, so the impulse is seen
    # leaving the weapon rather than only read off the body's new position.
    KNOCKBACK_DUST_MIN: float = 18.0
    KNOCKBACK_DUST_COLOR: tuple = (190, 180, 165)
    THRUST_TRAIL_COLOR: tuple = (215, 230, 245)
    THRUST_TRAIL_WIDTH: int = 14
    # A thrust is drawn as a lunge rather than a line: the head drives out to the end of the
    # lane over the first part of its life, the shaft stretches behind it, and the whole
    # thing outlives a sweep slightly, because reach is the spear's entire argument.
    THRUST_MS: float = 260.0
    THRUST_DRIVE_FRAC: float = 0.42
    THRUST_HEAD: float = 34.0
    THRUST_CORE_COLOR: tuple = (255, 255, 255)
    THRUST_WIND_SPREAD: float = 13.0
    THRUST_DUST: int = 9
    # How far the player is carried forward by their own thrust.
    THRUST_LUNGE: float = 18.0


@dataclass(frozen=True)
class Bombs:
    """The two things the player can carry that go off (game/entities/bomb.py).

    A bomb is the powder keg made portable: both kinds end in `WorldCombat.explode`, so
    what they do to a crowd, to the gore on the ground and to a village's temper is
    already decided and nothing here has to restate it. What separates them is when they
    go off. A mine is laid on the ground and waits for somebody to walk onto it, which is
    a piece of ground chosen in advance; a grenade is thrown at where the player is aiming
    and burns a fuse in the air, which is a fight answered right now.

    Both are consumables held in a weapon position: clicking spends one, and an empty
    position is bare hands like any other.
    """

    # A grenade travels at this many pixels per frame at TARGET_FPS and stops where it was
    # aimed, or at the first wall: it is thrown, so it never carries as far as a bow.
    THROW_SPEED: float = 9.0
    THROW_RANGE: float = 300.0
    FUSE_MS: int = 900
    # A grenade is airborne, not slid along the ground: it climbs to this height at the
    # midpoint of its throw and comes back down to land where it was aimed. Below
    # CLEARANCE_HEIGHT it is read as close enough to the ground for a wall to stop it;
    # above it, it is in the air and clears a low wall or a fence on the way over.
    ARC_HEIGHT: float = 46.0
    CLEARANCE_HEIGHT: float = 14.0

    # A mine is not live the instant it leaves the hand: the player has to be able to lay
    # one and step off it.
    ARM_MS: int = 900
    TRIGGER_RADIUS: float = 34.0
    # A laid mine is the player's own, so their own step never sets it off. What does is
    # anything that would fight them.
    MINE_LIFETIME_MS: int = 240_000

    RADIUS: float = 165.0
    DAMAGE: int = 62
    KNOCKBACK: float = 80.0
    SHAKE: float = 26.0
    # The player is standing further from their own grenade than from a keg they smashed,
    # but not far enough for it to be free.
    PLAYER_DAMAGE_MULT: float = 0.6

    # A bomb is not a weapon that can be spammed: the throw has the cadence of a heavy
    # swing, and the player has to live in the couple of seconds after it.
    COOLDOWN_MS: int = 700

    # What a merchant asks for one, before rarity: a bomb is expensive on purpose, since
    # it answers a crowd the way nothing else the player carries does.
    BASE_VALUE: int = 45

    BODY_COLOR: tuple = (58, 56, 62)
    FUSE_COLOR: tuple = (255, 190, 90)
    ARMED_COLOR: tuple = (255, 80, 60)
    SIZE: int = 13


@dataclass(frozen=True)
class Trees:
    """Felling a tree (game/combat.py `_swing_at_scenery`, game/entities/scenery.py).

    A wood is the one piece of scenery the player can argue with. A tree takes real work to
    bring down, an axe does that work several times faster than anything else, and what is
    left is a stump: no longer a wall to walk around, no longer a canopy to hide under, and
    a couple of logs on the ground worth what somebody in a village will pay for them.

    Which trees have been felled is the one thing about the wilderness the world remembers
    (`World.felled`), since everything else about a chunk is rolled from its seed.
    """

    HP: int = 90
    # What the swing counts for: an axe is what a tree is felled with, everything else is
    # somebody hitting a tree with the wrong thing.
    AXE_MULT: float = 3.0
    OTHER_MULT: float = 0.6
    HIT_RADIUS: int = 26
    # Logs left lying where it came down.
    LOG_DROPS: tuple = (1, 2)
    XP_PER_FELL: float = 3.0
    # How long the trunk takes to come down, and how far the canopy leans as it goes.
    FALL_MS: int = 700
    FALL_SHAKE: float = 14.0
    STUMP_COLOR: tuple = (96, 72, 48)


@dataclass(frozen=True)
class Boulders:
    """Breaking a boulder (game/combat.py `_smash_boulder`, game/entities/scenery.py).

    The second thing in the wilderness the player can argue with, and written the same way
    a tree is: a real pool of hit points, one weapon family that does the work properly
    (a hammer here, an axe there), a few stones left on the ground and a wreck that the
    world remembers (`World.smashed`) so the rock is still broken when the chunk streams
    back in.
    """

    HP: int = 130
    # A blunt weapon is what rock gives to; an edge chips at it.
    HAMMER_MULT: float = 3.0
    OTHER_MULT: float = 0.5
    HIT_RADIUS: int = 34
    STONE_DROPS: tuple = (1, 3)
    XP_PER_SMASH: float = 4.0
    SHAKE: float = 12.0
    RUBBLE_COLOR: tuple = (134, 130, 120)


@dataclass(frozen=True)
class Woodpile:
    """Breaking the firewood stacked against a house (game/combat.py `_chop_woodpile`,
    game/entities/buildings.py `woodpile_rect`).

    The one exterior extra of a building that stands in the way, so it is the one that has
    to answer a weapon: a prop the player cannot walk through and cannot take apart is a
    wall nobody put there. It is stacked wood rather than a tree, so it gives sooner than a
    trunk and pays the same way, in logs. Which piles are gone is kept on the building
    itself, beside its broken windows, since a house is saved and never rolled again.
    """

    HP: int = 45
    # An axe is what firewood was cut with in the first place; anything else is blunt work.
    AXE_MULT: float = 3.0
    OTHER_MULT: float = 0.8
    HIT_RADIUS: int = 22
    LOG_DROPS: tuple = (1, 2)
    XP_PER_BREAK: float = 2.0
    COLOR: tuple = (104, 78, 50)


@dataclass(frozen=True)
class Explosion:
    """A powder keg going off (game/combat.py `explode`).

    The one thing in the world that kills a crowd without a swing: the player shoots or
    smashes a keg standing in the middle of one. It hurts whoever is near it, the player
    included, so it is a decision rather than free damage.
    """

    RADIUS: float = 200.0
    DAMAGE: int = 55
    # Damage falls off from full at the centre to this share of it at the rim.
    EDGE_DAMAGE_FRAC: float = 0.35
    # The blast is not choosy: it takes this much of its damage off the player too.
    PLAYER_DAMAGE_MULT: float = 0.7
    KNOCKBACK: float = 90.0
    SHAKE: float = 20.0
    # A blast is the loudest thing that happens in this game, and it says so where it went
    # off rather than over the whole screen: the fire, the smoke and the debris are at the
    # blast, the shockwave carries a little past what it hurt, and the wash and the freeze
    # are a beat rather than a whiteout. It used to take the screen away from the player at
    # the exact moment they had a fight to read.
    HITSTOP_MS: float = 90.0
    # Ring radii as a share of the blast, drawn outward: the damage ring, then the
    # shockwave carrying past what it hurt.
    RING_FRACS: tuple = (1.0, 1.35)
    RING_COLORS: tuple = ((255, 220, 150), (200, 130, 60))
    FLASH_AMOUNT: float = 0.22
    FLASH_COLOR: tuple = (255, 225, 180)
    FIRE_PARTICLES: int = 45
    SMOKE_PARTICLES: int = 28
    DEBRIS_PARTICLES: int = 20
    # A keg inside the blast of another one goes off as well, which is what makes a
    # cluster of them worth lining up.
    CHAIN_RADIUS: float = 150.0
    # How far a chain may run before it stops, so a shipment of kegs cannot recurse without
    # end. Counted in blasts, not in kegs: one blast may set off several at once.
    MAX_CHAIN_DEPTH: int = 3


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
class ImpactFx:
    """The wave an area effect throws out, and the bolts naming what it caught
    (core/impact_fx.py)."""

    RING_MS: float = 320.0
    # The wave: particles scattered round the source out to the radius the damage covered,
    # rather than one drawn circle, which reads as a HUD element over the fight.
    WAVE_PER_PIXELS: float = 7.0
    WAVE_MIN: int = 8
    # How far in from the edge the scatter starts, as a fraction of the radius.
    WAVE_INNER: float = 0.55
    WAVE_SPEED: float = 4.5
    WAVE_LIFE_MS: int = 420
    WAVE_SIZE: int = 5
    CORE_PARTICLES: int = 8
    # The bolts naming what the pulse caught only last the first part of its life.
    BOLT_LIFE_FRAC: float = 0.55
    BOLT_SEGMENTS: int = 4
    BOLT_JITTER: float = 9.0
    BOLT_WIDTH: int = 3
    CHAINSTRIKE_COLOR: tuple = (140, 200, 255)


@dataclass(frozen=True)
class WeaponArchetype:
    """Feel profile for a weapon family, resolved from the weapon name's keyword.

    Multipliers apply to the base melee values (`Player.ATTACK_REACH/ATTACK_DAMAGE`,
    `Player.SWING_MS`). `shake` and `knockback` are in world pixels. A villager holding one
    of these swings on their own slower cadence (`NPC.swing_cooldown_ms`).
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
    # A thrust runs down a lane instead of sweeping a wedge: everything standing along the
    # shaft is skewered, each body behind the first for a little less (`Combat.THRUST_*`).
    # It is what the spear's blind spot buys, and the reason to hold a pack off in a line.
    pierce_melee: bool = False
    # What a ranged weapon puts in the air, and what that shot does beyond damage.
    # `element` is only ever set on a staff, resolved from the weapon's own name below.
    projectile_style: str = "arrow"
    element: str = ""
    # What one shot costs out of the player's mana pool (0 for everything that is not magic).
    # A staff spends no ammo and closes no distance, so this is the whole of what it pays.
    mana_cost: int = 0


@dataclass(frozen=True)
class Staffs:
    """What an elemental staff's bolt does on top of its damage (game/combat.py).

    A staff used to be one weapon painted purple: every bolt was identical, so carrying a
    staff instead of a bow was a question of ammo and nothing else. An element is read out
    of the weapon's own name and each one maps onto a mechanic the game already has, so
    the family differs in what it does to a fight rather than in its damage number.
    """

    # Fire: the burn affix's ticker, applied by the shot rather than by an affix roll.
    BURN_DAMAGE: int = 3
    # Frost: whatever it hits walks at this share of its speed for a moment. It never
    # roots (a bear trap is the only thing that does), it buys ground.
    CHILL_MULT: float = 0.55
    CHILL_MS: int = 1800
    # Storm: the bolt jumps to the nearest other enemy, the same idea as the Chain Strike
    # legendary but weaker, and on a weapon anyone can find.
    CHAIN_FRAC: float = 0.4
    CHAIN_RADIUS: float = 170.0


STAFF_BOLT_COLORS = {
    "": (150, 90, 230),
    "fire": (255, 145, 55),
    "frost": (140, 215, 255),
    "storm": (225, 210, 255),
}

# Name words that make a staff elemental. Read only once a weapon has already resolved to
# the staff archetype, so a "Flameblade" stays a sword instead of picking up a bolt.
STAFF_ELEMENT_WORDS = {
    "fire": "fire",
    "flame": "fire",
    "ember": "fire",
    "inferno": "fire",
    "frost": "frost",
    "ice": "frost",
    "rime": "frost",
    "winter": "frost",
    "storm": "storm",
    "shock": "storm",
    "thunder": "storm",
    "lightning": "storm",
}


@dataclass(frozen=True)
class Boomerang:
    """The thrown weapon that comes back (game/entities/projectile.py).

    A bow costs arrows and a staff costs nothing, which left nothing between them. A
    boomerang costs no ammo and only one is ever in the air: the wait for it to come home
    is the price, so it is a weapon of rhythm rather than of supply. It strikes on the way
    out and again on the way back, and a wall turns it early rather than eating it.
    """

    OUT_RANGE: int = 460
    # A plain boomerang comes home off the first thing it touches: striking a whole line of
    # bodies and then striking them all again on the way back was simply the best weapon in
    # the game. How many it carries through is a rarity roll now, indexed by tier, so the
    # piercing one is a thing to find rather than the way every one of them works.
    PIERCE_BY_TIER: tuple = (0, 0, 1, 2, 3)
    # The return leg is a little quicker than the throw, so the weapon is not dead time.
    RETURN_SPEED_MULT: float = 1.25
    # Close enough to the hand to be caught.
    CATCH_DISTANCE: float = 26.0
    COLOR: tuple = (205, 165, 95)


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
    # What it buys back is a lane rather than a point (`pierce_melee`, so a line of chasers
    # is skewered two at a time) and a shove hard enough to put whatever closed back out at
    # the end of the shaft, which is the range the weapon actually works at.
    "spear": WeaponArchetype(
        "spear", 2.2, 46.0, 0.9, 1.35, 380, 24, 0.12, False, 1.0, 5.0, False, False, 75.0, pierce_melee=True
    ),
    # The pole is a control weapon: it barely hurts and it moves people. What it is for is
    # the ground rather than the health bar, since the world is full of things worth being
    # shoved into (a river, a bear trap, a powder keg) and off (a pack that has surrounded
    # the player).
    "pole": WeaponArchetype("pole", 1.5, 0.0, 1.2, 0.45, 300, 62, 0.02, True, 1.3, 6.0, False, False, 140.0),
    # What somebody who owns no weapon fights with. A hoe is not a slower axe: it is short,
    # clumsy and barely hurts, which is the point of a farmer being dangerous in numbers
    # rather than in the hands. Anything a villager picks up off their own wall resolves
    # here, so making a village tougher is never a question of what its people are holding.
    "tool": WeaponArchetype("tool", 0.85, 0.0, 0.8, 0.5, 560, 4, 0.03, False, 1.0, 2.0, False, False, 95.0),
    "staff": WeaponArchetype(
        "staff",
        1.0,
        0.0,
        1.0,
        1.0,
        420,
        6,
        0.10,
        False,
        1.0,
        2.0,
        True,
        False,
        90.0,
        projectile_style="bolt",
        mana_cost=Magic.BOLT_COST,
    ),
    # Costs nothing to throw and only one is ever in the air: the flight is the cooldown.
    "boomerang": WeaponArchetype(
        "boomerang", 1.0, 0.0, 1.3, 0.9, 260, 8, 0.10, False, 1.0, 2.0, True, False, 90.0, projectile_style="boomerang"
    ),
    "bow": WeaponArchetype("bow", 1.0, 0.0, 1.0, 1.0, 400, 4, 0.10, False, 1.0, 1.0, True, True, 90.0),
}

# Weapon-name keyword -> archetype key. Keywords mirror items.WEAPON_KEYWORDS. Matched by
# substring in this order, so anything whose name contains another family's word (a
# "quarterstaff" holding "staff") has to be listed above the word it would be caught by.
_KEYWORD_TO_ARCHETYPE = {
    "quarterstaff": "pole",
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
    "pitchfork": "spear",
    "halberd": "spear",
    "pike": "spear",
    "hatchet": "axe",
    # A farmhouse's contents. Listed above the weapon words so a "Fire Poker" is a poker
    # rather than falling through to the sword every unknown name used to become.
    "hoe": "tool",
    "shovel": "tool",
    "spade": "tool",
    "rake": "tool",
    "sickle": "tool",
    "scythe": "tool",
    "broom": "tool",
    "rolling pin": "tool",
    "poker": "tool",
    "mallet": "tool",
    "tongs": "tool",
    "cudgel": "pole",
    "pole": "pole",
    "boomerang": "boomerang",
    "chakram": "boomerang",
    "staff": "staff",
    "bow": "bow",
}

# Elemental staffs are variants of the one staff profile rather than families of their
# own, built once and kept: the archetype is a frozen dataclass asked for on every swing,
# every icon and every tooltip.
_ELEMENTAL_STAFFS: dict[str, WeaponArchetype] = {}


def _staff_variant(lower: str) -> WeaponArchetype:
    """The staff profile for a name, carrying whichever element the name spells out."""
    element = next((el for word, el in STAFF_ELEMENT_WORDS.items() if word in lower), "")
    if not element:
        return WEAPON_ARCHETYPES["staff"]
    if element not in _ELEMENTAL_STAFFS:
        _ELEMENTAL_STAFFS[element] = replace(WEAPON_ARCHETYPES["staff"], element=element)
    return _ELEMENTAL_STAFFS[element]


# Weapon-name keyword -> the silhouette it is drawn as (game/entities/gear.py). Separate
# from the archetype table above because how a thing swings and what it looks like are two
# different questions: every farmhouse tool swings identically and none of them should look
# alike, while a hatchet and a battleaxe share a profile and swing the same. Matched by
# substring in this order; anything not listed is drawn as its archetype.
_KEYWORD_TO_LOOK = {
    "rolling pin": "rolling_pin",
    "pitchfork": "pitchfork",
    "halberd": "halberd",
    "hatchet": "hatchet",
    "scythe": "scythe",
    "sickle": "sickle",
    "shovel": "shovel",
    "spade": "shovel",
    "broom": "broom",
    "poker": "poker",
    "tongs": "tongs",
    "mace": "mace",
    "club": "club",
    "cudgel": "club",
    "knife": "knife",
    "rake": "rake",
    "hoe": "hoe",
}


def weapon_look(name: str | None) -> str:
    """The silhouette a weapon is drawn with: its own if it has one, its archetype's
    otherwise. Bare hands answer with "", which is what `draw_human` draws as empty hands."""
    if not name:
        return ""
    lower = name.lower()
    for keyword, look in _KEYWORD_TO_LOOK.items():
        if keyword in lower:
            return look
    return weapon_archetype(name).name


def weapon_archetype(name: str | None) -> WeaponArchetype:
    """Resolve a weapon name to its feel profile; generic/unknown weapons swing like a sword."""
    if not name:
        return UNARMED
    lower = name.lower()
    for keyword, key in _KEYWORD_TO_ARCHETYPE.items():
        if keyword in lower:
            return _staff_variant(lower) if key == "staff" else WEAPON_ARCHETYPES[key]
    return WEAPON_ARCHETYPES["sword"]


@dataclass(frozen=True)
class Decals:
    """Blood splats left on the ground by hits and kills (core/decals.py)."""

    LIFE_MS: float = 18_000.0
    # Oldest decal is dropped once the list grows past this, so a long fight
    # never leaves an unbounded number of splats to draw.
    MAX_COUNT: int = 600

    HIT_RADIUS: int = 10
    KILL_RADIUS: int = 28
    # How much harder a kill splashes than the hit that came before it, and a boss than
    # anything else: the same recipe, laid on until it reads from across the clearing.
    KILL_SCALE: float = 1.9
    BOSS_SCALE: float = 3.0

    # A wound throws a fan of droplets out along the blow rather than leaving one tidy
    # circle: the pool marks where it was struck, the spray says how it went. Each weapon
    # family scales these by its own row in `core.decals._SPLAT_STYLES`.
    SPRAY_SPREAD_DEG: float = 110.0
    SPRAY_COUNT: int = 12
    SPRAY_DISTANCE: tuple = (14.0, 95.0)
    SPRAY_RADIUS: tuple = (3.0, 9.0)
    # Deep arterial red, darker than the bright particle spray so the two read as
    # "still in the air" versus "already on the ground".
    BLOOD_COLOR: tuple = (128, 16, 16)

    # How opaque a splat is at its wettest. Blood on the ground is the record of a fight,
    # so it is meant to be read from across the clearing.
    ALPHA: int = 205
    # How much a droplet is pulled along its own flight at the far end of a spray: the
    # difference between a dot and a smear pointing where the blow went.
    SMEAR_STRETCH: float = 2.2
    # How far a splat's outline wanders off its own radius. Blood does not land in circles,
    # and this is the whole difference between a splat and a sticker.
    RAGGED: float = 0.42
    # The long arterial throws a kill adds on top of the fan.
    ARC_SPREAD_DEG: float = 70.0
    KILL_ARCS: int = 4
    BOSS_ARCS: int = 7
    ARC_LENGTH: tuple = (90.0, 250.0)
    BOSS_ARC_LENGTH: tuple = (110.0, 320.0)

    # What a blast burns into the ground it went off on. Nearly as opaque as blood, since
    # charred earth is charred earth, and far longer lived: the clearing keeps saying a keg
    # went up there long after the fight has moved on.
    SCORCH_COLOR: tuple = (26, 22, 20)
    SCORCH_FRINGE: tuple = (74, 52, 34)
    SCORCH_ALPHA: int = 196
    SCORCH_LIFE_MS: float = 54_000.0
    # How much of the blast's own radius is left burnt. A blast throws further than it
    # chars, so the mark is well inside the ring the damage was applied over.
    SCORCH_RADIUS_FRAC: float = 0.62

    # Blood is something to stand in: a splat this size or bigger marks the ground it
    # landed on as wet for a few seconds, and anything crossing that ground picks it up.
    WET_MS: float = 7000.0
    WET_MIN_RADIUS: float = 7.0
    WET_CELL: int = 26
    WET_MAX_CELLS: int = 400
    # One print per stride, alternating sides, the sole running dry over the next few
    # steps: a trail that says which way something walked away, not a permanent stain.
    FOOT_STRIDE: float = 30.0
    FOOT_OFFSET: float = 7.0
    FOOT_RADIUS: float = 6.5
    FOOT_LIFE_MS: float = 7000.0
    FOOT_FADE_PER_STEP: float = 0.14
