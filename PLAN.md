# Make the cave scary

Re-read this file first if a session was cut off; carry on from the first unticked box.
Delete it once every box is ticked.

## Batch 1: sound and score (root: the cave has no audio identity)
- [x] Underground music context in `core/music.py`, wired through `Game._music_context` (priority above day/night, below combat/boss)
- [x] Cave ambience (drips, distant rockfall, low room tone) as procedural one-shots on a timer, driven from `World.update` while `underground is not None`
- [x] Bat wing/screech sounds when a swarm wakes and when one closes; warden breath/heartbeat that fades in when it is near but still unlit
- [x] Duck the surface ambience/music volume while underground so the world above goes quiet (underground pad is the quietest; nothing else sounds underground)
- [x] (bonus) `_synth` uses a per-effect local RNG so adding a sound never shifts the world's seeded rolls again

## Batch 2: the lantern and the dark (root: the light is dead steady and safe-feeling)
- [x] Lantern flicker: small per-frame noise on radius/alpha, worse with depth from the shaft and near the warden
- [x] Lantern shrinks the longer the player is underground, recovers near the shaft
- [x] Rare full blackout for a beat (a down draught), seeded per room so it is not frame noise
- [x] Ambient silhouettes / eye-pairs drawn past the lantern edge, mostly nothing, room-seeded

## Batch 3: unseen pressure and feedback (root: threats give no warning in the dark)
- [x] "Something is watching" vignette (`screen_fx.DreadVignette`) held at `Tunnel.pressure` when the warden is unseen but close
- [x] Screen shake on a distant rockfall sound
- [x] Bat swarm on cave entry: a cloud of dark flecks crosses the light, screech + flutter + shake (cosmetic startle)
- [x] Skittering non-hostile "cave crawler" that bolts from the player (passive, flee_distance 340)

## Batch 4: what is down there (root: the cave is empty between fights)
- [x] Remains as scenery: bones and a dropped pack drawn per room (`Tunnel._draw_remains`), one fallen purse placed as a real item
- [x] Sleeping garrison: `Monster.dormant`, a fraction of the tunnel roll, wakes on proximity, a hit, or a rumble nearby (covers "looks like scenery until it moves")
- [x] Gas pocket hazard: room-seeded `Tunnel.gas` zones, chill the player, drawn as a sickly haze
- [x] Old bear traps in the corridors (`_lay_old_traps`, session-only, tagged with the tunnel)

## Deferred: two real subsystems with a design fork (asked Valentin)
- [ ] Pit hazard: fall through to a lower room. Needs a floor-level concept the tunnel does not have.
- [ ] Collapsing entrance: shaft blocked on entry, second exit at the vault. Needs a second way out and the pathing for it.
- [ ] Dedicated husk "corpse/rubble" disguise art (only if the dormant guard is not enough)
