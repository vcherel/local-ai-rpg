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
        - buildings: Building placement, kind, size, name and looted state (list[dict])
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
