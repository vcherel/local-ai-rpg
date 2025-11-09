from __future__ import annotations

import threading
import pygame
from typing import TYPE_CHECKING

from core.utils import ConversationHistory
from llm.llm_request_queue import generate_response_stream_queued
from llm.quest_system import QuestSystem
from ui.conversation_ui import ConversationUI

if TYPE_CHECKING:
    from game.entities.npcs import NPC
    from game.world import World
    from llm.name_generator import NPCNameGenerator


class DialogueManager:
    """Manage the Dialogue window in its entirety"""
    def __init__(self, screen, items, player):
        # Core state
        self.active = False
        self.current_npc = None
        self.waiting_for_llm = False
        self.system_prompt = ""
        self.conversation_ended = False
        
        # Response streaming
        self.generator = None
        
        # Pending actions
        self.pending_quest_analysis = False
        self.pending_quest_completion = None  # Store NPC reference for completion
        
        # Components
        self.conversation = ConversationHistory()
        self.ui = ConversationUI(screen)
        self.quest_system = QuestSystem(items, player)
    
    def _build_system_prompt(self, npc: NPC, context: str, quest_complete: bool) -> str:
        """Build the system prompt for the entire conversation"""
        system_prompt = (
            f"Tu es {npc.name}, un PNJ dans un RPG avec ce contexte : {context}. "
            f"Le joueur vient te parler."
            )
        
        if npc.has_active_quest:
            quest = npc.quest
            if quest_complete:
                system_prompt += (
                    f"Le joueur vient de te rapporter {quest.item_name} que tu avais demandé ({quest.description}). "
                    f"Remercie-le et mentionne sa récompense en pièces. "
                )
            elif quest.item:
                system_prompt += (
                    f"Tu as demandé au joueur de récupérer {quest.item_name}. "
                )
                if quest.item in self.quest_system.player.inventory:
                    system_prompt += "Le joueur l'a maintenant dans son inventaire. "
                else:
                    system_prompt += "Le joueur ne l'a pas encore trouvé. "
        else:
            system_prompt += (
                "Tu peux avoir des besoins ou des problèmes. Le joueur peux t'aider en allant récuper un objet spécifique. "
                "Tu ne peux pas participer toi même à ces quêtes (invente une excuse si besoin, le joueur ne dois pas le savoir) ! " 
                "Tu peux aussi simplement vouloir discuter. "
            )
        
        system_prompt += (
            "Réponds naturellement aux messages en restant bien dans le contexte de la conversation en une phrase courte."
        )

        return system_prompt
    
    def interact_with_npc(self, npc: NPC, npc_name_generator: NPCNameGenerator, world: World):
        """Start interaction with an NPC"""
        npc.assign_name(npc_name_generator)
        
        # Check if player has quest item
        quest_complete = False
        if npc.has_active_quest and npc.quest.item in self.quest_system.player.inventory:
            quest_complete = True
            self.pending_quest_completion = npc
        
        # Build system prompt once for entire conversation
        self.system_prompt = self._build_system_prompt(npc, world.context, quest_complete)
        
        # Initialize dialogue
        self.current_npc = npc
        self.active = True
        self.waiting_for_llm = True
        self.conversation_ended = False
        
        # Reset state
        self.conversation.clear()
        self.ui.reset()
        self.pending_quest_analysis = False
        
        # Start conversation with initial greeting
        initial_prompt = "Joueur: Salut !"
        self.generator = generate_response_stream_queued(initial_prompt, self.system_prompt, "First message")

    def handle_event(self, event, npc_name_generator: NPCNameGenerator):
        if not self.active:
            return False

        elif event.type == pygame.KEYDOWN:
            # Handle scrolling with arrow keys
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
        """Handle text input for chat"""
        if not self.active or self.conversation_ended:
            return
        
        message = self.ui.handle_text_input(event)
        if message:
            self._send_chat_message(message)
            self.ui.auto_scroll(self.conversation, self.current_npc.name)
    
    def handle_scroll(self, direction: int):
        """Handle scroll input"""
        if not self.active:
            return
        self.ui.handle_key_scroll(direction, self.conversation, self.current_npc.name)
    
    def _check_for_end_signal(self, text: str) -> bool:
        """Check if the NPC wants to end the conversation"""
        return '[FIN]' in text
    
    def update(self):
        """Update dialogue state and process streaming responses"""
        if self.active and self.generator is not None:
            try:
                partial = next(self.generator)
                self.conversation.update_last_assistant_message(partial)
                self.ui.auto_scroll(self.conversation, self.current_npc.name)
                self.waiting_for_llm = False
            except StopIteration:
                self.generator = None
                
                last_msg = self.conversation.get_last_message()

                # Clean up message formatting
                if ":" in last_msg["content"]:
                    cleaned_content = last_msg["content"].split(":", 1)[-1].strip()
                    if len(cleaned_content) <= 25:
                        self.conversation.update_last_assistant_message(cleaned_content)
                
                if "[FIN]" in last_msg["content"]:
                    cleaned_content = last_msg["content"].replace("[FIN]", "").strip()
                    self.conversation.update_last_assistant_message(cleaned_content)

                if last_msg and self._check_for_end_signal(last_msg["content"]):
                    # Clean the message and add end marker
                    cleaned_content = last_msg["content"].replace('[FIN]', '').strip()
                    self.conversation.update_last_assistant_message(cleaned_content)
                    
                    # Add the "[Conversation Ended]" message
                    self.conversation.add_system_message("[Conversation Ended]")
                    self.conversation_ended = True
                    self.ui.auto_scroll(self.conversation, self.current_npc.name)
                    
                    # Execute pending actions when conversation ends naturally
                    self._execute_pending_actions()
    
    def close(self):
        """Close dialogue"""
        if self.active and self.generator is None:
            if not self.current_npc.has_active_quest:
                self.pending_quest_analysis = True
            
            # Execute all pending actions
            self._execute_pending_actions()
            
            # Reset state
            self.active = False
            self.waiting_for_llm = False
            self.system_prompt = ""
            self.conversation.clear()
            self.ui.reset()
            self.conversation_ended = False
            self.pending_quest_completion = None
    
    def _execute_pending_actions(self):
        """Execute pending quest completion and analysis"""
        # Quest completion first (uses conversation context for rewards)
        if self.pending_quest_completion:
            threading.Thread(
                target=self._execute_quest_completion,
                args=(self.pending_quest_completion,),
                daemon=True
            ).start()
            self.pending_quest_completion = None
        
        # Quest analysis second (only for new quests)
        if self.pending_quest_analysis:
            threading.Thread(
                target=self._execute_quest_analysis,
                daemon=True
            ).start()
            self.pending_quest_analysis = False
    
    def draw(self):
        """Draw the dialogue UI"""
        self.update()

        if not self.active:
            return
        self.ui.draw(self.current_npc.name, self.conversation)
    
    def _send_chat_message(self, message: str):
        """Send a chat message to the NPC"""
        if self.conversation_ended:
            return
        
        self.conversation.add_user_message(message)
        
        conversation_text = self.conversation.format_for_prompt()
        conversation_text += f"Joueur: {message}"
        
        self.generator = generate_response_stream_queued(conversation_text, self.system_prompt, "Continuing conversation")
    
    def _execute_quest_analysis(self):
        """Analyze conversation for quest in background thread"""
        conversation_text = self.conversation.format_for_prompt()
        if conversation_text:
            quest_info = self.quest_system.analyze_conversation_for_quest(conversation_text)
            print(f"~~~ Generated these quest infos : {quest_info}")
            if quest_info['has_quest']:
                self.quest_system.create_quest_from_analysis(self.current_npc, quest_info)
    
    def _execute_quest_completion(self, npc: NPC):
        """Complete quest: extract reward and clean up"""
        last_msg = self.conversation.get_last_message()
        if last_msg and npc.quest:
            # Extract and give reward based on NPC's completion message
            reward = self.quest_system.extract_and_give_reward(last_msg["content"])
            npc.quest.reward_coins = reward
        
        # Now complete the quest (removes items, marks as completed)
        self.quest_system.complete_quest(npc)
