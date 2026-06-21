from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pygame

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


class DialogueManager:
    def __init__(self, screen, items, player):
        self.active = False
        self.current_npc = None
        self.waiting_for_llm = False
        self.system_prompt = ""
        self.conversation_ended = False

        self.generator = None

        self.pending_quest_analysis = False
        self.pending_quest_completion = None
        self.notification = QuestNotification(screen)

        self.conversation = ConversationHistory()
        self.ui = ConversationUI(screen)
        self.quest_system = QuestSystem(items, player)

    def _build_system_prompt(self, npc: NPC, context: str, quest_complete: bool) -> str:
        system_prompt = (
            f"You are {npc.name}, an NPC in an RPG with this context: {context}. The player comes to talk to you."
        )

        if npc.has_active_quest:
            quest = npc.quest
            if quest_complete:
                system_prompt += (
                    f"The player has just brought you {quest.item_name} that you asked for ({quest.description}). "
                    f"Thank them and mention their reward in coins. "
                )
            elif quest.item:
                system_prompt += f"You asked the player to fetch {quest.item_name}. "
                if quest.item in self.quest_system.player.inventory:
                    system_prompt += "The player now has it in their inventory. "
                else:
                    system_prompt += "The player has not found it yet. "
        else:
            system_prompt += (
                "You may have needs or problems. "
                "The player can help you by going to fetch a specific item. "
                "You cannot take part in these quests yourself "
                "(make up an excuse if needed, the player must not know) ! "
                "You may also simply want to chat. "
            )

        system_prompt += (
            "Reply naturally to messages, staying within the context of the conversation, in one short sentence."
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

        elif event.type == pygame.KEYDOWN:
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
            if not self.current_npc.has_active_quest:
                self.pending_quest_analysis = True

            self._execute_pending_actions()

            self.active = False
            self.waiting_for_llm = False
            self.system_prompt = ""
            self.conversation.clear()
            self.ui.reset()
            self.conversation_ended = False
            self.pending_quest_completion = None

    def _execute_pending_actions(self):
        # Quest completion first (uses conversation context for rewards)
        if self.pending_quest_completion:
            threading.Thread(
                target=self._execute_quest_completion, args=(self.pending_quest_completion,), daemon=True
            ).start()
            self.pending_quest_completion = None

        # Quest analysis second (only for new quests)
        if self.pending_quest_analysis:
            threading.Thread(target=self._execute_quest_analysis, daemon=True).start()
            self.pending_quest_analysis = False

    def draw(self):
        if not self.active:
            return

        self.update()
        self.ui.draw(self.current_npc.name, self.conversation)

    def _send_chat_message(self, message: str):
        if self.conversation_ended:
            return

        self.conversation.add_user_message(message)

        conversation_text = self.conversation.format_for_prompt()
        conversation_text += f"Player: {message}"

        self.generator = generate_response_stream_queued(
            conversation_text + "\nNPC:", self.system_prompt, "Continuing conversation"
        )

    def _execute_quest_analysis(self):
        conversation_text = self.conversation.format_for_prompt()
        if conversation_text:
            quest_info = self.quest_system.analyze_conversation_for_quest(conversation_text)
            print(f"~~~ Generated these quest infos : {quest_info}")
            if quest_info["has_quest"]:
                self.quest_system.create_quest_from_analysis(self.current_npc, quest_info)
                quest = self.current_npc.quest
                if quest:
                    self.notification.show(quest)
                    play_sound("quest_new")

    def _execute_quest_completion(self, npc: NPC):
        last_msg = self.conversation.get_last_message()
        if last_msg and npc.quest:
            reward = self.quest_system.extract_and_give_reward(last_msg["content"])
            npc.quest.reward_coins = reward

        self.quest_system.complete_quest(npc)
        play_sound("quest_complete")
