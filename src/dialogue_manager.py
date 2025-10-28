import re
import random
import threading
import pygame
from typing import List

import constants as c
from llm_request_queue import generate_response_queued, generate_response_stream_queued
from entities import NPC, Item, Player
from utils import random_coordinates

class DialogueManager:
    """Manages all dialogue, quest, and NPC interaction logic"""
    
    def __init__(self):        
        # Dialogue state
        self.active = False
        self.generator = None
        self.current_npc: NPC = None
        self.waiting_for_llm = False
        self.pending_npc = None
        self.frames_waited = 0
        
        # Chat state
        self.user_input = ""
        self.conversation_history = []  # List of {"role": "user"/"assistant", "content": str}
        
        # Scroll state
        self.scroll_offset = 0  # Pixels scrolled from bottom
        self.max_visible_height = 170  # Height of scrollable area in pixels
        self.line_height = 26
        
        # Pending actions to execute on close
        self.pending_quest_item_gen = False
        self.pending_reward_extraction = False
        
        # Fonts
        self.font = pygame.font.SysFont("arial", 28, bold=True)
        self.message_font = pygame.font.SysFont("arial", 20)
        self.input_font = pygame.font.SysFont("arial", 24)
        self.small_font = pygame.font.SysFont("arial", 18)
        
        # References
        self.items_list: List[Item] = None
        self.player: Player = None
    
    def interact_with_npc(self, npc: NPC, npc_name_generator):
        # Assign name if not already done
        npc.assign_name(npc_name_generator)

        # Check if player has quest item
        if npc.has_active_quest and npc.quest_item in self.player.inventory:
            # Complete quest
            self.player.inventory.remove(npc.quest_item)
            npc.quest_complete = True
        
        self.current_npc = npc
        self.active = True
        self.scroll_offset = 0
        self.waiting_for_llm = True
        self.pending_npc = npc
        self.frames_waited = 0
        self.user_input = ""
        self.conversation_history = []
        self.pending_quest_item_gen = False
        self.pending_reward_extraction = False
    
    def handle_text_input(self, event, context):
        """Handle text input for chat"""
        if not self.active:
            return
        
        if event.key == pygame.K_RETURN and self.user_input.strip():
            # Send message to NPC
            self._send_chat_message(self.user_input, context)
            self.user_input = ""
            self.auto_scroll()
        elif event.key == pygame.K_BACKSPACE:
            self.user_input = self.user_input[:-1]
        elif event.unicode and len(self.user_input) < 150:
            self.user_input += event.unicode
    
    def handle_scroll(self, direction):
        """Handle arrow key scrolling (direction: 1 for up, -1 for down)"""
        if not self.active:
            return
        
        # Scroll by line_height pixels
        scroll_amount = -self.line_height * direction
        
        # Calculate total content height
        total_height = self._calculate_total_content_height()
        max_scroll = max(0, total_height - self.max_visible_height)
        
        # Update scroll offset
        self.scroll_offset = max(0, min(self.scroll_offset + scroll_amount, max_scroll))

    def _calculate_total_content_height(self):
        """Calculate total height of all messages"""
        total_height = 0
        for msg in self.conversation_history:
            # Calculate wrapped lines for this message
            if msg["role"] == "user":
                prefix = "Vous : "
            else:
                prefix = f"{self.current_npc.name} : "
            
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
            
            total_height += len(lines) * self.line_height
        
        return total_height

    def _send_chat_message(self, message: str, context: str):
        """Send a chat message to the NPC and get response"""
        npc = self.current_npc
        
        # Add user message to history
        self.conversation_history.append({"role": "user", "content": message})
        
        # Build system prompt with NPC context
        system_prompt = f"Tu es {npc.name}, un PNJ dans un RPG avec ce contexte : {context}"
        
        if npc.has_active_quest: 
            if not npc.quest_complete and npc.quest_item:  # If quest is active AND item generated
                system_prompt += f"Tu as demandé au joueur de récupérer {npc.quest_item.name or 'un objet'}."
                if npc.quest_item in self.player.inventory:
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
        
        # Start the generator - user message is already in history and will display
        self.generator = generate_response_stream_queued(prompt, system_prompt)
    
    def _generate_npc_dialogue(self, npc: NPC, context: str):
        """Generate initial interaction dialogue with NPC"""
        # Choose type of interaction
        interaction_type = random.choices(
            ["quest", "talk"],
            weights=[0.8, 0.2],
            k=1
        )[0]

        if interaction_type == "quest" and not npc.has_active_quest:
            # Generate new quest
            system_prompt = (
                f"Tu es {self.current_npc.name}, un PNJ dans un RPG avec ce contexte : {context}"
                f"Tu demandes de l'aide au joueur en une seule phrase."
            )
            prompt = "Demande au joueur de récupérer un objet en prenant en compte le context. Indique l'objet, où il se trouve, et pourquoi tu en as besoin."
            self.generator = generate_response_stream_queued(prompt, system_prompt)

            # Create quest
            npc.has_active_quest = True

            # Mark that quest item generation should happen on close
            self.pending_quest_item_gen = True

        elif npc.has_active_quest:
            if npc.quest_complete:
                # Quest completion dialogue
                system_prompt = (
                    f"Tu es {self.current_npc.name}, un PNJ dans un RPG avec ce contexte : {context}."
                    f"Le joueur vient de terminer ta quête."
                )
                prompt = (
                    f"Le joueur t'a apporté {npc.quest_item.name} ({npc.quest_content}). "
                    f"Remercie-le en une phrase et mentionne sa récompense en pièces."
                )
                self.generator = generate_response_stream_queued(prompt, system_prompt)

                # Mark that reward extraction should happen on close
                self.pending_reward_extraction = True

                # Reset quest status
                npc.has_active_quest = False
                npc.quest_complete = False
                npc.quest_item = None

            else:
                # Active quest not yet completed
                system_prompt = (
                    f"Tu es {self.current_npc.name}, un PNJ dans un RPG avec ce contexte : {context}."
                    f"Le joueur est en train d'accomplir ta quête, mais ne l'a pas encore terminée."
                )
                prompt = (
                    f"Rappelle au joueur sa mission : {npc.quest_content}. "
                    f"Encourage-le brièvement."
                )
                self.generator = generate_response_stream_queued(prompt, system_prompt)


        else:
            # Casual conversation
            system_prompt = f"Tu es {self.current_npc.name}, un PNJ dans un RPG. Tu discutes brièvement avec le joueur."
            prompt = "Dis une courte réplique au joueur pour le saluer."
            self.generator = generate_response_stream_queued(prompt, system_prompt)

    def _execute_quest_item_extraction(self):
        """Execute quest item extraction (called when dialogue closes)"""
        npc = self.current_npc
        
        # Extract quest item
        npc.quest_content = self.conversation_history[-1]["content"]
        system_prompt = "Tu es un assistant d'extraction. Réponds seulement avec l'information demandée, sans article ('le', 'la', 'l\', 'un', 'une', etc.) et sans guillemets."
        prompt = f"Quel est l'objet à récupérer dans '{npc.quest_content}' ?"
        
        # Use the queued version and get the response
        item_name = generate_response_queued(prompt, system_prompt)
        
        # Process the extracted item name
        item_name = item_name.strip().rstrip('.')

        # Create the quest item
        npc.quest_item = Item(*random_coordinates(), item_name)
        self.items_list.append(npc.quest_item) # Add to the global items list

    def _execute_reward_extraction(self):
        """Execute coin reward extraction (called when dialogue closes)"""
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
    
    def auto_scroll(self):
        """Auto-scroll to bottom of chat if needed"""
        total_height = self._calculate_total_content_height()
        if total_height > self.max_visible_height:
            self.scroll_offset = total_height - self.max_visible_height
        else:
            self.scroll_offset = 0

    def update(self, context: str):
        """Update dialogue text if generator is active"""        
        if self.pending_npc is not None:
            self.frames_waited += 1
            if self.frames_waited >= 2:
                self._generate_npc_dialogue(self.pending_npc, context)
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
                    self.auto_scroll()
                self.waiting_for_llm = False
            except StopIteration:
                self.generator = None
    
    def close(self):
        """Close the dialogue window and execute pending actions"""
        if self.active and self.generator is None:
            # Execute pending actions before closing
            if self.pending_quest_item_gen:
                threading.Thread(target=self._execute_quest_item_extraction, daemon=True).start()
                self.pending_quest_item_gen = False
            
            if self.pending_reward_extraction:
                threading.Thread(target=self._execute_reward_extraction, daemon=True).start()
                self.pending_reward_extraction = False
            
            # Now close the dialogue
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
        message_area_y = box_y + 55
        message_area_height = self.max_visible_height
        
        # Create a subsurface for clipping
        clip_rect = pygame.Rect(20, message_area_y, c.Screen.WIDTH - 40, message_area_height)
        screen.set_clip(clip_rect)
        
        # Calculate total height and starting y position
        total_height = self._calculate_total_content_height()
        y_offset = message_area_y - self.scroll_offset
        
        # Draw messages
        for msg in self.conversation_history:
            if msg["role"] == "user":
                prefix = "Vous : "
                color = c.Colors.CYAN
            else:
                prefix = f"{self.current_npc.name} : "
                color = c.Colors.WHITE
            
            # Word wrap the message (same as before)
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
                text_surface = self.message_font.render(line, True, color)
                screen.blit(text_surface, (25, y_offset))
                y_offset += self.line_height
        
        # Remove clipping
        screen.set_clip(None)
        
        # Draw scroll indicator if needed
        if total_height > message_area_height and self.scroll_offset < total_height - message_area_height:
            scroll_text = f"↑ Défiler pour voir plus"
            scroll_surface = self.small_font.render(scroll_text, True, c.Colors.YELLOW)
            screen.blit(scroll_surface, (c.Screen.WIDTH - 250, message_area_y - 35))
        
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
        instruction = self.small_font.render("ENTRÉE: Envoyer | Flèches Haut/Bas: Défiler chat | ECHAP: Fermer", True, c.Colors.CYAN)
        screen.blit(instruction, (25, box_y + box_height - 25))
