# Enhance-code plan

Applying the 15 proposals from the code-quality audit. Batches share a root cause.
Tick a box as it lands, commit per batch, delete this file when every box is ticked.

## Batch 1: the same code written twice
- [x] 1. `combat.py:1026` `snap_traps`: four near-identical victim lookups into one loop over `(list, radius)` pairs, the form `prick_spikes` already uses
- [x] 2. `combat.py:630`/`:718` `bash_gates`/`bash_doors`: one loop parameterised by what stands between chaser and player
- [x] 3. `critter.py:130-165`: `root`/`chill`/`staggered`/`status_effects`/`dead` copied from `Entity`, extract a `Statuses` mixin both use
- [x] 15. `combat.py:1211`/`:1268` `_apply_chainstrike`/`_chain_bolt`: one mechanic at two strengths, one function with a target count

## Batch 2: long functions flattened
- [x] 4. `player.py:962` `receive_damage`: three bail-outs into one `_shrugged_off` guard, the ward branch into `_apply_ward`
- [x] 12. `entities.py:412` `_body_sprite`: split the cache key from the painting
- [x] 13. `main_menu.py:41`, `notification.py:36`: superfluous `elif` after `return`
- [x] 14. `inventory_menu.py:111`: `list.extend` of a comprehension

## Batch 3: dead weight and misplaced state
- [ ] 7. `constants/combat.py:306` `Explosion.RING_COLORS`: read nowhere, delete
- [ ] 9. `npcs.py:39`: the merchant four off every farmer, onto a shop object made only for merchants
- [ ] 11. `game_renderer.py:170`/`:175`: traps and breakables walk the whole list, use the range lookups the neighbours use

## Batch 4: files split along the mixin seam
- [ ] 5. `player.py`: affixes and buffs into a `player_affixes.py` mixin
- [ ] 6. `game.py`: `current_interaction` and the seven `_offer_*` into `game/interactions.py`, closures replaced by returned candidates
- [ ] 8. `combat.py`: gore and feedback into `game/gore.py`
- [ ] 10. `game_renderer.py:102` `draw_world`: the ground passes into `_draw_ground`
