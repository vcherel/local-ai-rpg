import json
import os
import threading


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
        - explored: Grid cells the player has walked through, as "gx:gy" strings (Fog.CELL
          wide). The minimap draws these and blacks out everything else (list[str])
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
            with open(self.filename, "r") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}
        return {}

    def update(self, key, value):
        self.data[key] = value

    def load(self, key, default=None):
        return self.data.get(key, default)

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
