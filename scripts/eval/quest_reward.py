"""Quest analysis on the real model: is there a quest, which kind, and what does it pay.

The conversations are the ones the reward fallback was measured on (a promised item that
came back empty in about one run in six), plus a few that hold no quest, since a change
that finds every reward by finding quests everywhere is no fix. Each case goes through
`QuestSystem.analyze_conversation_for_quest` exactly as the game calls it.

    uv run python scripts/eval/quest_reward.py [--runs 3] [--ref HEAD]
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import runner

# (conversation, the quest type it should read as or None when either of two would do,
#  a word the reward item has to contain, or None when only coins were promised,
#  whether it holds a quest the player took)
CASES = [
    (
        "NPC: Wolves took three of my sheep this week. Kill four of them and I'll pay you 30 gold.\n"
        "Player: Deal, I'll hunt them.\nNPC: Thank you, come back when it's done.\n",
        "kill_mob",
        None,
        True,
    ),
    (
        "NPC: My sister in the next village is waiting on this letter. Carry it to her and there's a purse "
        "of coins in it for you.\nPlayer: Sure, give it here.\nNPC: Safe roads, friend.\n",
        "deliver",
        None,
        True,
    ),
    (
        "NPC: A thief took my silver ring last night. Get it back and I'll reward you with 50 coins.\n"
        "Player: I'll find him.\nNPC: Bless you.\n",
        "recover_stolen",
        None,
        True,
    ),
    (
        "NPC: I need a bundle of firewood before the frost. Fetch it and I'll pay you well.\n"
        "Player: Okay, I can do that.\nNPC: Wonderful, hurry back.\n",
        "fetch",
        None,
        True,
    ),
    (
        "NPC: Bandits have a camp up on the ridge. Clear it out and the village will pay you a hundred gold "
        "pieces.\nPlayer: Consider it done.\nNPC: We are in your debt.\n",
        "clear_camp",
        None,
        True,
    ),
    (
        "NPC: Bring me a healing herb and I'll give you my old dagger.\n"
        "Player: Alright, I'll find one.\nNPC: Thank you, traveler.\n",
        "fetch",
        "dagger",
        True,
    ),
    (
        "NPC: Spiders have nested in the cellar. Kill five of them and my late husband's iron helmet is yours.\n"
        "Player: I'll deal with them.\nNPC: Be careful down there.\n",
        "kill_mob",
        "helmet",
        True,
    ),
    (
        "NPC: My neighbour stole my grandmother's locket. Recover it and you can have this lucky amulet.\n"
        "Player: Yes, I'll get it back.\nNPC: Oh, thank you!\n",
        "recover_stolen",
        "amulet",
        True,
    ),
    (
        "NPC: Deliver this parcel to the blacksmith's wife and I'll give you a pair of leather boots for your "
        "trouble.\nPlayer: Sure thing.\nNPC: Mind you don't open it.\n",
        "deliver",
        "boots",
        True,
    ),
    (
        "NPC: The troll king under the bridge must die. Slay him and I'll hand you the family longsword.\n"
        "Player: I accept.\nNPC: May the gods guide your blade.\n",
        "slay_boss",
        "longsword",
        True,
    ),
    (
        "NPC: Fetch me three mushrooms from the swamp. In exchange you'll get a health potion.\n"
        "Player: Okay.\nNPC: Don't eat any on the way!\n",
        "fetch",
        "potion",
        True,
    ),
    (
        "NPC: Kill the goblins raiding my farm, six of them, and I'll give you 40 gold and my hunting bow.\n"
        "Player: You have a deal.\nNPC: Thank the gods.\n",
        "kill_mob",
        "bow",
        True,
    ),
    (
        "NPC: Steal the ledger from the merchant's house for me. I'll pay 25 coins and throw in a wooden shield.\n"
        "Player: Fine, I'll do it.\nNPC: Quietly, mind you.\n",
        "steal",
        "shield",
        True,
    ),
    (
        "NPC: Bring back the golden chalice from the ruins and you'll get 60 gold pieces plus an enchanted ring.\n"
        "Player: I'm in.\nNPC: Good luck out there.\n",
        "fetch",
        "ring",
        True,
    ),
    (
        "NPC: Hunt down the wolf that killed my dog. I'll reward you with some silver and a warm fur cloak.\n"
        "Player: I will.\nNPC: He was a good dog.\n",
        None,
        "cloak",
        True,
    ),
    (
        "NPC: Could you fetch me a bucket of water from the well? I'd give you five coins.\n"
        "Player: No, I'm busy.\nNPC: Suit yourself.\n",
        None,
        None,
        False,
    ),
    (
        "NPC: Lovely weather today. The harvest looks good this year.\nPlayer: Indeed it does.\nNPC: Take care now.\n",
        None,
        None,
        False,
    ),
    (
        "NPC: They say a dragon sleeps under the mountain.\nPlayer: Interesting.\nNPC: Just a tale, probably.\n",
        None,
        None,
        False,
    ),
]


def measure(runs: int) -> dict:
    from llm.quest_system import QuestSystem

    analyzer = QuestSystem(None, None, None)
    seen = typed = typed_right = kept = lost = wrong = stray = 0
    seconds = []
    for conversation, want_type, want_item, has_quest in CASES:
        for _ in range(runs):
            start = time.monotonic()
            info = analyzer.analyze_conversation_for_quest(conversation)
            seconds.append(time.monotonic() - start)
            found = bool(info.get("has_quest"))
            got = QuestSystem._reward_name(info.get("reward_item", "")) if found else ""
            seen += found == has_quest
            if found and want_type:
                typed += 1
                typed_right += info.get("quest_type") == want_type
            if has_quest and want_item:
                kept += want_item in got.lower()
                lost += not got
                wrong += bool(got) and want_item not in got.lower()
            elif has_quest:
                stray += bool(got)
            runner.record(
                {
                    "case": conversation.split("\n")[0][5:70],
                    "has_quest": found,
                    "quest_type": info.get("quest_type"),
                    "want_type": want_type,
                    "reward": got,
                    "want_reward": want_item,
                    "item_name": info.get("item_name"),
                    "seconds": round(seconds[-1], 2),
                }
            )
            print(f"{'ok ' if found == has_quest else 'BAD'} {info.get('quest_type') or '-':15} {got!r}")

    item_runs = runs * sum(1 for _, _, item, quest in CASES if quest and item)
    coin_runs = runs * sum(1 for _, _, item, quest in CASES if quest and not item)
    return {
        "quest found or not, right": f"{seen}/{runs * len(CASES)}",
        "quest type right": f"{typed_right}/{typed}",
        "promised item kept": f"{kept}/{item_runs}",
        "promised item lost": lost,
        "a different item": wrong,
        "coin offer given an item": f"{stray}/{coin_runs}",
        "seconds per analysis": round(sum(seconds) / len(seconds), 2),
    }


if __name__ == "__main__":
    sys.exit(runner.main("quest_reward", measure))
