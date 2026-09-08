# Plan

## Batch 1: doors, sight and the room
- [x] 6. A barred door drawn with the beam across an open leaf (`_bar_doors` never shuts it, `Building.locked` ignores `door_open`)
- [x] 7. Shutting the door behind you blocks a villager's sight (`WorldSocial.sight_reaches` only tests the facade half-plane)
- [x] 5. Trespass caught in the tavern by sleepers (`squatter_witness` counts a resident even while asleep)
- [x] 1. Furniture laid on top of the rug (`interior_layout` places the rug after the room is furnished)

## Batch 2: bodies that move and bodies that don't
- [x] 3. Critters wedged in outside corners (`_update_critters` never calls `unwedge`)
- [x] 10. Villagers with no bed (`_populate_npcs` ignores how many beds the room fits)
- [x] 11. Guards too immobile (post radius 70 with ordinary villager idle timings)
- [x] 4. Sleep unreadable (blanket over the sleeper, a rising z, a bedroll on the floor)

## Batch 3: the night
- [x] 2a. A bell rung once at curfew, heard inside a settlement
- [x] 2b. Villagers go to bed on their own rolled delay instead of all on one frame
- [x] 2c. The tavern stays open at night, its keeper up longest
- [x] 2d. A doorman on the tavern at night: a few coins for the room

## Batch 4: the sky and one surprise
- [ ] 8. Fog fades in over a doorway instead of popping (`game.py` `if self.interior is None`)
- [ ] 9. Fog costs frames (unconverted per-pixel-alpha banks re-`set_alpha`ed and blitted every frame)
- [ ] 12. Villagers walking home after the bell carry a lantern
