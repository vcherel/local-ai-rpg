import json
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
    
    def analyze_conversation_for_quest(self, conversation_history: str) -> dict:
        """
        Analyze conversation to detect if a quest was given.
        Returns dict with: {has_quest: bool, quest_description: str, item_name: str}
        """
        system_prompt = (
            "Tu es un analyseur de conversation pour un jeu RPG. "
            "Analyse la conversation et détermine si le PNJ a donné une quête au joueur. "
            "Une quête implique que le PNJ demande au joueur de récupérer, trouver, ou apporter un objet spécifique. "
            "Réponds UNIQUEMENT avec un JSON valide, sans texte supplémentaire."
        )
        
        prompt = (
            f"Conversation:\n{conversation_history}\n\n"
            f"Réponds avec ce format JSON exact:\n"
            f'{{"has_quest": true/false, "quest_description": "description brève", "item_name": "nom de l\'objet"}}\n'
            f"Si pas de quête, utilise: {{'has_quest': false, 'quest_description': '', 'item_name': ''}}"
        )
        
        response = generate_response_queued(prompt, system_prompt, "Conversation analyze")
        
        # Parse JSON response
        try:
            response = response.strip()
            # Convert true/false to lowercase JSON
            json_str = response.replace("True", "true").replace("False", "false")
            # Wrap keys in double quotes
            response = re.sub(r'(\b\w+\b)\s*:', r'"\1":', response)
            # Wrap unquoted string values in double quotes
            response = re.sub(r':\s*([^",\d][^,\n}]*)', r': "\1"', response)

            # Extract the first {...} block
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if match:
                json_str = match.group(0)
                result = json.loads(json_str)
                return {
                    'has_quest': result.get('has_quest', False),
                    'quest_description': result.get('quest_description', ''),
                    'item_name': result.get('item_name', '')
                }
        except Exception as e:
            print(f"Failed to parse quest analysis: {e}, response: {response}")
        
        # Fallback: no quest detected
        return {'has_quest': False, 'quest_description': '', 'item_name': ''}
    
    def create_quest_from_analysis(self, npc: NPC, quest_info: dict):
        """Create and register a quest item based on analysis"""
        if not quest_info['has_quest'] or not quest_info['item_name']:
            return
        
        from entities import Item
        
        # Clean item name
        item_name = quest_info['item_name'].strip()
        # Remove articles
        for article in ['le ', 'la ', "l'", 'un ', 'une ', 'des ']:
            if item_name.lower().startswith(article):
                item_name = item_name[len(article):]
                break
        
        # Create quest item
        npc.quest_item = Item(*random_coordinates(), item_name)
        npc.quest_content = quest_info['quest_description']
        npc.has_active_quest = True
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
        
        reward_str = generate_response_queued(prompt, system_prompt, "Extract reward")
        print(f"~~~ Extracted reward : {reward_str} ~~~")
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
    def __init__(self, items, player):
        # Core state
        self.active = False
        self.current_npc = None
        self.waiting_for_llm = False
        self.system_prompt = ""  # Store system prompt for entire conversation
        
        # Response streaming
        self.generator = None
        
        # Pending actions
        self.pending_quest_analysis = False
        self.pending_reward_extraction = False
        
        # Components
        self.conversation = ConversationHistory()
        self.ui = ConversationUI()
        self.quest_system = QuestSystem(items, player)
    
    def _build_system_prompt(self, npc: NPC, context: str) -> str:
        """Build the system prompt for the entire conversation"""
        system_prompt = f"Tu es {npc.name}, un PNJ dans un RPG avec ce contexte : {context}. "
        
        if npc.has_active_quest:
            if npc.quest_complete:
                # Quest just completed
                system_prompt += (
                    f"Le joueur vient de te rapporter {npc.quest_item.name} que tu avais demandé ({npc.quest_content}). "
                    f"Remercie-le et mentionne sa récompense en pièces. "
                )
            elif npc.quest_item:
                # Active quest in progress
                system_prompt += (
                    f"Tu as demandé au joueur de récupérer {npc.quest_item.name}. "
                )
                if npc.quest_item in self.quest_system.player.inventory:
                    system_prompt += "Le joueur l'a maintenant dans son inventaire. "
                else:
                    system_prompt += "Le joueur ne l'a pas encore trouvé. "
        else:
            # New interaction - NPC can decide naturally
            system_prompt += (
                "Tu peux avoir des besoins, des problèmes, ou des requêtes. "
                "Si le joueur te le demande, ou si cela émerge naturellement de la conversation, "
                "tu peux lui demander de récupérer un objet spécifique pour t'aider. "
                "Tu peux aussi n'avoir aucune quête à donner. "
            )
        
        system_prompt += "Réponds naturellement en une ou deux phrases courtes."
        return system_prompt
    
    def interact_with_npc(self, npc: NPC, npc_name_generator, context: str):
        """Start interaction with an NPC"""
        npc.assign_name(npc_name_generator)
        
        # Check if player has quest item
        if npc.has_active_quest and npc.quest_item in self.quest_system.player.inventory:
            self.quest_system.player.inventory.remove(npc.quest_item)
            npc.quest_complete = True
        
        # Build system prompt once for entire conversation
        self.system_prompt = self._build_system_prompt(npc, context)
        
        # Initialize dialogue
        self.current_npc = npc
        self.active = True
        self.waiting_for_llm = True
        
        # Reset state
        self.conversation.clear()
        self.ui.reset()
        self.pending_quest_analysis = False
        self.pending_reward_extraction = False
        
        # Check if we need to extract reward after this conversation
        if npc.quest_complete:
            self.pending_reward_extraction = True
            self.quest_system.complete_quest(npc)
        
        # Start conversation with initial greeting
        initial_prompt = "Le joueur s'approche de toi. Salue-le."
        self.generator = generate_response_stream_queued(initial_prompt, self.system_prompt, "First message")

    def handle_event(self, event):
        if not self.active:
            return False

        elif event.type == pygame.KEYDOWN:
            # Handle scrolling with arrow keys
            if event.key == pygame.K_UP:
                self.handle_scroll(1)  # Scroll up
            elif event.key == pygame.K_DOWN:
                self.handle_scroll(-1)  # Scroll down
            else:
                self.handle_text_input(event)
                
            if event.key == pygame.K_ESCAPE:
                self.close()

        return True
    
    def handle_text_input(self, event):
        """Handle text input for chat"""
        if not self.active:
            return
        
        message = self.ui.handle_text_input(event)
        if message:
            self._send_chat_message(message)
            self.ui.auto_scroll(self.conversation, self.current_npc.name)
    
    def handle_scroll(self, direction: int):
        """Handle scroll input"""
        if not self.active:
            return
        self.ui.handle_scroll(direction, self.conversation, self.current_npc.name)
    
    def update(self):
        """Update dialogue state and process streaming responses"""
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
            # Analyze conversation for quest if NPC doesn't have active quest
            if not self.current_npc.has_active_quest and not self.current_npc.quest_complete:
                self.pending_quest_analysis = True
            
            # Execute pending actions
            if self.pending_quest_analysis:
                threading.Thread(
                    target=self._execute_quest_analysis,
                    daemon=True
                ).start()
                self.pending_quest_analysis = False
            
            if self.pending_reward_extraction:
                threading.Thread(
                    target=self._execute_reward_extraction,
                    daemon=True
                ).start()
                self.pending_reward_extraction = False
            
            # Reset state
            self.active = False
            self.waiting_for_llm = False
            self.system_prompt = ""
            self.conversation.clear()
            self.ui.reset()
    
    def draw(self, screen: pygame.Surface):
        """Draw the dialogue UI"""
        if not self.active:
            return
        self.ui.draw(screen, self.current_npc.name, self.conversation)
    
    def _send_chat_message(self, message: str):
        """Send a chat message to the NPC"""
        self.conversation.add_user_message(message)
        
        # Format conversation for prompt
        conversation_text = self.conversation.format_for_prompt()
        conversation_text += f"Joueur: {message}"
        
        # Start streaming response using the same system prompt
        self.generator = generate_response_stream_queued(conversation_text, self.system_prompt, "Continuing conversation")
    
    def _execute_quest_analysis(self):
        """Analyze conversation for quest in background thread"""
        conversation_text = self.conversation.format_for_prompt()
        if conversation_text:
            quest_info = self.quest_system.analyze_conversation_for_quest(conversation_text)
            print(f"~~~ Generated these quest infos : {quest_info}")
            if quest_info['has_quest']:
                self.quest_system.create_quest_from_analysis(self.current_npc, quest_info)
    
    def _execute_reward_extraction(self):
        """Execute reward extraction in background thread"""
        last_msg = self.conversation.get_last_message()
        if last_msg:
            self.quest_system.extract_and_give_reward(last_msg["content"])
