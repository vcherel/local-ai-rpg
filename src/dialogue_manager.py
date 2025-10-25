import re
import random
import threading
import time
import pygame
from typing import List

import constants as c
from llm_request_queue import generate_response_queued, generate_response_stream_queued
from entities import NPC, Item, Player


class DialogueManager:
    """Manages all dialogue, quest, and NPC interaction logic"""
    
    def __init__(self, world_width: int, world_height: int):
        self.world_width = world_width
        self.world_height = world_height
        
        # Dialogue state
        self.active = False
        self.generator = None
        self.current_npc: NPC = None
        self.waiting_for_llm = False
        self.pending_npc = None
        self.frames_waited = 0
        
        # Chat state - always enabled
        self.user_input = ""
        self.conversation_history = []  # List of {"role": "user"/"assistant", "content": str}
        
        # Scroll state
        self.scroll_offset = 0  # Lines scrolled from bottom (0 = bottom)
        self.max_visible_lines = 7  # Number of message lines visible
        
        # Fonts
        self.font = pygame.font.SysFont("arial", 28, bold=True)
        self.message_font = pygame.font.SysFont("arial", 20)
        self.input_font = pygame.font.SysFont("arial", 24)
        self.small_font = pygame.font.SysFont("arial", 18)
        
        # References
        self.items_list: List[Item] = None
        self.player: Player = None
    
    def interact_with_npc(self, npc: NPC):
        """Start interaction with an NPC"""
        # Check if player has quest item
        if npc.has_active_quest and npc.quest_item_name in self.player.inventory:
            # Complete quest
            self.player.inventory.remove(npc.quest_item_name)
            npc.quest_complete = True
        
        self.current_npc = npc
        self.active = True
        self.scroll_offset = 0
        self.waiting_for_llm = True
        self.pending_npc = npc
        self.frames_waited = 0
        self.user_input = ""
        self.conversation_history = []
    
    def handle_text_input(self, event):
        """Handle text input for chat"""
        if not self.active:
            return
        
        if event.key == pygame.K_RETURN and self.user_input.strip():
            # Send message to NPC
            self._send_chat_message(self.user_input)
            self.user_input = ""
            self.scroll_offset = 0  # Auto-scroll to bottom on new message
        elif event.key == pygame.K_BACKSPACE:
            self.user_input = self.user_input[:-1]
        elif event.unicode and len(self.user_input) < 150:
            self.user_input += event.unicode
    
    def handle_scroll(self, scroll_direction):
        """Handle mouse wheel scrolling (scroll_direction: 1 for up, -1 for down)"""
        if not self.active:
            return
        
        # Calculate total lines in conversation
        total_lines = len(self.conversation_history)
        max_scroll = max(0, total_lines - self.max_visible_lines)
        
        # Update scroll offset
        self.scroll_offset = max(0, min(self.scroll_offset + scroll_direction, max_scroll))
    
    def _send_chat_message(self, message: str):
        """Send a chat message to the NPC and get response"""
        npc = self.current_npc
        
        # Add user message to history
        self.conversation_history.append({"role": "user", "content": message})
        
        # Build system prompt with NPC context
        system_prompt = f"Tu es {npc.name}, un PNJ dans un RPG. "
        
        if npc.has_active_quest and not npc.quest_complete:
            system_prompt += f"Tu as demandé au joueur de récupérer {npc.quest_item_name or 'un objet'}."
            if npc.quest_item_name in self.player.inventory:
                system_prompt += "Le joueur l'a maintenant dans son inventaire. "
            else:
                system_prompt += "Le joueur ne l'a pas encore trouvé. "
        elif npc.quest_complete:
            system_prompt += "Le joueur vient de terminer ta quête. "
        
        system_prompt += "Réponds naturellement en une ou deux phrases courtes."
        
        # Build conversation history in chat format
        conversation_messages = self.conversation_history[-10:]
        
        # Format as a multi-turn conversation for the prompt
        conversation_text = ""
        for msg in conversation_messages[:-1]:  # All except the last (current) message
            if msg['role'] == 'user':
                conversation_text += f"Joueur: {msg['content']}\n"
            else:
                conversation_text += f"PNJ: {msg['content']}\n"
        
        # Add the current user message
        conversation_text += f"Joueur: {message}"
        
        # The prompt is just the conversation
        prompt = conversation_text
        
        self.waiting_for_llm = True
        self.generator = generate_response_stream_queued(prompt, system_prompt)
    
    def _generate_npc_dialogue(self, npc: NPC):
        """Generate initial interaction dialogue with NPC (first message is automatic)"""
        # Choose type of interaction
        interaction_type = random.choices(
            ["quest", "talk"],
            weights=[0.7, 0.3],
            k=1
        )[0]

        if interaction_type == "quest" and not npc.has_active_quest:
            # Generate new quest
            system_prompt = "Tu es un PNJ dans un RPG. Tu demandes de l'aide au joueur en une seule phrase."
            prompt = "Demande au joueur de récupérer un objet. Indique l'objet, où il se trouve, et pourquoi tu en as besoin."
            self.generator = generate_response_stream_queued(prompt, system_prompt)

            # Create quest
            npc.has_active_quest = True

            # Schedule quest item generation to run after dialogue completes
            self._schedule_quest_item_generation(npc)

        elif npc.has_active_quest:
            if npc.quest_complete:
                # Quest completion dialogue
                system_prompt = "Tu es un PNJ dans un RPG. Le joueur vient de terminer ta quête."
                prompt = (
                    f"Le joueur t'a apporté {npc.quest_item_name} ({npc.quest_content}). "
                    f"Remercie-le en une phrase et mentionne sa récompense en pièces."
                )
                self.generator = generate_response_stream_queued(prompt, system_prompt)

                # Schedule reward extraction
                self._schedule_reward_extraction()

                # Reset quest status
                npc.has_active_quest = False
                npc.quest_complete = False
                npc.quest_item_name = None
            else:
                # Talk about active quest
                system_prompt = "Tu es un PNJ dans un RPG. Le joueur est en train de faire ta quête."
                prompt = (
                    f"Tu as demandé au joueur de récupérer {npc.quest_item_name}. "
                    f"Contexte de la quête : {npc.quest_content}. "
                    f"Le joueur n'a pas encore terminé. Relance-le en une seule phrase naturelle."
                )
                self.generator = generate_response_stream_queued(prompt, system_prompt)

        else:
            # Casual conversation
            system_prompt = "Tu es un PNJ dans un RPG. Tu discutes brièvement avec le joueur."
            prompt = "Dis une courte réplique au joueur pour le saluer."
            self.generator = generate_response_stream_queued(prompt, system_prompt)

    def _schedule_quest_item_generation(self, npc: NPC):
        """Schedule quest item generation after dialogue completes"""
        def check_and_generate():
            # Wait for dialogue to finish
            while self.generator is not None:
                time.sleep(0.1)
            
            # Extract quest item
            npc.quest_content = self.conversation_history[-1]["content"]
            system_prompt = "Tu es un assistant d'extraction. Réponds seulement avec l'information demandée, sans article ('le', 'la', 'un', 'une', etc.) et sans guillemets."
            prompt = f"Quel est l'objet à récupérer dans '{npc.quest_content}' ?"
            
            # Use the queued version and get the response
            item_name = generate_response_queued(prompt, system_prompt)
            
            # Process the extracted item name
            item_name = item_name.strip().rstrip('.')
            npc.quest_item_name = item_name
            
            # Spawn the item
            item_x = random.randint(100, self.world_width - 100)
            item_y = random.randint(100, self.world_height - 100)
            self.items_list.append(Item(item_x, item_y, item_name))
        
        # Start the waiting thread
        threading.Thread(target=check_and_generate, daemon=True).start()

    def _schedule_reward_extraction(self):
        """Schedule coin reward extraction after dialogue completes"""
        def check_and_extract():
            # Wait for dialogue to finish
            while self.generator is not None:
                time.sleep(0.1)
            
            # Get the last assistant message
            last_message = self.conversation_history[-1]["content"]
            
            # First try to extract coin number directly
            match = re.search(r'\b(\d+)\b', last_message)
            if match:
                reward = int(match.group(1))
                self.player.coins += reward
                return
            
            # If no explicit number, use LLM
            system_prompt = "Tu es un assistant d'extraction. Réponds seulement avec un nombre."
            prompt = f"Combien de pièces dans ce texte : '{last_message}' ?"
            
            # Get the response using the queued function
            reward_str = generate_response_queued(prompt, system_prompt)
            
            # Process the extracted reward
            reward_str = re.sub(r'[^\d]', '', reward_str)
            if reward_str:
                reward = int(reward_str)
                if reward > 0:
                    self.player.coins += reward
        
        # Start the waiting thread
        threading.Thread(target=check_and_extract, daemon=True).start()
    
    def update(self):
        """Update dialogue text if generator is active"""        
        if self.pending_npc is not None:
            self.frames_waited += 1
            if self.frames_waited >= 2:
                self._generate_npc_dialogue(self.pending_npc)
                self.pending_npc = None
                self.frames_waited = 0
            return
        
        if self.active and self.generator is not None:
            try:
                partial = next(self.generator)
                # Update the last message in history if it's from assistant
                if self.conversation_history and self.conversation_history[-1]["role"] == "assistant":
                    self.conversation_history[-1]["content"] = partial
                else:
                    # Add new assistant message
                    self.conversation_history.append({"role": "assistant", "content": partial})
                self.waiting_for_llm = False
            except StopIteration:
                self.generator = None
    
    def close(self):
        """Close the dialogue window"""
        if self.active and self.generator is None:
            self.active = False
            self.current_npc = None
            self.waiting_for_llm = False
            self.pending_npc = None
            self.frames_waited = 0
            self.user_input = ""
            self.conversation_history = []
            self.scroll_offset = 0

    def draw(self, screen: pygame.Surface):
        """Draw dialogue box with scrollable conversation history"""
        if not self.active:
            return
        
        box_height = 300
        box_y = c.Screen.HEIGHT - box_height - 25
        pygame.draw.rect(screen, c.Colors.DARK_GRAY, 
                       (10, box_y, c.Screen.WIDTH - 20, box_height))
        pygame.draw.rect(screen, c.Colors.WHITE, 
                       (10, box_y, c.Screen.WIDTH - 20, box_height), 2)
        
        # Draw NPC name
        name_surface = self.font.render(self.current_npc.name, True, c.Colors.YELLOW)
        screen.blit(name_surface, (25, box_y + 10))
        
        # Draw conversation history (scrollable)
        message_area_y = box_y + 45
        message_area_height = 180
        line_height = 26
        
        # Calculate which messages to display based on scroll
        total_messages = len(self.conversation_history)
        start_index = max(0, total_messages - self.max_visible_lines - self.scroll_offset)
        end_index = total_messages - self.scroll_offset
        
        visible_messages = self.conversation_history[start_index:end_index]
        
        # Draw messages
        y_offset = message_area_y
        for msg in visible_messages:
            if msg["role"] == "user":
                prefix = "Vous : "
                color = c.Colors.CYAN
            else:
                prefix = f"{self.current_npc.name} : "
                color = c.Colors.WHITE
            
            # Word wrap the message
            full_text = prefix + msg["content"]
            words = full_text.split()
            lines = []
            current_line = []
            
            for word in words:
                test_line = ' '.join(current_line + [word])
                if self.message_font.size(test_line)[0] < c.Screen.WIDTH - 60:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
            if current_line:
                lines.append(' '.join(current_line))
            
            # Draw each line
            for line in lines:
                if y_offset < message_area_y + message_area_height:
                    text_surface = self.message_font.render(line, True, color)
                    screen.blit(text_surface, (25, y_offset))
                    y_offset += line_height
        
        # Draw scroll indicator if needed
        if self.scroll_offset > 0:
            scroll_text = f"↑ {self.scroll_offset} messages au-dessus"
            scroll_surface = self.small_font.render(scroll_text, True, c.Colors.YELLOW)
            screen.blit(scroll_surface, (c.Screen.WIDTH - 250, message_area_y))
        
        # Draw chat input box
        input_y = box_y + box_height - 60
        pygame.draw.rect(screen, c.Colors.BLACK,
                       (20, input_y, c.Screen.WIDTH - 40, 35))
        pygame.draw.rect(screen, c.Colors.WHITE,
                       (20, input_y, c.Screen.WIDTH - 40, 35), 2)
        
        # Draw user input with cursor
        input_text = self.user_input + "|"
        input_surface = self.input_font.render(input_text, True, c.Colors.WHITE)
        screen.blit(input_surface, (30, input_y + 5))
        
        # Draw instructions
        instruction = self.small_font.render("ENTRÉE: Envoyer | Molette: Défiler | ESPACE: Fermer", True, c.Colors.CYAN)
        screen.blit(instruction, (25, box_y + box_height - 25))