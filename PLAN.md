# Plan: the notice board and the props around it

## Batch 1: the notice board reads as a plank
Root cause: it is drawn bare, flat and walk-through, so nothing says it is the quest board.

- [x] Roll a settlement's notices when it is prepared, not when the menu opens, so a board is never drawn empty
- [x] Redraw `Village._draw_board` as an upright object: ground shadow, darker posts, plank grain, shingle header
- [x] Make the board solid in `Village.blocks`
- [x] Verify: `refs.py`, `smoke.py`, `render_diff.py`

## Batch 2: outdoor props that look solid but are not
Root cause: breakables are collision-less and placed without seeing the lanes.

- [ ] Barrels, powder kegs and saplings block movement; bush, flowerbed and herbs stay walk-through
- [ ] Breakable placement keeps off a settlement's lanes and plaza
- [ ] Verify: `refs.py`, `smoke.py`, `render_diff.py`
