from __future__ import annotations

import math
from typing import NamedTuple

import core.constants as c
from llm.llm_request_queue import llm_busy


class Interaction(NamedTuple):
    """What the interact key acts on right now, and the prompt drawn over it. `hint` is a
    second line for an extra key on the same target (a merchant's trade key)."""

    # Which kind of thing this is, and the key into `Game.interact_actions`, which is the
    # one list of them. Loot is not among them: it is collected by the magnet in
    # `Game._sweep_loot`, never by a key.
    kind: str
    target: object
    label: str
    x: float
    y: float
    hint: str = ""


class GameInteractions:
    """Everything the interact key could be pointed at, and which one it actually is.

    Mixed into `Game`, whose player, world and menus these read. Split out because finding
    the nearest thing in reach is one job and a long one, and because it is the half of
    `Game` that answers a question rather than changing anything: every method here reads
    the world and yields offers, and the acting is done by `Game.interact_actions`.
    """

    def current_interaction(self) -> Interaction | None:
        """The single thing the interact key acts on right now: the nearest interactable in
        reach, indoors or out. The prompt drawn on screen comes from the same call, so a
        tavern full of beds can't stack labels and the prompt can never point at something
        other than what the key does.

        Each `_offer_*` yields the `(distance, Interaction)` pairs it found and the nearest
        of the lot wins. They used to be handed a pair of closures to push into instead, so
        every one of them carried two arguments it did nothing with but pass along.
        """
        offers = [
            *self._offer_indoors(),
            *self._offer_doors(),
            *self._offer_gate(),
            *self._offer_night_gate(),
            *self._offer_underground(),
            *self._offer_places(),
            *self._offer_npc(),
        ]
        if not offers:
            return None
        return min(offers, key=lambda offer: offer[0])[1]

    def _reach(self, x, y) -> float:
        """How far the player is from a point, which is what every offer is ranked on."""
        return math.hypot(self.player.x - x, self.player.y - y)

    def _offer_indoors(self):
        """The chest and the beds of the room the player is standing in, if they are in one."""
        if self.interior is None:
            return
        indoor_reach = c.Buildings.INTERACT_DISTANCE
        layout = self.interior.interior_layout()

        chest = layout["chest"]
        if chest and not self.interior.looted:
            dist = self._reach(chest.centerx, chest.centery)
            if dist <= indoor_reach:
                # A chest only ever stands in somebody's house, so opening it is theft
                # and the prompt says so rather than dressing it up as loot.
                label = self._watched_label("E: steal from the chest")
                yield dist, Interaction("chest", chest, label, chest.centerx, chest.top)

        for bed in layout["beds"]:
            dist = self._reach(bed.centerx, bed.centery)
            if dist <= indoor_reach:
                yield dist, Interaction("bed", bed, self._bed_label(bed), bed.centerx, bed.top)

    def _offer_doors(self):
        """Every front door in reach, and whether E would open it or shut it."""
        for building in self.world.buildings_near(self.player.x, self.player.y):
            if not building.has_door or building.door_broken:
                continue
            door = building.door_rect()
            dist = self._reach(door.centerx, door.centery)
            if dist > c.Buildings.INTERACT_DISTANCE:
                continue
            inside = building.contains_point(self.player.x, self.player.y)
            if building.locked and not inside:
                # Barred from the outside is a wall, and the prompt says so rather than
                # offering a key that does nothing. The window beside it is the way in.
                label = "The door is barred"
            elif building.house_locked:
                # Inside a house with its own beam across: this is the one that comes off for
                # good, thrown by whoever climbed in through the window.
                label = "E: lift the beam"
            elif building.door_overlaps(self.player.x, self.player.y, c.Player.SIZE / 2):
                # Standing in the doorway: the only thing E may do here is open it. Offering
                # to close a door around oneself is how one used to end up sealed in it.
                if building.door_open:
                    continue
                label = "E: open the door"
            else:
                label = "E: close the door" if building.door_open else "E: open the door"
            yield dist, Interaction("door", building, label, door.centerx, door.top - 10)

    def _offer_gate(self):
        """The barred gate the player is standing at, and the only prompt in the game that
        is held rather than pressed. A town that has shut itself is not a box: the beam can
        be heaved up from the inside, it just takes long enough that doing it with a mob at
        your back is a decision (`_lift_gate`)."""
        found = self.world.barred_gate_in_reach(self.player)
        if found is None:
            return
        village, index = found
        leaf = village.defences()["gates"][index]["rect"]
        label = f"Hold E: heave the bar up ({int((1 - self.gate_lift) * c.Villages.GATE_LIFT_S) + 1}s)"
        yield (
            self._reach(leaf.centerx, leaf.centery),
            Interaction("gate", found, label, leaf.centerx, leaf.top - 10),
        )

    def _offer_night_gate(self):
        """The gate a village has leaned shut for the night, which is one press rather than
        the hold a bar takes. Never offered on a barred gate: that one is the other prompt,
        and being shut out of a town you have angered is not something a keystroke undoes."""
        found = self.world.shut_gate_in_reach(self.player)
        if found is None:
            return
        village, index = found
        leaf = village.defences()["gates"][index]["rect"]
        yield (
            self._reach(leaf.centerx, leaf.centery),
            Interaction("nightgate", found, "E: push the gate open", leaf.centerx, leaf.top - 10),
        )

    def _offer_underground(self):
        """The two ends of the dark: the way back up when down there, the two ways down when
        on the surface. Never both, since one of them is always somewhere else."""
        if self.world.underground is not None:
            # The one way back up, and the only thing to interact with down there besides
            # what is lying on the floor.
            tunnel = self.world.underground
            if tunnel.at_exit(self.player.x, self.player.y):
                label = "E: climb back up" if tunnel.kind == "well" else "E: leave the cave"
                yield self._reach(*tunnel.entrance), Interaction("ladder", tunnel, label, *tunnel.entrance)
            return

        village = self.world.well_in_reach(self.player)
        if village is not None:
            # Deliberately not "climb down": which wells go anywhere is what walking over
            # to one is for, and a prompt that already knew would answer the question.
            yield (
                self._reach(village.x, village.y),
                Interaction("well", village, "E: look down the well", village.x, village.y - 40),
            )

        cave = self.world.cave_in_reach(self.player)
        if cave is not None:
            yield (
                self._reach(cave.x, cave.y),
                Interaction("cave", cave, "E: enter the cave", cave.x, cave.y - 50),
            )

    def _offer_places(self):
        """A campfire to rest at, a shrine to pray at, a notice board to read and a shut trap
        to set again: the things standing in the open that answer a press."""
        camp = self.world.camp_in_reach(self.player)
        if camp is not None:
            cooling = self.world.rest_ready_in(camp.id)
            label = f"E: fire burned low ({int(cooling) + 1}s)" if cooling > 0 else "E: rest at the fire"
            yield self._reach(camp.x, camp.y), Interaction("camp", camp, label, camp.x + 40, camp.y)

        shrine = self.world.shrine_in_reach(self.player)
        if shrine is not None:
            yield (
                self._reach(shrine.x, shrine.y),
                Interaction("shrine", shrine, "E: pray at the shrine", shrine.x, shrine.y - 40),
            )

        village = self.world.board_in_reach(self.player)
        if village is not None:
            bx, by = village.board_pos()
            yield self._reach(bx, by), Interaction("board", village, "E: read the notice board", bx, by - 60)

        trap = self.world.sprung_trap_in_reach(self.player)
        if trap is not None:
            yield (
                self._reach(trap.x, trap.y),
                Interaction("trap", trap, "E: set the trap again", trap.x, trap.y - 24),
            )

    def _offer_npc(self):
        """Whoever is close enough to talk to, and the reason they won't when they won't."""
        npc = self.world.npc_in_reach(self.player)
        # A merchant still waiting on its stock, someone who has turned on the player, or a
        # world whose context hasn't generated yet: no prompt for something the key wouldn't do.
        if npc is None or not npc.can_talk or self.world.context is None or (npc.is_merchant and not npc.shop_ready):
            return
        if self._threat_nearby():
            # Nobody stands in the street making conversation with a wolf twenty paces
            # off. Kill it or walk away from it first.
            label = f"{npc.name or 'They'} won't talk with that out there"
        elif llm_busy():
            # One model serves the whole game and the call already running cannot be
            # cut short, so a conversation opened now would sit on an empty box.
            label = f"{npc.name} is busy..." if npc.name else "Busy..."
        else:
            label = f"E: talk to {npc.name}" if npc.name else "E: talk"
        hint = "B: trade" if npc.is_merchant else ""
        yield (
            self._reach(npc.x, npc.y),
            Interaction("npc", npc, label, npc.x, npc.y - c.Entities.NPC_SIZE, hint),
        )
