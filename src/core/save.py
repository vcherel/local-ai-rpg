import json
import os
import threading
import time


class SaveSystem:
    """
    Save key elements of the game to continue

    Keys:
        - context: World context (str)
        - coins: Player coins (int)
        - name_buffer: NPC names generated ahead of need, not yet assigned (list[str])
        - used_names: Every NPC name handed out so far, to avoid duplicates (list[str])
        - player: Player position and hp (dict)
        - stats: Character stat levels and xp (dict)
        - inventory: Item ids the player carries (list[str])
        - equipped: Currently equipped item ids, keyed by slot (dict[str, str | None])
        - potion_bar: Item ids on the HUD potion quickbar, None per empty slot. A choice the
          save keeps, so which potion a quick key drinks survives a pickup (list)
        - active_hands: Which of its two weapons each hand is currently holding, one index
          per hand (list[int])
        - items: All world items, the master list quests and inventory link into (list[dict])
        - npcs: NPC state including their quests (list[dict])
        - monsters: Monster positions, hp and kind (list[dict])
        - buildings: Building placement, kind, size, name, looted state, and which
          interior crates/exterior windows are broken (list[dict])
        - villages: Every settlement generated so far: plaza position, owning chunk, size,
          name and whether it has been walked into. Their buildings and people are saved in
          `buildings`/`npcs` like the starting town's; unlike a POI a village is generated
          once and kept, since its NPCs carry names, affinity, quests and stock (list[dict])
        - breakables: Outdoor barrels/pots/bushes not yet smashed, position and kind (list[dict])
        - pois: What the player changed about a wilderness point of interest, by POI id:
          {"cx:cy": {"looted": bool, "discovered": bool, "npc_spawned": bool}}. POIs themselves
          are regenerated from their chunk, so only touched ones appear here (dict)
        - felled: Trees the player has cut down, as "cx:cy:index" keys. A chunk's scenery is
          rolled from its seed, so what was felled is the one thing about it worth keeping
          (list[str])
        - bombs: Mines the player laid and has not set off, position and kind. A grenade is
          in the air for a second and is never saved (list[dict])
        - deaths: How many times the player has died this playthrough (int)
        - quests_done: How many quests the player has handed in this playthrough (int)
        - milestones: Which death and quest milestones have already paid out, so a reward is
          granted once ({"quests": [int], "deaths": [int]})
        - traps: Which hunters' bear traps have already shut, by trap id: {"cx:cy:x,y": True}.
          Traps themselves are regenerated from their chunk, so springing one is all there is
          to save (dict)
        - tunnels: What is left of each tunnel under the world, by tunnel id:
          {"tunnel:cx:cy": {"guards_alive": int, "hoard_placed": bool, "vault_placed": bool,
          "warden_alive": bool | None, "warden_name": str}}. The layout itself is rebuilt
          from the chunk the way in stands in, and a cave's warden is stood back up from
          these two fields exactly as its garrison is from the count (dict)
        - underground: The tunnel the player was standing in when the game was saved and the
          spot to put them back at, or None on the surface:
          {"id": "tunnel:cx:cy", "return": [x, y]} (dict | None)
        - explored: Grid cells the player has walked through, as "gx:gy" strings (Fog.CELL
          wide). The minimap draws these and blacks out everything else (list[str])
        - village_strikes: How much patience each settlement has left with the player, by
          village key and by what the player did:
          {"cx:cy": {"assault": {"count": int, "at": wall-clock seconds}}}. A village warns
          once per kind of offence before it turns hostile, and the warning outlives a quit
          like the anger does (dict)
        - camp_rest: When each place the player rested will serve them again, by POI id for a
          campfire and by building id for a villager's bed (wall-clock seconds)
        - death_taunts: Mocking death-screen lines written ahead of need, not yet used (list[str])
        - buffs: Active potion buffs, {effect: {"until": wall-clock seconds, "magnitude": float}}
        - daynight_elapsed_ms: Elapsed time within the current day/night cycle (float)
    """

    def __init__(self, filename="./saves/save.json"):
        self.filename = filename
        self.data = self._load_all()
        # Background generation threads and the main loop both save now; serialise the
        # file writes so two threads can't interleave and corrupt the JSON.
        self._write_lock = threading.Lock()

    def _load_all(self):
        if os.path.exists(self.filename):
            with open(self.filename) as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}
        return {}

    def update(self, key, value):
        self.data[key] = value

    def load(self, key, default=None):
        return self.data.get(key, default)

    def await_context(self, abandoned) -> str | None:
        """Block until the world context has been written, then return it.

        The context is generated once at startup on its own thread, and the background
        writers that need it (NPC names, death taunts) are started before it lands. They
        all wait here rather than each keeping their own poll loop. `abandoned` is asked
        between polls: a session that has been closed gives up and gets None back, so a
        thread still waiting when the player quits does not write into the next game.
        """
        while True:
            if abandoned():
                return None
            context = self.load("context", None)
            if context is not None:
                return context
            time.sleep(0.1)

    def save_all(self):
        with self._write_lock:
            os.makedirs(os.path.dirname(self.filename) or ".", exist_ok=True)
            tmp = f"{self.filename}.tmp"
            # Shallow-copy the top-level dict so a concurrent update() on the main thread
            # can't change it mid-serialisation; write to a temp file and swap it in
            # atomically so a crash mid-write leaves the old save intact.
            with open(tmp, "w") as f:
                json.dump(dict(self.data), f, indent=4)
            os.replace(tmp, self.filename)

    def clear(self):
        self.data = {}
        if os.path.exists(self.filename):
            os.remove(self.filename)
