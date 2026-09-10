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
- [ ] Bat swarm behaviour: a cloud that crosses the room and briefly fills the screen, chip damage only
- [ ] Skittering non-hostile cave critter that flees the light (new `CRITTER_KINDS` row, temperament if needed)

## Batch 4: what is down there (root: the cave is empty between fights)
- [ ] Remains as scenery: bones, a dropped pack, a dead adventurer with a little loot, room-seeded
- [ ] Husk / disguised monster posing as a corpse or rubble pile, unmasks for the player only
- [ ] Sleeping garrison: some tunnel guards start dormant (no vision cone), wake on light or noise within a short radius
- [ ] Cave hazard table: a pit (fall + damage), a gas pocket (existing chill/weakness status), a ceiling rockfall telegraphed by a shadow

## Batch 5: structural dread (root: the cave has no stakes beyond the fight)
- [ ] Collapsing entrance (rare): the shaft is blocked on entry and the player walks to a second exit added to the vault room
- [ ] Old bear traps / snares left in corridors by whoever came before (reuse `BearTrap`)
