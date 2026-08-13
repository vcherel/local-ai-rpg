from __future__ import annotations

import json
import re
import threading
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core import dialogue_log
from core.audio import play_sound
from core.utils import ConversationHistory
from game.entities.items import potion_description
from llm.llm_request_queue import generate_response_stream_queued
from llm.quest_system import QuestSystem
from ui import widgets
from ui.conversation_ui import ConversationUI
from ui.quest_tracker import QuestTracker

if TYPE_CHECKING:
    from game.entities.npcs import NPC
    from game.world import World
    from llm.name_generator import NPCNameGenerator

END_MARKER = "[END]"

# The model is asked for "[END]" but writes it however it likes: bare END, on its own
# line, bolded, parenthesised, "[end of conversation]". Bracketed forms match in any
# case; a bare END must be uppercase so an NPC saying "we must end this" isn't a goodbye.
END_RE = re.compile(
    # [END], (end of conversation), **[END]**, in any case
    r"(?i:[\*\s]*[\[\(]\s*end\b[^\]\)]*[\]\)]?[\*\s]*)"
    # A bare END, uppercase and closing the reply: an all-caps word mid-sentence
    # ("I will END this curse") is emphasis, not a goodbye.
    r"|(?<=[.!?…\"'\)\n])\s*\*{0,2}\bEND\b\*{0,2}[\s.]*$"
)

# Sentence enders used to trim a reply that ran into the token cap mid-sentence.
SENTENCE_END_RE = re.compile(r"[.!?…]['\"]?(?=\s|$)")

# Stops handed to llama for dialogue: a reply is one turn, so the moment the model
# starts writing the player's turn for them, generation is done. A newline is not a stop
# here on purpose: the model sometimes opens with one, which would cut the reply to
# nothing. The stream itself drops everything past the first line break instead.
DIALOGUE_STOPS = ["Player:", "player:"]


def _ware_effect(item) -> str:
    """How a shop item is described to the merchant's LLM prompt: what it actually does."""
    if item.item_type == "potion":
        return potion_description(item).lower()
    return f"+{item.bonus} bonus"


def _trim_partial_marker(text: str) -> str:
    # Hide an end marker that is still streaming in, e.g. a trailing "[EN"
    upper = text.upper()
    for length in range(len(END_MARKER) - 1, 0, -1):
        if upper.endswith(END_MARKER[:length]):
            return text[:-length]
    return text


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
        self._opened_at_ms = 0
        self.current_npc = None
        self.waiting_for_llm = False
        self.system_prompt = ""
        self.conversation_ended = False
        self._is_first_message = False

        self.generator = None

        self.pending_quest_analysis = False
        self.pending_quest_completion = None
        self.quest_tracker = QuestTracker(screen)
        self.shop_requested = False
        self.shop_button_rect: pygame.Rect | None = None

        self.conversation = ConversationHistory()
        self.ui = ConversationUI(screen)
        self.quest_system = QuestSystem(items, player, npcs)
        self._npc_name_generator: NPCNameGenerator | None = None

    def _build_system_prompt(self, npc: NPC, context: str, quest_complete: bool) -> str:
        persuasion_hint = self.quest_system.player.stats.persuasion_descriptor()
        affinity_hint = npc.affinity_descriptor()

        if npc.is_merchant:
            system_prompt = (
                (
                    f"You are {npc.name}, a merchant in an RPG with this context: {context}. "
                    "The player comes to talk to you. "
                )
                + persuasion_hint
                + affinity_hint
            )
            if npc.shop_ready and npc.shop_items:
                wares = ", ".join(
                    f"{item.name} ({item.rarity} {item.item_type}, {_ware_effect(item)})"
                    f" for {npc.shop_prices[item.id]} coins"
                    for item in npc.shop_items
                )
                system_prompt += f"You sell: {wares}. "
            else:
                system_prompt += "You are a trader who buys and sells adventuring gear. "
            system_prompt += (
                "Reply naturally to messages in one short sentence. You can mention your wares but keep it brief. "
                "Usually just reply normally. Only if the player says goodbye, or you have clearly finished "
                f"your business with them, add {END_MARKER} after your reply."
            )
            return system_prompt

        system_prompt = (
            (f"You are {npc.name}, an NPC in an RPG with this context: {context}. The player comes to talk to you. ")
            + persuasion_hint
            + affinity_hint
        )

        if npc.has_active_quest:
            quest = npc.quest
            if quest_complete:
                if quest.quest_type == "slay_boss":
                    system_prompt += (
                        f"The player has just slain the boss you asked them to defeat ({quest.description}). "
                        f"Thank them and give them their reward"
                    )
                elif quest.quest_type == "kill_mob":
                    system_prompt += (
                        f"The player has just killed the {quest.kill_count} {quest.target_monster_kind}(s) "
                        f"you asked for ({quest.description}). Thank them and give them their reward"
                    )
                else:
                    system_prompt += (
                        f"The player has just brought you {quest.item_name} that you asked for "
                        f"({quest.description}). Thank them and give them their reward"
                    )
                if quest.reward_item_name:
                    system_prompt += f" (your {quest.reward_item_name} and any coins you promised)"
                else:
                    system_prompt += " in coins"
                system_prompt += ". "
            elif quest.quest_type == "slay_boss":
                system_prompt += (
                    f"You asked the player to slay a powerful boss terrorizing the area ({quest.description}). "
                )
                if quest.reward_item_name:
                    system_prompt += f"You promised them your {quest.reward_item_name} as a reward. "
                system_prompt += "They have not defeated it yet. "
            elif quest.quest_type == "kill_mob":
                system_prompt += f"You asked the player to kill {quest.kill_count} {quest.target_monster_kind}(s). "
                if quest.reward_item_name:
                    system_prompt += f"You promised them your {quest.reward_item_name} as a reward. "
                system_prompt += f"They have killed {quest.kills_done}/{quest.kill_count} so far. "
            elif quest.item_name:
                system_prompt += f"You asked the player to fetch {quest.item_name}. "
                if quest.reward_item_name:
                    system_prompt += f"You promised them your {quest.reward_item_name} as a reward. "
                if quest.item and quest.item in self.quest_system.player.inventory:
                    system_prompt += "The player now has it in their inventory. "
                else:
                    system_prompt += "The player has not found it yet. "
        else:
            system_prompt += (
                "You may have needs or problems. "
                "The player can help you by fetching a specific item, dealing with dangerous creatures, "
                "or recovering something that was stolen from you. "
                "You may offer coins, a specific item you own, or both as a reward. "
                "You cannot take part in these quests yourself "
                "(make up an excuse if needed, the player must not know) ! "
                "You may also simply want to chat. "
            )

        system_prompt += (
            "Reply naturally to messages, staying within the context of the conversation, in one short sentence. "
            "Usually just reply normally. Only if the player says goodbye, or you have clearly finished "
            f"your business with them, add {END_MARKER} after your reply."
        )

        return system_prompt

    def interact_with_npc(self, npc: NPC, npc_name_generator: NPCNameGenerator, world: World):
        npc.assign_name(npc_name_generator)
        self._npc_name_generator = npc_name_generator

        quest_complete = False
        if npc.has_active_quest:
            quest = npc.quest
            if quest.quest_type in ("kill_mob", "slay_boss"):
                quest_complete = quest.kills_done >= quest.kill_count
            else:
                quest_complete = quest.item in self.quest_system.player.inventory
        if quest_complete:
            self.pending_quest_completion = npc

        self.system_prompt = self._build_system_prompt(npc, world.context, quest_complete)

        self.current_npc = npc
        self.active = True
        self._opened_at_ms = pygame.time.get_ticks()
        self.waiting_for_llm = True
        self.conversation_ended = False
        self._is_first_message = True

        self.conversation.clear()
        self.ui.reset()
        self.pending_quest_analysis = False

        initial_prompt = "Player: Hi!\nNPC:"
        self.generator = generate_response_stream_queued(
            initial_prompt,
            self.system_prompt,
            "First message",
            max_tokens=c.Hyperparameters.DIALOGUE_MAX_TOKENS,
            stop=DIALOGUE_STOPS,
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

        elif event.type == pygame.KEYDOWN:
            # Swallow keys for a brief window after opening (e.g. a movement key pressed
            # right as E was pressed), since its KEYDOWN can arrive a frame late and
            # otherwise leaks into the input box.
            if pygame.time.get_ticks() - self._opened_at_ms < 200:
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
        if not self.active or self.conversation_ended:
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
        if self.active and self.generator is not None:
            try:
                partial = next(self.generator)
                match = END_RE.search(partial)
                if match:
                    stripped = partial[: match.start()].rstrip()
                    # The model sometimes tags [END] on the opening greeting, or right
                    # after asking the player a question, both premature. Drop the tag
                    # but keep the conversation open in those cases.
                    if not self._is_first_message and not stripped.endswith("?"):
                        self.conversation_ended = True
                    partial = stripped
                else:
                    partial = _trim_partial_marker(partial)
                self.conversation.update_last_assistant_message(partial)
                self.ui.auto_scroll(self.conversation, self.current_npc.name)
                self.waiting_for_llm = False
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

                # Second pass on the finished text: catches an end marker that only
                # became recognisable once the reply was complete, and trims a reply the
                # token cap cut off mid-sentence.
                match = END_RE.search(content)
                if match:
                    content = content[: match.start()].rstrip()
                    if not was_first_message and not content.endswith("?"):
                        self.conversation_ended = True
                content = _trim_to_sentence(content)

                self.conversation.update_last_assistant_message(content)
                self.ui.auto_scroll(self.conversation, self.current_npc.name)

    def close(self):
        if not self.active:
            return

        # Escape can be pressed mid-stream; abandon the in-flight generator rather than
        # waiting for it, so closing the dialogue is never blocked on the LLM.
        self.generator = None

        log_path = dialogue_log.write_conversation(self.current_npc, self.system_prompt, self.conversation)

        # A conversation the player never answered can't hold a quest they accepted, so it
        # isn't worth an analysis: that call would only make the next NPC's greeting wait
        # behind it for nothing.
        player_spoke = any(msg["role"] == "user" for msg in self.conversation.messages)
        if player_spoke and not self.current_npc.has_active_quest and not self.current_npc.is_merchant:
            self.pending_quest_analysis = True

        self._execute_pending_actions(log_path)

        self.active = False
        self.waiting_for_llm = False
        self.system_prompt = ""
        self.conversation.clear()
        self.ui.reset()
        self.conversation_ended = False
        self.pending_quest_completion = None

    def _execute_pending_actions(self, log_path):
        # Snapshot the conversation now: close() clears it right after this returns,
        # so the background threads must not read it directly.
        npc = self.current_npc
        conversation_text = self.conversation.format_for_prompt()
        last_msg = self.conversation.get_last_message()

        # Quest completion first (uses conversation context for rewards)
        if self.pending_quest_completion:
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
        self.ui.draw(self.current_npc.name, self.conversation, self.conversation_ended)

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
        else:
            self.shop_button_rect = None

    def _send_chat_message(self, message: str):
        if self.conversation_ended:
            return

        self.conversation.add_user_message(message)
        self._is_first_message = False

        conversation_text = self.conversation.format_for_prompt()

        self.generator = generate_response_stream_queued(
            conversation_text + "\nNPC:",
            self.system_prompt,
            "Continuing conversation",
            max_tokens=c.Hyperparameters.DIALOGUE_MAX_TOKENS,
            stop=DIALOGUE_STOPS,
        )

    def _execute_quest_analysis(self, npc: NPC, conversation_text: str, log_path):
        if conversation_text:
            quest_info = self.quest_system.analyze_conversation_for_quest(conversation_text)
            dialogue_log.append_section(log_path, "Quest analysis", json.dumps(quest_info, ensure_ascii=False))
            if quest_info["has_quest"]:
                self.quest_system.create_quest_from_analysis(npc, quest_info, self._npc_name_generator)
                quest = npc.quest
                if quest:
                    self.quest_tracker.notify_new_quest(quest)
                    play_sound("quest_new")

    def _execute_quest_completion(self, npc: NPC, last_msg, log_path):
        if last_msg and npc.quest:
            reward = self.quest_system.extract_and_give_reward(last_msg["content"])
            npc.quest.reward_coins = reward
            dialogue_log.append_section(log_path, "Quest completion", f"Reward: {reward} coins")

        self.quest_system.complete_quest(npc)
        play_sound("quest_complete")
