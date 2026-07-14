import json
import os


class SaveSystem:
    """
    Save key elements of the game to continue

    Keys:
        - context: World context (str)
        - coins: Player coins (int)
        - name: Next NPC name (str)
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
        with open(self.filename, "w") as f:
            json.dump(self.data, f, indent=4)

    def clear(self):
        self.data = {}
        if os.path.exists(self.filename):
            os.remove(self.filename)
