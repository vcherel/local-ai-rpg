import re
import random
import time
import pygame
from typing import Optional

from constants import DARK_GRAY, SCREEN_HEIGHT, SCREEN_WIDTH, WHITE, YELLOW
from generate import generate_response, generate_response_stream
from classes import NPC, Item


class DialogueManager:
    """Manages all dialogue, quest, and NPC interaction logic"""
    
    def __init__(self, world_width: int, world_height: int, task_manager):
        self.world_width = world_width
        self.world_height = world_height
        self.task_manager = task_manager
        
        # Dialogue state
        self.active = False
        self.generator = None
        self.current_text = ""
        self.current_npc: Optional[NPC] = None
        self.scroll = 0
        
        # Fonts
        self.font = pygame.font.SysFont("arial", 28, bold=True)
        self.small_font = pygame.font.SysFont("arial", 22)
        
        # References (set externally)
        self.items_list = None  # Will be set to game.items
        self.player = None  # Will be set to game.player
    
    def interact_with_npc(self, npc: NPC):
        """Start interaction with an NPC"""
        # Check if player has quest item
        if npc.has_active_quest and npc.quest_item_name in self.player.inventory:
            # Complete quest
            self.player.inventory.remove(npc.quest_item_name)
            npc.quest_complete = True
        
        self.current_npc = npc
        self.active = True
        self.scroll = 0
        self.current_text = ""
        
        # Generate dialogue
        self._generate_npc_dialogue(npc)
    
    def _generate_npc_dialogue(self, npc: NPC):
        """Generate interaction dialogue with NPC"""
        # Choose type of interaction
        interaction_type = random.choices(
            ["quest", "talk"],
            weights=[0.7, 0.3],
            k=1
        )[0]
        
        if interaction_type == "quest" and not npc.has_active_quest:
            # Generate quest
            prompt = (
                "Tu es un PNJ dans un RPG. Demande au joueur de récupérer un objet. "
                "Écris-le comme une phrase naturelle et fluide, à la première personne, "
                "indique l'objet, où le trouver et pourquoi tu en as besoin. "
                "Demande directement son aide. Ne fais pas de listes ni de bullet points.\n\n"
                "Exemple de style souhaité : 'Salut ! Peux-tu m'aider à retrouver mon épée perdue dans la forêt ? J'en ai besoin pour vaincre le dragon.'"
            )
            self.generator = generate_response_stream(prompt)
            
            # Create quest
            npc.has_active_quest = True
            
            # Wait for dialogue to complete, then generate quest item
            self._schedule_quest_item_generation(npc)
        
        elif npc.has_active_quest and npc.quest_complete:
            # Quest completion dialogue (NPC rewards player)
            prompt = (
                f"Tu es un PNJ dans un RPG. Le joueur a terminé ta quête ({npc.quest_content}) et t'a apporté l'objet : {npc.quest_item_name}. "
                f"Tu dois commenter la quête et l'objet, et tu peux remercier le joueur ou lui donner des pièces. Actuellement, le joueur a {self.player.coins} pièces. "
                f"Fais court et concis."
            )

            self.generator = generate_response_stream(prompt)
            
            # Extract reward after dialogue completes
            self._schedule_reward_extraction()
            
            # Reset quest status
            npc.has_active_quest = False
            npc.quest_complete = False
            npc.quest_item_name = None
        
        else:
            # Casual conversation
            prompt = (
                f"Tu es un PNJ dans un monde RPG. Dis une courte réplique aléatoire : un salut, un commentaire ou une question au joueur. "
                f"Reste concis et naturel. Ne continue pas la conversation et n’ajoute pas de dialogue supplémentaire."
            )

            self.generator = generate_response_stream(prompt)
    
    def _schedule_quest_item_generation(self, npc: NPC):
        """Schedule quest item generation after dialogue completes"""
        def generate_when_ready():
            # Wait for dialogue to finish accumulating
            while self.generator is not None:
                time.sleep(0.1)
            
            # Now extract quest item from completed dialogue
            npc.quest_content = self.current_text
            extract_prompt = f"À partir de cette quête : '{npc.quest_content}', extrais uniquement le nom de l'objet."
            item_name = generate_response(extract_prompt).strip()
            
            return item_name
        
        def on_complete(item_name):
            npc.quest_item_name = item_name
            
            # Spawn the item
            item_x = random.randint(100, self.world_width - 100)
            item_y = random.randint(100, self.world_height - 100)
            self.items_list.append(Item(item_x, item_y, item_name))
        
        self.task_manager.add_task(generate_when_ready, on_complete)
    
    def _schedule_reward_extraction(self):
        """Schedule coin reward extraction after dialogue completes"""
        def extract_when_ready():
            # Wait for dialogue to finish
            while self.generator is not None:
                time.sleep(0.1)
            
            # First try to extract coin number directly from NPC's message
            match = re.search(r'\b(\d+)\b', self.current_text)
            if match:
                return int(match.group(1))
            
            # If no explicit number found, use LLM to extract the amount
            extract_prompt = (
                f"À partir de ce message du PNJ : '{self.current_text}', détermine combien de pièces le joueur devrait recevoir selon ce que le PNJ a dit. "
                f"Extrait UNIQUEMENT le nombre de pièces sous forme d'entier."
            )
            reward_str = generate_response(extract_prompt).strip()
            
            # Clean up any non-numeric characters
            reward_str = re.sub(r'[^\d]', '', reward_str)
            
            if reward_str:
                return int(reward_str)
            return 0
        
        def on_complete(reward):
            if reward > 0:
                self.player.coins += reward
        
        self.task_manager.add_task(extract_when_ready, on_complete)
    
    def update(self):
        """Update dialogue text if generator is active"""
        if self.active and self.generator is not None:
            try:
                # Get next partial text from generator
                partial = next(self.generator)
                self.current_text = partial
            except StopIteration:
                # Generator finished
                self.generator = None
    
    def close(self):
        """Close the dialogue window"""
        if self.active and self.generator is None:
            self.active = False
            self.current_npc = None
    
    def draw(self, screen):
        """Draw dialogue box if active"""
        if not self.active:
            return
        
        box_height = 200
        box_y = SCREEN_HEIGHT - box_height - 25
        pygame.draw.rect(screen, DARK_GRAY, 
                       (10, box_y, SCREEN_WIDTH - 20, box_height))
        pygame.draw.rect(screen, WHITE, 
                       (10, box_y, SCREEN_WIDTH - 20, box_height), 2)
        
        # Word wrap dialogue
        words = self.current_text.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            if self.small_font.size(test_line)[0] < SCREEN_WIDTH - 60:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        if current_line:
            lines.append(' '.join(current_line))
        
        # Draw lines
        y_offset = box_y + 15
        for line in lines:
            text_surface = self.small_font.render(line, True, WHITE)
            screen.blit(text_surface, (25, y_offset))
            y_offset += 25
        
        # Draw instruction
        if self.generator is None:
            instruction = self.small_font.render("Appuyez sur ESPACE pour fermer", True, YELLOW)
            screen.blit(instruction, (SCREEN_WIDTH - 350, box_y + box_height - 30))