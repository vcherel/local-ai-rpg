import json
import os


class SaveSystem:
    """
    Save key elements of the game to continue

    Keys:
        - context: World context (str)
        - coins: Player coins (int)
        - name: Next NPC name (str)
    """

    def __init__(self, filename="./assets/save.json"):
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
