from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core import dialogue_log
from core.audio import play_sound
from core.utils import ConversationHistory
from llm.llm_request_queue import generate_response_stream_queued
from llm.quest_system import QuestSystem
from ui.conversation_ui import ConversationUI
from ui.notification import QuestNotification

if TYPE_CHECKING:
    from game.entities.npcs import NPC
    from game.world import World
    from llm.name_generator import NPCNameGenerator

END_MARKER = "[END]"


def _trim_partial_marker(text: str) -> str:
    # Hide an end marker that is still streaming in, e.g. a trailing "[EN"
    upper = text.upper()
    for length in range(len(END_MARKER) - 1, 0, -1):
        if upper.endswith(END_MARKER[:length]):
            return text[:-length]
    return text


class DialogueManager:
    def __init__(self, screen, items, player):
        self.active = False
        self.opened_this_frame = False
        self.current_npc = None
        self.waiting_for_llm = False
        self.system_prompt = ""
        self.conversation_ended = False

        self.generator = None

        self.pending_quest_analysis = False
        self.pending_quest_completion = None
        self.notification = QuestNotification(screen)
        self.shop_requested = False
        self.shop_button_rect: pygame.Rect | None = None

        self.conversation = ConversationHistory()
        self.ui = ConversationUI(screen)
        self.quest_system = QuestSystem(items, player)

    def _build_system_prompt(self, npc: NPC, context: str, quest_complete: bool) -> str:
        if npc.is_merchant:
            system_prompt = (
                f"You are {npc.name}, a merchant in an RPG with this context: {context}. "
                "The player comes to talk to you. "
            )
            if npc.shop_ready and npc.shop_items:
                wares = ", ".join(
                    f"{item.name} ({item.rarity} {item.item_type}, +{item.bonus} bonus)"
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
            f"You are {npc.name}, an NPC in an RPG with this context: {context}. The player comes to talk to you."
        )

        if npc.has_active_quest:
            quest = npc.quest
            if quest_complete:
                system_prompt += (
                    f"The player has just brought you {quest.item_name} that you asked for ({quest.description}). "
                    f"Thank them and give them their reward"
                )
                if quest.reward_item_name:
                    system_prompt += f" (your {quest.reward_item_name} and any coins you promised)"
                else:
                    system_prompt += " in coins"
                system_prompt += ". "
            elif quest.item:
                system_prompt += f"You asked the player to fetch {quest.item_name}. "
                if quest.reward_item_name:
                    system_prompt += f"You promised them your {quest.reward_item_name} as a reward. "
                if quest.item in self.quest_system.player.inventory:
                    system_prompt += "The player now has it in their inventory. "
                else:
                    system_prompt += "The player has not found it yet. "
        else:
            system_prompt += (
                "You may have needs or problems. "
                "The player can help you by going to fetch a specific item. "
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

        quest_complete = False
        if npc.has_active_quest and npc.quest.item in self.quest_system.player.inventory:
            quest_complete = True
            self.pending_quest_completion = npc

        self.system_prompt = self._build_system_prompt(npc, world.context, quest_complete)

        self.current_npc = npc
        self.active = True
        self.opened_this_frame = True
        self.waiting_for_llm = True
        self.conversation_ended = False

        self.conversation.clear()
        self.ui.reset()
        self.pending_quest_analysis = False

        initial_prompt = "Player: Hi!\nNPC:"
        self.generator = generate_response_stream_queued(initial_prompt, self.system_prompt, "First message")

    def handle_event(self, event, npc_name_generator: NPCNameGenerator):
        if not self.active:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
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
            # Swallow keys queued in the same frame the dialogue opened (e.g. a movement
            # key still held while pressing E), so they don't leak into the input box.
            if self.opened_this_frame:
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
        self.ui.handle_key_scroll(direction, self.conversation, self.current_npc.name)

    def update(self):
        if self.active and self.generator is not None:
            try:
                partial = next(self.generator)
                marker_pos = partial.upper().find(END_MARKER)
                if marker_pos != -1:
                    self.conversation_ended = True
                    partial = partial[:marker_pos].rstrip()
                else:
                    partial = _trim_partial_marker(partial)
                self.conversation.update_last_assistant_message(partial)
                self.ui.auto_scroll(self.conversation, self.current_npc.name)
                self.waiting_for_llm = False
            except StopIteration:
                self.generator = None

                last_msg = self.conversation.get_last_message()

                # The model sometimes prefixes its reply with a speaker label; drop it
                if ":" in last_msg["content"]:
                    cleaned_content = last_msg["content"].split(":", 1)[-1].strip()
                    if len(cleaned_content) <= 25:
                        self.conversation.update_last_assistant_message(cleaned_content)

    def close(self):
        if self.active and self.generator is None:
            log_path = dialogue_log.write_conversation(self.current_npc, self.system_prompt, self.conversation)

            if not self.current_npc.has_active_quest and not self.current_npc.is_merchant:
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
            box_height = 300
            box_y = c.Screen.HEIGHT - box_height - 25
            btn_w, btn_h = 130, 30
            btn_x = c.Screen.WIDTH - 40 - btn_w
            btn_y = box_y + 10
            self.shop_button_rect = pygame.Rect(btn_x, btn_y, btn_w, btn_h)

            mouse = pygame.mouse.get_pos()
            color = c.Colors.BUTTON_HOVERED if self.shop_button_rect.collidepoint(mouse) else c.Colors.BUTTON
            pygame.draw.rect(self.ui.screen, color, self.shop_button_rect, border_radius=4)
            pygame.draw.rect(self.ui.screen, (100, 255, 100), self.shop_button_rect, 2, border_radius=4)
            label = c.Fonts.button.render("Shop", True, (100, 255, 100))
            self.ui.screen.blit(label, label.get_rect(center=self.shop_button_rect.center))
        else:
            self.shop_button_rect = None

    def _send_chat_message(self, message: str):
        if self.conversation_ended:
            return

        self.conversation.add_user_message(message)

        conversation_text = self.conversation.format_for_prompt()
        conversation_text += f"Player: {message}"

        self.generator = generate_response_stream_queued(
            conversation_text + "\nNPC:", self.system_prompt, "Continuing conversation"
        )

    def _execute_quest_analysis(self, npc: NPC, conversation_text: str, log_path):
        if conversation_text:
            quest_info = self.quest_system.analyze_conversation_for_quest(conversation_text)
            dialogue_log.append_section(log_path, "Quest analysis", json.dumps(quest_info, ensure_ascii=False))
            if quest_info["has_quest"]:
                self.quest_system.create_quest_from_analysis(npc, quest_info)
                quest = npc.quest
                if quest:
                    self.notification.show(quest)
                    play_sound("quest_new")

    def _execute_quest_completion(self, npc: NPC, last_msg, log_path):
        if last_msg and npc.quest:
            reward = self.quest_system.extract_and_give_reward(last_msg["content"])
            npc.quest.reward_coins = reward
            dialogue_log.append_section(log_path, "Quest completion", f"Reward: {reward} coins")

        self.quest_system.complete_quest(npc)
        play_sound("quest_complete")
