from __future__ import annotations

import json
import re
import threading
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core import dialogue_log, mainthread
from core.audio import play_sound
from core.utils import ConversationHistory
from game.entities.item_icons import draw_shape_with_border
from game.entities.items import potion_description
from game.quest import COUNTED_QUEST_TYPES
from llm import offline
from llm.decide import decide, later, odds
from llm.llm_request_queue import generate_response_stream_queued, warm_queued
from llm.quest_system import QuestSystem, coin_band
from ui import widgets
from ui.conversation_ui import ConversationUI
from ui.quest_tracker import QuestTracker

if TYPE_CHECKING:
    from game.entities.npcs import NPC
    from game.world import World
    from llm.name_generator import NPCNameGenerator

# Sentence enders, for trimming a reply that ran into the token cap mid-sentence.
SENTENCE_END_RE = re.compile(r"[.!?…]['\"]?(?=\s|$)")

# Stops handed to llama for dialogue: a reply is one turn, so the moment the model
# starts writing the player's turn for them, generation is done. A newline is not a stop
# here on purpose: the model sometimes opens with one, which would cut the reply to
# nothing. The stream itself drops everything past the first line break instead.
DIALOGUE_STOPS = ["Player:", "player:"]

# A bracketed fill-in the model left in a reply ("[amount] coins", "{item}"). Never
# something an NPC says out loud, so it is cut from what reaches the screen.
# The words that introduce the greeter's errand in their prompt. `offline.py` reads the
# quoted line after them back out, so the model-less greeter says the same thing.
GREETER_TASK = "the errand is:"

PLACEHOLDER_RE = re.compile(r"\s*[\[{][^\]}]{0,60}[\]}]")


# How a line of the player's can land, as put to the person hearing it. The labels are the
# keys of `Affinity.MOOD_SHIFT`, which says what each is worth.
MOODS = {
    "pleased": "It pleased you",
    "neutral": "It neither pleased nor bothered you",
    "annoyed": "It annoyed you",
    "insulted": "It insulted or offended you",
}
YES_NO = {"yes": "Yes", "no": "No"}
HAGGLE_ANSWERS = {
    "accept": "Agree to a good discount",
    "counter": "Offer only a small discount",
    "refuse": "Refuse to lower your prices",
}
PLEAS = {
    "good": "Good: sincere, apologetic, or offering to make amends",
    "poor": "Poor: dismissive or unconvincing",
    "bad": "Bad: insulting or threatening",
}
# What the player is shown in the box's header for each reading, and for how long.
REACTION_MS = 3500


# What an NPC is told about the quest they gave, per quest type: the line for a task just
# finished, the line reminding them what they asked for, and the line saying how far the
# player has got with it. Formatted against the quest's own fields, so adding a quest type
# is three strings here rather than another branch in `_build_system_prompt`.
QUEST_LINES = {
    "clear_camp": (
        "The player has just wiped out the bandit camp you sent them to ({description}). ",
        "You asked the player to wipe out a bandit camp ({description}). ",
        "The bandits are still there. ",
    ),
    "deliver": (
        "The player has just delivered your {item_name} to {recipient} ({description}). ",
        "You asked the player to carry your {item_name} to {recipient} ({description}). ",
        "They have not delivered it yet. ",
    ),
    "steal": (
        "The player has just brought you the {item_name} you asked them to steal ({description}). ",
        "You asked the player to steal a {item_name} from a neighbour's house ({description}). "
        "Keep your voice down about it. ",
        "They have not brought it to you yet. ",
    ),
    "slay_boss": (
        "The player has just slain the boss you asked them to defeat ({description}). ",
        "You asked the player to slay a powerful boss terrorizing the area ({description}). ",
        "They have not defeated it yet. ",
    ),
    "kill_mob": (
        "The player has just killed the {kill_count} {monster_kind}(s) you asked for ({description}). ",
        "You asked the player to kill {kill_count} {monster_kind}(s). ",
        "They have killed {kills_done}/{kill_count} so far. ",
    ),
}

# Fetching a named thing is the shape every other quest type falls back to: the objective
# is an item, so the status is simply whether the player is carrying it yet.
FETCH_LINES = (
    "The player has just brought you {item_name} that you asked for ({description}). ",
    "You asked the player to fetch {item_name}. ",
    "{fetch_status}",
)


# What a villager with no quest of their own is told they might want from the player.
VILLAGER_NEEDS = (
    "You may have needs or problems. "
    "The player can help you by fetching a specific item, dealing with dangerous creatures, "
    "recovering something that was stolen from you, clearing out a bandit camp, carrying "
    "something to someone who lives far away, or quietly taking something from a neighbour. "
    "You may offer coins, a specific item you own, or both as a reward. "
    "You cannot take part in these quests yourself "
    "(make up an excuse if needed, the player must not know) ! "
    "You may also simply want to chat. "
)


def _deal_line(discount: float) -> str:
    """What a merchant who has been asked for a better price remembers about their answer."""
    if discount <= 0:
        return "The player asked you for a better price and you refused; you will not change your mind. "
    return (
        f"The player asked you for a better price and you agreed to take {round(discount * 100)}% off "
        "everything you sell them; say so if it comes up, and go no lower. "
    )


def _ware_effect(item) -> str:
    """How a shop item is described to the merchant's LLM prompt: what it actually does."""
    if item.item_type == "potion":
        return potion_description(item).lower()
    return f"+{item.bonus} bonus"


def _strip_placeholders(text: str) -> str:
    """Drop a fill-in the model left in the reply, e.g. "here is [describe coins]".

    Asked to hand over a reward, the model sometimes writes the instruction back instead of
    a number, in brackets. Nothing in a spoken line is ever meant to be in brackets, so they
    come out whatever is inside them.
    """
    text = PLACEHOLDER_RE.sub(" ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _trim_to_sentence(text: str) -> str:
    """Cut a reply back to its last finished sentence.

    A reply that hits the token cap stops mid-word; showing half a sentence reads worse
    than showing one sentence less. Text with no sentence break at all is left alone
    rather than blanked.
    """
    text = text.strip()
    if not text or text[-1] in ".!?…\"'":
        return text
    ends = list(SENTENCE_END_RE.finditer(text))
    return text[: ends[-1].end()].strip() if ends else text


class DialogueManager:
    def __init__(self, screen, items, player, npcs):
        self.active = False
        # Keys that were already held when the box opened, ignored until they are released.
        self._ignored_keys: set[int] = set()
        self.current_npc = None
        self.system_prompt = ""
        self.conversation_ended = False
        self._is_first_message = False

        self.generator = None

        self.pending_quest_analysis = False
        self.pending_quest_completion = None
        # The quests whose hand-in is still being paid out on a worker, by id. A hand-in
        # waits on the model for the coins the NPC named, and the box can be opened and
        # closed again on the same NPC in that time: without this the second conversation
        # queued a second payout, and the quest was paid, rewarded and counted twice.
        self._completing: set[int] = set()
        self.quest_tracker = QuestTracker(screen)
        self.shop_requested = False
        self.shop_button_rect: pygame.Rect | None = None

        # Decisions read off the conversation (`llm/decide.py`), on a thread, and what to do
        # with them on the main thread once they land. One at a time, and the box takes no
        # typing while one is out: the next line would be read against a conversation that
        # has already moved on.
        self._judging = None
        self._on_judged = None
        # What talking has earned with this person so far this conversation
        # (`Affinity.TALK_GAIN_CAP`), and the reading shown in the box's header.
        self._talk_gain = 0.0
        self._reaction: tuple[str, tuple] | None = None
        self._reaction_until = 0
        # Talking an angry villager down rather than chatting (`Parley`): how many lines the
        # player has had, and whether it worked.
        self.parley = False
        self._parley_turns = 0
        self._parley_good = 0
        self._parley_won = False

        self.conversation = ConversationHistory()
        self.ui = ConversationUI(screen)
        self.quest_system = QuestSystem(items, player, npcs)
        self._npc_name_generator: NPCNameGenerator | None = None

    def _prompt_head(self, npc: NPC, context: str) -> str:
        """The start of this person's system prompt that is known before E is pressed, so it
        can be read into the cache while the talk prompt shows (`warm_for`). What depends on
        the conversation opening (a haggle, a delivery, a quest) comes after it."""
        role = "a merchant" if npc.is_merchant else "an NPC"
        head = (
            f"You are {npc.name}, {role} in an RPG with this context: {context}. The player comes to talk to you. "
            + self.quest_system.player.stats.persuasion_descriptor()
            + npc.temperament_descriptor()
            + npc.affinity_descriptor()
        )
        if npc.is_merchant:
            if npc.shop_ready and npc.shop_items:
                wares = ", ".join(
                    f"{item.name} ({item.rarity} {item.item_type}, {_ware_effect(item)})"
                    f" for {npc.shop_prices[item.id]} coins"
                    for item in npc.shop_items
                )
                head += f"You sell: {wares}. "
            else:
                head += "You are a trader who buys and sells adventuring gear. "
        elif not npc.has_active_quest and not npc.is_greeter:
            head += VILLAGER_NEEDS
        return head

    def warm_for(self, interaction, context: str | None):
        """Start reading the system prompt of whoever E would talk to, while nothing else
        wants the model, so their first line does not pay for it."""
        if self.active or interaction is None or interaction.kind != "npc" or context is None:
            return
        npc = interaction.target
        if npc.name is None:
            return
        head = self._prompt_head(npc, context)
        warm_queued((id(npc), head), head)

    def _build_system_prompt(self, npc: NPC, context: str, quest_complete: bool, delivered: str = "") -> str:
        system_prompt = self._prompt_head(npc, context)

        if npc.is_merchant:
            if npc.haggled:
                system_prompt += _deal_line(npc.discount)
            system_prompt += (
                "Reply naturally to messages in one short sentence. You can mention your wares but keep it brief."
            )
            return system_prompt

        if npc.has_active_quest:
            system_prompt += self._quest_lines(npc.quest, quest_complete)
        elif npc.is_greeter and (offer := self._greeter_offer(npc)) is not None:
            # The greeter has one thing to say and it is decided already: the errand
            # `_grant_greeter_quest` hands over when the box closes. Told to the model in
            # full so what they talk about is what lands, rather than a task of their own
            # invention followed by a different one in the tracker.
            system_prompt += (
                f"You walked over to the player, a newcomer, to ask for their help with one thing: {GREETER_TASK} "
                f'"{offer["quest_description"]}" '
                "Open with that request in your own words, and stick to it: do not invent any other "
                "task, item or reward. If they accept or agree, thank them and tell them to come back "
                "when it is done. "
            )
        elif npc.is_greeter:
            system_prompt += VILLAGER_NEEDS

        if delivered:
            system_prompt += (
                f"The player has just handed you {delivered}, sent to you by someone else. "
                "Take it and thank them; you owe them nothing, the sender pays them. "
            )

        system_prompt += (
            "Reply naturally to messages, staying within the context of the conversation, in one short sentence."
        )

        return system_prompt

    @staticmethod
    def _build_parley_prompt(npc: NPC, context: str) -> str:
        """An angry villager with the player at weapon point, and the player talking."""
        return (
            f"You are {npc.name}, an NPC in an RPG with this context: {context}. "
            "Your village has turned on the player for what they did here, and you have them at weapon point. "
            "They are trying to talk their way out of it. You are angry, but you would rather not spill blood "
            "if they can convince you to let it go. "
            + npc.temperament_descriptor()
            + npc.affinity_descriptor()
            + "Reply in character, in one short sentence."
        )

    def _quest_lines(self, quest, quest_complete: bool) -> str:
        """What to tell an NPC about the quest they gave: that the player has just finished
        it and is owed a reward, or what was asked for and how far they have got with it."""
        carrying = self.quest_system.carried_item(quest) is not None
        fields = {
            "description": quest.description,
            "item_name": quest.item_name,
            "recipient": quest.recipient_npc_name,
            "kill_count": quest.kill_count,
            "kills_done": quest.kills_done,
            "monster_kind": quest.target_monster_kind,
            "fetch_status": (
                "The player now has it in their inventory. " if carrying else "The player has not found it yet. "
            ),
        }
        known_type = quest.quest_type in QUEST_LINES
        done_line, asked_line, pending_line = QUEST_LINES.get(quest.quest_type, FETCH_LINES)

        if quest_complete:
            reward = (
                f" (your {quest.reward_item_name} and any coins you promised)"
                if quest.reward_item_name
                else " in coins"
            )
            # The band the payout is clamped into anyway (QuestSystem.promised_reward),
            # told to the NPC so the figure they say out loud is the figure the player is paid.
            low, high = coin_band(quest)
            return (
                done_line.format(**fields)
                + "Thank them and give them their reward"
                + reward
                + f". A job like this is worth between {low} and {high} coins."
                + " Say the exact number of coins yourself; never write a placeholder in brackets. "
            )

        # A quest that is neither one of the known types nor about a named item has nothing
        # to remind the NPC of, so it is left out of the prompt entirely.
        if not known_type and not quest.item_name:
            return ""

        promise = f"You promised them your {quest.reward_item_name} as a reward. " if quest.reward_item_name else ""
        return asked_line.format(**fields) + promise + pending_line.format(**fields)

    def interact_with_npc(self, npc: NPC, npc_name_generator: NPCNameGenerator, world: World, parley: bool = False):
        npc.assign_name(npc_name_generator)
        self._npc_name_generator = npc_name_generator
        self.parley = parley
        self._parley_turns = 0
        self._parley_good = 0
        self._parley_won = False
        self._talk_gain = 0.0
        self._reaction = None

        # Walking up to the person a parcel is addressed to is the delivery: it happens as
        # the conversation opens, so they can react to it in their first line.
        delivered_quest = None if parley else self.quest_system.on_delivery(npc)

        quest_complete = False
        if not parley and npc.has_active_quest and id(npc.quest) not in self._completing:
            quest = npc.quest
            if quest.quest_type in COUNTED_QUEST_TYPES:
                quest_complete = quest.kills_done >= quest.kill_count
            else:
                quest_complete = self.quest_system.carried_item(quest) is not None
        if quest_complete:
            self.pending_quest_completion = npc

        if parley:
            self.system_prompt = self._build_parley_prompt(npc, world.context)
        else:
            self.system_prompt = self._build_system_prompt(
                npc, world.context, quest_complete, delivered=delivered_quest.item_name if delivered_quest else ""
            )

        self.current_npc = npc
        self.active = True
        # Whatever was already pressed when the box opened does not belong in the box. Two
        # things would leak in: a key held down as E was pressed (the player walks up to
        # somebody with W held, and its repeat lands in the input), and any KEYDOWN queued
        # before this frame. The queue is dropped, and every key currently down is ignored
        # until it is released, so typing starts from the first key actually typed at the
        # box rather than from whatever the player was doing to get to it.
        pygame.event.clear(pygame.KEYDOWN)
        self._ignored_keys = {key for key, down in enumerate(pygame.key.get_pressed()) if down}
        self.conversation_ended = False
        self._is_first_message = True

        self.conversation.clear()
        self.ui.reset()
        self.pending_quest_analysis = False

        initial_prompt = "Player: Wait! Hear me out!\nNPC:" if parley else "Player: Hi!\nNPC:"
        self.generator = generate_response_stream_queued(
            initial_prompt,
            self.system_prompt,
            "First message",
            max_tokens=c.Hyperparameters.DIALOGUE_MAX_TOKENS,
            stop=DIALOGUE_STOPS,
            poll=True,
        )

    def handle_event(self, event, npc_name_generator: NPCNameGenerator):
        if not self.active:
            return False

        if event.type == pygame.MOUSEWHEEL:
            self.handle_scroll(event.y)
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.ui.close_button_rect().collidepoint(event.pos):
                self.close()
                npc_name_generator.start_generation()
                return True
            if (
                self.current_npc
                and self.current_npc.is_merchant
                and self.shop_button_rect
                and self.generator is None
                and self.shop_button_rect.collidepoint(event.pos)
            ):
                self.shop_requested = True
                self.close()
                npc_name_generator.start_generation()
            return True

        elif event.type == pygame.KEYUP:
            # Released: the key is the player's to type with from now on.
            self._ignored_keys.discard(event.key)
            return True

        elif event.type == pygame.KEYDOWN:
            # A key that was already down when the box opened is the player still walking,
            # not the player typing, so it is swallowed until they let go of it.
            if event.key in self._ignored_keys:
                return True

            if event.key == pygame.K_UP:
                self.handle_scroll(1)
            elif event.key == pygame.K_DOWN:
                self.handle_scroll(-1)
            else:
                if not self.conversation_ended:
                    self.handle_text_input(event)

            if event.key == pygame.K_ESCAPE:
                self.close()
                npc_name_generator.start_generation()

        return True

    def handle_text_input(self, event):
        # The reply still streaming in is the one the player is answering, so the box takes
        # nothing until it is finished. Before the stream was polled the main thread was
        # blocked here anyway; now it is not, and sending mid-stream would abandon a reply
        # halfway through writing itself.
        if not self.active or self.conversation_ended or self.generator is not None or self._judging is not None:
            return

        message = self.ui.handle_text_input(event)
        if message:
            self._send_chat_message(message)
            self.ui.auto_scroll(self.conversation, self.current_npc.name)

    def handle_scroll(self, direction: int):
        if not self.active:
            return
        self.ui.scroll(direction, self.conversation, self.current_npc.name)

    def update(self):
        if self.active and self._judging is not None and self._judging.done:
            pending, landed = self._judging, self._on_judged
            self._judging = self._on_judged = None
            landed(pending.poll())
        if self.active and self.generator is not None:
            try:
                partial = next(self.generator)
                # Nothing generated yet this frame: the stream is polled, not waited on, so
                # the game keeps running and the spinner keeps saying the NPC is thinking.
                if partial is None:
                    return
                self.conversation.update_last_assistant_message(_strip_placeholders(partial))
                self.ui.auto_scroll(self.conversation, self.current_npc.name)
            except StopIteration:
                self.generator = None
                was_first_message = self._is_first_message
                self._is_first_message = False

                content = self.conversation.get_last_message()["content"]

                # The model sometimes prefixes its reply with a speaker label; drop it
                if ":" in content:
                    cleaned_content = content.split(":", 1)[-1].strip()
                    if len(cleaned_content) <= 25:
                        content = cleaned_content

                # Trims a reply the token cap cut off mid-sentence.
                content = _trim_to_sentence(_strip_placeholders(content))

                self.conversation.update_last_assistant_message(content)
                self.ui.auto_scroll(self.conversation, self.current_npc.name)
                # Whether it is over, and how the player's last line landed, is asked once
                # the reply it drew is whole. The opening line answers nothing the player said.
                if not was_first_message:
                    self._judge_turn(content)

    def close(self):
        if not self.active:
            return

        # Escape can be pressed mid-stream; abandon the in-flight generator rather than
        # waiting for it, so closing the dialogue is never blocked on the LLM. A decision
        # still out is dropped with it: it was about a conversation that is over.
        self.generator = None
        self._judging = self._on_judged = None
        # Walking away from a parley is the villager's answer made for them, so a fight
        # cannot be paused by opening a box and shutting it again.
        if self.parley and not self._parley_won and self.quest_system.world is not None:
            self.quest_system.world.refuse_parley(self.current_npc)

        log_path = dialogue_log.write_conversation(self.current_npc, self.system_prompt, self.conversation)

        # The greeter's first quest is not the model's to find in the words: hearing them
        # out at all is accepting it, so it is granted here and now, and the analysis that
        # would otherwise run over the same conversation is skipped.
        greeter_intro = self._grant_greeter_quest()

        # A conversation the player never answered can't hold a quest they accepted, so it
        # isn't worth an analysis: that call would only make the next NPC's greeting wait
        # behind it for nothing.
        player_spoke = any(msg["role"] == "user" for msg in self.conversation.messages)
        npc = self.current_npc
        if player_spoke and not greeter_intro and not self.parley and not npc.has_active_quest and not npc.is_merchant:
            self.pending_quest_analysis = True

        self._execute_pending_actions(log_path)

        self.active = False
        self.system_prompt = ""
        self.conversation.clear()
        self.ui.reset()
        self.conversation_ended = False
        self.pending_quest_completion = None
        self.parley = False

    def _greeter_offer(self, npc: NPC) -> dict | None:
        """The first quest as `World.intro_offer` rolled it, off the greeter's own town."""
        world = self.quest_system.world
        village = world.village_at(npc.x, npc.y) if world is not None else None
        return world.intro_offer(village) if village is not None else None

    def _grant_greeter_quest(self) -> bool:
        """Hand the player the first quest when they hear the starting-town greeter out.

        Built locally from `World.intro_offer` rather than read out of the conversation,
        so it lands the same with a model, without one, or if the player closed the box
        without a word. Returns whether this was the greeter."""
        npc = self.current_npc
        if not npc.is_greeter or npc.has_active_quest:
            return npc.is_greeter
        offer = self._greeter_offer(npc)
        if offer is not None:
            self.quest_system.create_quest_from_analysis(npc, offer, self._npc_name_generator)
        if npc.quest is not None:
            npc.is_greeter = False
            npc.hailing = False
            if self.quest_system.world is not None:
                self.quest_system.world.greeter = None
            self.quest_tracker.notify_new_quest(npc.quest)
            play_sound("quest_new")
        return True

    def _execute_pending_actions(self, log_path):
        # Snapshot the conversation now: close() clears it right after this returns,
        # so the background threads must not read it directly.
        npc = self.current_npc
        conversation_text = self.conversation.format_for_prompt()
        last_msg = self.conversation.get_last_message()

        # Quest completion first (uses conversation context for rewards)
        if self.pending_quest_completion:
            self._completing.add(id(self.pending_quest_completion.quest))
            threading.Thread(
                target=self._execute_quest_completion,
                args=(self.pending_quest_completion, last_msg, log_path),
                daemon=True,
            ).start()
            self.pending_quest_completion = None

        # Quest analysis second (only for new quests)
        if self.pending_quest_analysis:
            threading.Thread(
                target=self._execute_quest_analysis, args=(npc, conversation_text, log_path), daemon=True
            ).start()
            self.pending_quest_analysis = False

    def draw(self):
        if not self.active:
            return

        self.update()
        reaction = self._reaction if pygame.time.get_ticks() < self._reaction_until else None
        self.ui.draw(self.current_npc.name, self.conversation, self.conversation_ended, reaction)

        if self.current_npc.is_merchant and self.generator is None:
            box_height = self.ui.BOX_HEIGHT
            box_y = c.Screen.HEIGHT - box_height - 25
            btn_w, btn_h = 130, 30
            # Left of the close cross in the same corner, not under it.
            btn_x = self.ui.close_button_rect().left - 12 - btn_w
            btn_y = box_y + 12
            self.shop_button_rect = pygame.Rect(btn_x, btn_y, btn_w, btn_h)

            mouse = pygame.mouse.get_pos()
            hover = self.shop_button_rect.collidepoint(mouse)
            widgets.draw_button(
                self.ui.screen,
                self.shop_button_rect,
                "Shop",
                c.Fonts.button,
                hovered=hover,
                text_color=(100, 255, 100),
                accent=(100, 255, 100),
            )
            self._draw_purse(self.shop_button_rect.left - 14, self.shop_button_rect.centery)
        else:
            self.shop_button_rect = None

    def _draw_purse(self, right: int, centery: int):
        """The player's coins beside the Shop button. Haggling with a merchant is the one
        conversation where what's in the purse decides what to say next."""
        amount = c.Fonts.button.render(str(self.quest_system.player.coins), True, c.Colors.ACCENT)
        self.ui.screen.blit(amount, (right - amount.get_width(), centery - amount.get_height() // 2))
        draw_shape_with_border(self.ui.screen, "coin", (right - amount.get_width() - 16, centery), 8, (235, 205, 80), 2)

    def _send_chat_message(self, message: str):
        if self.conversation_ended:
            return

        self.conversation.add_user_message(message)
        self._is_first_message = False

        # A merchant hears a line as a haggle or not before answering it, so what they say
        # back is the deal they actually struck.
        npc = self.current_npc
        conversation_text = self.conversation.format_for_prompt()
        if self.parley:
            args = (npc.temperament, conversation_text)
            self._await(lambda: self._read_plea(*args), self._land_plea)
            return
        # A warning standing against the player here is something an apology can take back.
        world = self.quest_system.world
        sorry = world is not None and bool(world.warnings_at(npc.x, npc.y))
        if npc.is_merchant or sorry:
            haggle = (npc.haggled, npc.affinity, npc.temperament) if npc.is_merchant else None
            args = (haggle, sorry, self.system_prompt, conversation_text, message)
            self._await(lambda: self._read_before_reply(*args), self._land_before_reply)
            return
        self._reply()

    def _await(self, work, landed):
        self._judging = later(work)
        self._on_judged = landed

    def _react(self, text: str, color: tuple):
        self._reaction = (text, color)
        self._reaction_until = pygame.time.get_ticks() + REACTION_MS

    def _reply(self):
        """Ask for the NPC's next line over the conversation as it stands."""
        conversation_text = self.conversation.format_for_prompt()
        self.generator = generate_response_stream_queued(
            conversation_text + "\nNPC:",
            self.system_prompt,
            "Continuing conversation",
            max_tokens=c.Hyperparameters.DIALOGUE_MAX_TOKENS,
            stop=DIALOGUE_STOPS,
            poll=True,
        )

    @classmethod
    def _read_before_reply(cls, haggle, sorry, system_prompt, conversation_text, message) -> dict:
        """What has to be known before the NPC answers a line, so the answer can say it: a
        haggle struck with a merchant, an apology accepted."""
        out = {}
        if haggle is not None:
            out["haggle"] = cls._read_haggle(*haggle, system_prompt, conversation_text, message)
        if sorry:
            out["apology"] = decide(
                "The player was warned by an NPC's village for something they did there.\n"
                f"Conversation:\n{conversation_text}",
                "Is the player's last line a sincere apology?",
                YES_NO,
                "You judge conversations in an RPG game.",
                "conversation",
                offline=offline.says(offline.APOLOGY_RE, message),
                draw=False,
            ).choice
        return out

    def _land_before_reply(self, out: dict | None):
        out = out or {}
        npc = self.current_npc
        world = self.quest_system.world
        if "haggle" in out:
            self._land_haggle(out["haggle"])
        if out.get("apology") == "yes" and world is not None and world.forgive_strikes(npc):
            self.system_prompt += "The player has apologised for what they did here and you accept it. "
            self._react(f"{npc.name} lets it go", c.Colors.GREEN)
        self._reply()

    @staticmethod
    def _read_haggle(haggled, affinity, temperament, system_prompt, conversation_text, message):
        """The worker's half of a haggle: whether the player's line asks for a better price,
        and if it is the first time, what the merchant says to it. None when it was not a
        haggle at all, "again" when it was one already answered."""
        asked = decide(
            conversation_text,
            "Is the player asking you for a lower price, a discount or a better deal?",
            YES_NO,
            system_prompt,
            "haggle",
            offline=offline.says(offline.HAGGLE_RE, message),
            draw=False,
        )
        if asked.choice == "no":
            return None
        if haggled:
            return "again"
        liking = affinity / c.Affinity.START
        return decide(
            conversation_text,
            "The player wants a better price from you. What do you do?",
            HAGGLE_ANSWERS,
            system_prompt,
            "haggle",
            offline=odds(
                c.Haggle.OFFLINE,
                {"accept": liking, "refuse": 1 / max(liking, 0.1)},
                {"refuse": 2.0} if temperament == "greedy" else {"accept": 1.6} if temperament == "kind" else None,
            ),
        )

    def _land_haggle(self, answer):
        npc = self.current_npc
        if answer == "again":
            self.system_prompt += "The player is pushing for a better price again; your answer stands. "
        elif answer is not None:
            npc.haggled = True
            npc.discount = c.Haggle.DISCOUNT[answer.choice]
            self.system_prompt += _deal_line(npc.discount)
            percent = round(npc.discount * 100)
            if answer.choice == "refuse":
                npc.affinity = max(c.Affinity.MIN, npc.affinity + c.Haggle.REFUSE_AFFINITY)
                self._react(f"{npc.name} won't budge", c.Colors.ORANGE)
            elif answer.choice == "accept":
                self._react(f"{npc.name} takes {percent}% off", c.Colors.GREEN)
            else:
                self._react(f"{npc.name} comes down {percent}%", c.Colors.YELLOW)

    def _judge_turn(self, reply: str):
        """Ask how the player's last line landed and whether the conversation is over, off
        the conversation as it now stands, which is what the cache already holds."""
        if self.parley:
            return
        player_line = next((m["content"] for m in reversed(self.conversation.messages) if m["role"] == "user"), "")
        args = (
            self.system_prompt,
            self.conversation.format_for_prompt(),
            player_line,
            reply,
        )
        self._await(lambda: self._read_turn(*args), self._land_turn)

    @staticmethod
    def _read_turn(system_prompt, conversation_text, player_line, reply) -> dict:
        """The worker's half of `_judge_turn`: every question about this turn, one after
        the other over the same prefix."""
        out = {
            "mood": decide(
                conversation_text,
                "How did you take the player's last line to you?",
                MOODS,
                system_prompt,
                "conversation",
                offline={"neutral": 1.0},
            ).choice
        }
        # A reply that asks the player something is waiting on an answer, whatever else it says.
        if not reply.rstrip().endswith("?"):
            out["end"] = decide(
                conversation_text,
                "Is this conversation over now, with both of you done talking?",
                YES_NO,
                system_prompt,
                "conversation",
                offline=offline.says(offline.FAREWELL_RE, player_line),
                draw=False,
            ).choice
        return out

    def _land_turn(self, out: dict | None):
        if not out:
            return
        npc = self.current_npc
        shift = c.Affinity.MOOD_SHIFT[out["mood"]]
        if shift > 0:
            shift = min(shift, c.Affinity.TALK_GAIN_CAP - self._talk_gain)
            self._talk_gain += shift
        npc.affinity = max(c.Affinity.MIN, min(c.Affinity.MAX, npc.affinity + shift))
        if out["mood"] == "pleased" and shift > 0:
            self._react(f"{npc.name} liked that", c.Colors.GREEN)
        elif out["mood"] == "annoyed":
            self._react(f"{npc.name} didn't like that", c.Colors.ORANGE)
        elif out["mood"] == "insulted":
            self._react(f"{npc.name} is offended", c.Colors.RED)
        if out.get("end") == "yes":
            self.conversation_ended = True

    @staticmethod
    def _read_plea(temperament, conversation_text) -> str:
        """The worker's half of a parley line: how good the player's last line is at calming
        the villager down, asked of the model as an onlooker. Asked in the villager's own
        angry voice it found nothing convincing, however sincere."""
        return decide(
            "An angry villager has the player at weapon point, and the player is trying to calm them down.\n"
            f"Conversation:\n{conversation_text}",
            "How good is the player's last line at calming the villager?",
            PLEAS,
            "You judge conversations in an RPG game.",
            "parley",
            offline=odds(c.Parley.OFFLINE, c.Parley.TEMPERAMENT_ODDS.get(temperament)),
        ).choice

    def _land_plea(self, plea: str | None):
        """Count the line, settle the parley if it is settled, and tell the villager what they
        decided so the line they answer with is that decision."""
        npc = self.current_npc
        world = self.quest_system.world
        self._parley_turns += 1
        if plea == "good":
            self._parley_good += 1
        if plea != "bad" and self._parley_good >= c.Parley.PLEAS_NEEDED and world is not None:
            self._parley_won = True
            self.conversation_ended = True
            world.stand_down(npc)
            self.system_prompt += "They have convinced you. You lower your weapon and let it go; say so. "
            self._react(f"{npc.name} lowers their weapon", c.Colors.GREEN)
            play_sound("quest_complete")
        elif plea == "bad" or self._parley_turns >= c.Parley.TURNS:
            self.conversation_ended = True
            if world is not None:
                world.refuse_parley(npc)
            self.system_prompt += "You have heard enough. You raise your weapon to attack; say so. "
            self._react(f"{npc.name} has heard enough", c.Colors.RED)
        elif plea == "good":
            self.system_prompt += "That moved you a little, but you are not convinced yet. "
            self._react(f"{npc.name} hesitates", c.Colors.YELLOW)
        self._reply()

    def _execute_quest_analysis(self, npc: NPC, conversation_text: str, log_path):
        """The worker's half: the model reads the conversation. What it found is built into
        the world on the main thread (`_land_quest`), since building one spawns items, a
        thief or a boss into lists the frame is walking."""
        if not conversation_text:
            return
        quest_info = self.quest_system.analyze_conversation_for_quest(conversation_text)
        dialogue_log.append_section(log_path, "Quest analysis", json.dumps(quest_info, ensure_ascii=False))
        if quest_info["has_quest"]:
            mainthread.post(self._land_quest, npc, quest_info)

    def _land_quest(self, npc: NPC, quest_info: dict):
        self.quest_system.create_quest_from_analysis(npc, quest_info, self._npc_name_generator)
        quest = npc.quest
        if quest:
            self.quest_tracker.notify_new_quest(quest)
            play_sound("quest_new")

    def _execute_quest_completion(self, npc: NPC, last_msg, log_path):
        """The worker's half: the coins the NPC's parting line named, which may cost a model
        call. The payout itself (`_pay_out`) is main-thread work, and the quest stays marked
        as completing until it has actually run there."""
        quest = npc.quest
        try:
            if last_msg and quest:
                reward = self.quest_system.promised_reward(last_msg["content"], quest)
                quest.reward_coins = reward
                dialogue_log.append_section(log_path, "Quest completion", f"Reward: {reward} coins")
        except Exception:
            self._completing.discard(id(quest))
            raise
        mainthread.post(self._pay_out, npc, quest)

    def _pay_out(self, npc: NPC, quest):
        try:
            self.quest_system.complete_quest(npc)
            play_sound("quest_complete")
        finally:
            self._completing.discard(id(quest))
