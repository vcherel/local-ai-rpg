import re
import random
import threading
import pygame
from typing import List

import core.constants as c
from ui.conversation_ui import ConversationUI
from entities import NPC, Player
from llm.llm_request_queue import generate_response_queued, generate_response_stream_queued
from core.utils import ConversationHistory, random_coordinates

import pygame
import random
import threading
import re
from typing import List
from llm.llm_request_queue import generate_response_stream_queued, generate_response_queued
from core.utils import random_coordinates
import core.constants as c

class QuestSystem:
    """Manages quest generation, completion, and rewards"""
    
    def __init__(self, items: List, player):
        self.items = items
        self.player: Player = player
    
    def generate_quest_dialogue(self, npc: NPC, context: str):
        """Generate quest request dialogue"""
        system_prompt = (
            f"Tu es {npc.name}, un PNJ dans un RPG avec ce contexte : {context}"
            f"Tu demandes de l'aide au joueur en une seule phrase."
        )
        prompt = "Demande au joueur de récupérer un objet en prenant en compte le context. Indique l'objet, où il se trouve, et pourquoi tu en as besoin."
        
        npc.has_active_quest = True
        return generate_response_stream_queued(prompt, system_prompt)
    
    def generate_active_quest_dialogue(self, npc: NPC, context: str):
        """Generate dialogue for active quest reminder"""
        system_prompt = (
            f"Tu es {npc.name}, un PNJ dans un RPG avec ce contexte : {context}."
            f"Le joueur est en train d'accomplir ta quête, mais ne l'a pas encore terminée."
        )
        prompt = (
            f"Rappelle au joueur sa mission : {npc.quest_content}. "
            f"Encourage-le brièvement."
        )
        return generate_response_stream_queued(prompt, system_prompt)
    
    def generate_completion_dialogue(self, npc: NPC, context: str):
        """Generate quest completion dialogue"""
        system_prompt = (
            f"Tu es {npc.name}, un PNJ dans un RPG avec ce contexte : {context}."
            f"Le joueur vient de terminer ta quête."
        )
        prompt = (
            f"Le joueur t'a apporté {npc.quest_item.name} ({npc.quest_content}). "
            f"Remercie-le en une phrase et mentionne sa récompense en pièces."
        )
        return generate_response_stream_queued(prompt, system_prompt)
    
    def extract_quest_item(self, npc: NPC, quest_content: str):
        """Extract and create quest item from dialogue"""
        system_prompt = "Tu es un assistant d'extraction. Réponds seulement avec l'information demandée, sans article ('le', 'la', 'l\', 'un', 'une', etc.) et sans guillemets."
        prompt = f"Quel est l'objet à récupérer dans '{quest_content}' ?"
        
        item_name = generate_response_queued(prompt, system_prompt)
        item_name = item_name.strip().rstrip('.')
        
        # Create and register the quest item
        from entities import Item  # Import here to avoid circular dependency
        npc.quest_item = Item(*random_coordinates(), item_name)
        npc.quest_content = quest_content
        self.items.append(npc.quest_item)
    
    def extract_and_give_reward(self, last_message: str):
        """Extract coin reward from completion message and give to player"""
        # First try direct number extraction
        match = re.search(r'\b(\d+)\b', last_message)
        if match:
            reward = int(match.group(1))
            self.player.add_coins(reward)
            return
        
        # Fall back to LLM extraction
        system_prompt = "Tu es un assistant d'extraction. Réponds seulement avec un nombre."
        prompt = f"Combien de pièces dans ce texte : '{last_message}' ?"
        
        reward_str = generate_response_queued(prompt, system_prompt)
        reward_str = re.sub(r'[^\d]', '', reward_str)
        
        if reward_str:
            reward = int(reward_str)
            if reward > 0:
                self.player.add_coins(reward)
    
    def complete_quest(self, npc: NPC):
        """Mark quest as complete and reset NPC quest state"""
        npc.has_active_quest = False
        npc.quest_complete = False
        npc.quest_item = None

class DialogueManager:
    """Orchestrates NPC interactions, dialogue flow, and quest management"""
    
    def __init__(self, items, player):
        # Core state
        self.active = False
        self.current_npc = None
        self.waiting_for_llm = False
        
        # Delayed initialization state
        self.pending_npc = None
        self.frames_waited = 0
        
        # Response streaming
        self.generator = None
        
        # Pending actions
        self.pending_quest_item_gen = False
        self.pending_reward_extraction = False
        
        # Components
        self.conversation = ConversationHistory()
        self.ui = ConversationUI()
        self.quest_system = QuestSystem(items, player)
    
    def interact_with_npc(self, npc: NPC, npc_name_generator):
        """Start interaction with an NPC"""
        npc.assign_name(npc_name_generator)
        
        # Check if player has quest item
        if npc.has_active_quest and npc.quest_item in self.quest_system.player.inventory:
            self.quest_system.player.inventory.remove(npc.quest_item)
            npc.quest_complete = True
        
        # Initialize dialogue
        self.current_npc = npc
        self.active = True
        self.waiting_for_llm = True
        self.pending_npc = npc
        self.frames_waited = 0
        
        # Reset state
        self.conversation.clear()
        self.ui.reset()
        self.pending_quest_item_gen = False
        self.pending_reward_extraction = False
    
    def handle_text_input(self, event, context: str):
        """Handle text input for chat"""
        if not self.active:
            return
        
        message = self.ui.handle_text_input(event)
        if message:
            self._send_chat_message(message, context)
            self.ui.auto_scroll(self.conversation, self.current_npc.name)
    
    def handle_scroll(self, direction: int):
        """Handle scroll input"""
        if not self.active:
            return
        self.ui.handle_scroll(direction, self.conversation, self.current_npc.name)
    
    def update(self, context: str):
        """Update dialogue state and process streaming responses"""
        # Handle delayed NPC dialogue generation
        if self.pending_npc is not None:
            self.frames_waited += 1
            if self.frames_waited >= 2:
                self._generate_npc_dialogue(self.pending_npc, context)
                self.pending_npc = None
                self.frames_waited = 0
            return
        
        # Process streaming response
        if self.active and self.generator is not None:
            try:
                partial = next(self.generator)
                self.conversation.update_last_assistant_message(partial)
                self.ui.auto_scroll(self.conversation, self.current_npc.name)
                self.waiting_for_llm = False
            except StopIteration:
                self.generator = None
    
    def close(self):
        """Close dialogue and execute pending actions"""
        if self.active and self.generator is None:
            # Execute pending actions
            if self.pending_quest_item_gen:
                threading.Thread(
                    target=self._execute_quest_item_extraction,
                    daemon=True
                ).start()
                self.pending_quest_item_gen = False
            
            if self.pending_reward_extraction:
                threading.Thread(
                    target=self._execute_reward_extraction,
                    daemon=True
                ).start()
                self.pending_reward_extraction = False
            
            # Reset state
            self.active = False
            self.current_npc = None
            self.waiting_for_llm = False
            self.pending_npc = None
            self.frames_waited = 0
            self.conversation.clear()
            self.ui.reset()
    
    def draw(self, screen: pygame.Surface):
        """Draw the dialogue UI"""
        if not self.active:
            return
        self.ui.draw(screen, self.current_npc.name, self.conversation)
    
    def _send_chat_message(self, message: str, context: str):
        """Send a chat message to the NPC"""
        npc = self.current_npc
        self.conversation.add_user_message(message)
        
        # Build system prompt
        system_prompt = f"Tu es {npc.name}, un PNJ dans un RPG avec ce contexte : {context}"
        
        if npc.has_active_quest:
            if not npc.quest_complete and npc.quest_item:
                system_prompt += f"Tu as demandé au joueur de récupérer {npc.quest_item.name or 'un objet'}."
                if npc.quest_item in self.quest_system.player.inventory:
                    system_prompt += "Le joueur l'a maintenant dans son inventaire. "
                else:
                    system_prompt += "Le joueur ne l'a pas encore trouvé. "
            elif npc.quest_complete:
                system_prompt += "Le joueur vient de terminer ta quête. "
        
        system_prompt += "Réponds naturellement en une ou deux phrases courtes."
        
        # Format conversation for prompt
        conversation_text = self.conversation.format_for_prompt()
        conversation_text += f"Joueur: {message}"
        
        # Start streaming response
        self.generator = generate_response_stream_queued(conversation_text, system_prompt)
    
    def _generate_npc_dialogue(self, npc, context: str):
        """Generate initial NPC dialogue based on quest state"""
        # Determine interaction type
        if npc.has_active_quest:
            if npc.quest_complete:
                # Quest completion
                self.generator = self.quest_system.generate_completion_dialogue(npc, context)
                self.pending_reward_extraction = True
                self.quest_system.complete_quest(npc)
            else:
                # Active quest reminder
                self.generator = self.quest_system.generate_active_quest_dialogue(npc, context)
        else:
            # New interaction
            interaction_type = random.choices(["quest", "talk"], weights=[0.8, 0.2], k=1)[0]
            
            if interaction_type == "quest":
                self.generator = self.quest_system.generate_quest_dialogue(npc, context)
                self.pending_quest_item_gen = True
            else:
                # Casual conversation
                system_prompt = f"Tu es {npc.name}, un PNJ dans un RPG. Tu discutes brièvement avec le joueur."
                prompt = "Dis une courte réplique au joueur pour le saluer."
                self.generator = generate_response_stream_queued(prompt, system_prompt)
    
    def _execute_quest_item_extraction(self):
        """Execute quest item extraction in background thread"""
        last_msg = self.conversation.get_last_message()
        if last_msg:
            self.quest_system.extract_quest_item(self.current_npc, last_msg["content"])
    
    def _execute_reward_extraction(self):
        """Execute reward extraction in background thread"""
        last_msg = self.conversation.get_last_message()
        if last_msg:
            self.quest_system.extract_and_give_reward(last_msg["content"])
