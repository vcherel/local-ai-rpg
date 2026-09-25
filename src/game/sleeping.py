from __future__ import annotations

import math

import pygame

import core.constants as c
from core.audio import play_sound


class GameSleep:
    """A night in a bed: the prompt over it, the refusals, and the fade to morning.

    Mixed into `Game`, whose player, world and interior these read.
    """

    def _bed_cooling(self) -> float:
        """Seconds before this bed is worth lying in again. Every bed in the world has the
        same cooldown, the tavern's included: a room of them is not a row of full heals. The
        prompt and the key both read it from here so they can't disagree about whether it
        will work."""
        return self.world.rest_ready_in(self.interior.id)

    def _bed_label(self, bed) -> str:
        """What the prompt over a bed says: whether there is somebody in it, whether it is
        still warm, what the room costs and who is watching them climb into it.

        One bed in the game is paid for, and it is paid for because somebody is standing at
        the door of it (`World.room_price`). Every other bed in the world is taken and
        risked, which is what the watching cones under the prompt are about."""
        sleeper = self.world.bed_taken(bed)
        if sleeper is not None:
            return f"{sleeper.name or 'Someone'} is asleep in this bed"
        if self._sleep_threat():
            return "Too dangerous to sleep with that out there"
        cooling = self._bed_cooling()
        if cooling > 0:
            return f"E: this bed is still warm ({int(cooling) + 1}s)"
        price = self.world.room_price(self.interior)
        if price:
            # Paid for at the door, so nobody is watching and there is nothing to watch: the
            # cones are for a bed being taken, and this one is being rented.
            if self.player.coins < price:
                return f"A room here is {price} coins"
            return f"E: take a room ({price} coins)"
        label = "E: sleep in their bed" if self.interior.kind == "house" else "E: take a room"
        return self._watched_label(label)

    def _sleep_in_bed(self, bed):
        # Somebody is already in it. A house has one bed and a tavern has several, so which
        # bed is free is a real answer after dark rather than a formality, and nobody is
        # tipped out of their own to make room for the player.
        sleeper = self.world.bed_taken(bed)
        if sleeper is not None:
            name = sleeper.name or "Someone"
            self.loot_notification.show(f"{name} is asleep in this bed", c.Colors.MUTED)
            return
        # A bed is the one full night's rest in the game: unlike a campfire it heals
        # everything, shakes off the post-death weakness and puts the night behind the
        # player. None of them is the player's: a villager's bed, or a tavern room nobody is
        # renting out, is taken, which costs the risk of being seen, and every one of them
        # is left cold for a while. Nobody sleeps
        # with something hostile in the street, the same refusal a campfire makes through
        # `camp_is_clear`.
        if self._sleep_threat():
            self.loot_notification.show("Too dangerous to sleep with that out there", c.Colors.RED)
            return

        remaining = self._bed_cooling()
        if remaining > 0:
            self.loot_notification.show(f"You slept here recently. Again in {int(remaining) + 1}s", c.Colors.MUTED)
            return
        # A tavern with somebody on the door after dark rents its rooms. Paying for one is
        # the only way a bed in this game is ever anything but taken, and it is why the
        # household is not woken up about it below.
        price = self.world.room_price(self.interior)
        if price:
            if self.player.coins < price:
                self.loot_notification.show(f"The doorman wants {price} coins for a room", c.Colors.RED)
                return
            self.player.add_coins(-price)

        play_sound("quest_complete")
        self._sleep_until_dawn()
        # Marked cold once the night is over rather than before it: the skip runs every
        # rest clock forward, and this bed's would have been spent on the night slept in it.
        self.world.rest_in_house(self.interior)
        self.player.clear_death_debuff()
        self.player.max_hp = self.player.effective_max_hp()
        self.player.hp = self.player.max_hp
        self.loot_notification.show("You sleep until dawn and wake fully rested", c.Colors.GREEN)
        # Not a theft, and never worded as one: the household finds a stranger in the bed.
        # Unless it was paid for at the door, in which case there is no stranger and no bed
        # of anybody's: that is the whole of what the coins buy.
        if not price:
            self._check_witness("squatting")
        # A night is hours of world clocks moved on; nobody wants to sleep it twice.
        self.save_data()

    def _sleep_threat(self) -> bool:
        """Whether anything hostile is close enough to make lying down absurd. Shared by the
        prompt and the key, like every other refusal."""
        return bool(self.world.hostiles_near(self.player.x, self.player.y, c.Buildings.SLEEP_SAFE_RADIUS))

    def _sleep_until_dawn(self):
        """Fade out, run the world forward to just after dawn, fade back in.

        Deliberately not instant: the tint moving under the fade is the only thing that says
        hours went by. Nothing in the world takes a step while it runs (`World.update` is not
        called), but every clock in it moves, and whatever was coursing through the player's
        veins at bedtime has worn off by morning.

        Nothing takes a step, but the settlement is not the tableau it was either: everybody
        is got out of bed and walked to somewhere plausible to be found at over the length
        of the fade (`World.plan_morning`, `World.drift_to_morning`), so waking up is a
        street that has moved on rather than the same one with a lighter sky."""
        skip_ms = self.world.daynight.time_until(c.Buildings.SLEEP_WAKE_PROGRESS)
        duration = c.Buildings.SLEEP_FADE_MS
        overlay = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT))
        overlay.fill((0, 0, 0))

        self.world.plan_morning()
        elapsed = 0.0
        while elapsed < duration:
            # Input is swallowed for the second and a half this lasts; the pump is only
            # there so the window keeps answering the OS.
            pygame.event.pump()
            step = min(self.clock.tick(60), duration - elapsed)
            elapsed += step
            self.world.pass_time(skip_ms * (step / duration) / 1000)
            self.world.drift_to_morning(elapsed / duration)

            self.game_renderer.draw_world(self.camera, self.world, self.player, self.interior, None)
            self.world.daynight.draw(self.screen, self.world.events.blood_intensity)
            # Full black at the halfway mark, clear at both ends.
            overlay.set_alpha(int(255 * math.sin(math.pi * elapsed / duration)))
            self.screen.blit(overlay, (0, 0))
            pygame.display.flip()

        # Whatever was pressed while the screen was black is not an instruction about the
        # morning, so it is dropped rather than replayed the moment the player can see.
        # Whatever the loop's last frame left, everybody ends the night on open ground.
        self.world.drift_to_morning(1.0)
        pygame.event.clear()
        self.player.clear_buffs()
