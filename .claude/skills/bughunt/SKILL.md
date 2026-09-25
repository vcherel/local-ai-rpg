---
name: bughunt
description: Hunt for bugs, weird UI and wrong logic in rpg-ai, then fix what Valentin approves and turn each bug class into a check in scripts/verify so it cannot come back. Use when asked to find bugs, weird things, or wrong logic in the game.
---

# bughunt

The hunts before this skill found real bugs by reading, and the same kinds kept coming back
(a quest left pointing at somebody gone, a worker thread changing the world, a save that
drops or resurrects someone). Reading is still how bugs are found. What changes is that a
bug fixed here also leaves a check behind.

## 1. Look

- Run `scripts/verify/refs.py` and `scripts/verify/smoke.py` first and say what they
  printed. A failure there is the first finding.
- Read the systems touched by the last commits (`git log --oneline -15`) before the rest:
  new code is where new bugs are.
- For every candidate, find the path that triggers it in play. Reproduce it through
  `scripts/verify/harness.py` when it can be reached headless, and say which findings were
  reproduced and which were only read. A finding that turns out wrong is dropped, not fixed.
- Anything the player sees (layout, text, an icon) is checked by drawing a real frame
  through the harness and reading the PNG back, never by reasoning about the draw code.

## 2. Report and wait

A numbered list, most harmful to the player first, each with the trigger in play, the
cause with `file:line`, and the fix proposed. Then stop: fixing waits for Valentin's go,
unless he started this with /solo.

## 3. Fix

- More than four fixes go in `PLAN.md` first, as the global rules say.
- For each fix, ask whether its bug belongs to a class a check could catch: an invariant
  about the world after N frames or after a save and a reload goes in `smoke.py`
  (`check`, `check_quests`), a rule about code shape goes in `refs.py`. Add the check, then
  prove it by putting the bug back and watching the check fail. Say which fixes got a check
  and why the others could not.
- Run `refs.py`, `smoke.py`, and `render_diff.py` if anything draws, and report what they
  printed.

## 4. Report

What changed, per fix, with the files each one touched, so `/wrap-up` can commit unrelated
fixes separately instead of one commit whose subject is a list.
