import pygame
import random
import sys

from constants import DARK_GRAY, GREEN, INTERACTION_DISTANCE, PLAYER_SPEED, SCREEN_HEIGHT, SCREEN_WIDTH, WHITE, YELLOW
from generate import generate_response
from classes import Player, NPC, Item


class Game:
    def __init__(self):
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        
        # World settings
        self.world_width = 2500
        self.world_height = 2000
        
        # Game objects
        self.player = Player(self.world_width // 2, self.world_height // 2)
        self.npcs = []
        self.items = []
        
        # Spawn NPCs randomly
        for i in range(5):
            x = random.randint(100, self.world_width - 100)
            y = random.randint(100, self.world_height - 100)
            self.npcs.append(NPC(x, y, i))
        
        # UI state
        self.dialogue_active = False
        self.current_dialogue = ""
        self.current_npc = None
        self.dialogue_scroll = 0
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 20)
        
        # Camera
        self.camera_x = 0
        self.camera_y = 0
    
    def update_camera(self):
        # Center camera on player
        self.camera_x = self.player.x - SCREEN_WIDTH // 2
        self.camera_y = self.player.y - SCREEN_HEIGHT // 2
        
        # Clamp camera to world bounds
        self.camera_x = max(0, min(self.camera_x, self.world_width - SCREEN_WIDTH))
        self.camera_y = max(0, min(self.camera_y, self.world_height - SCREEN_HEIGHT))
    
    def generate_npc_interaction(self, npc):
        """Generate interaction dialogue with NPC"""
        # Choose type of interaction
        interaction_type = random.choice(["quest", "talk"])
        
        if interaction_type == "quest" and not npc.has_active_quest:
            # Generate quest
            prompt = (
                f"You are an NPC in a RPG game. Generate a quest where you ask the player to find and bring you a specific item."
                f"Keep it brief."
            )
            response = generate_response(prompt, max_new_tokens=80)
            
            quest_text = response.strip()
            
            # Ask LLM to extract item name
            extract_prompt = f"From this quest: '{quest_text}', what is the item name? Answer with just the item name, nothing else."
            item_name = generate_response(extract_prompt, max_new_tokens=10).strip()
            
            # Create quest
            npc.has_active_quest = True
            npc.quest_item_name = item_name
            # TODO: add quest here
            
            # Spawn item in random location
            item_x = random.randint(100, self.world_width - 100)
            item_y = random.randint(100, self.world_height - 100)
            self.items.append(Item(item_x, item_y, item_name))
            
            return quest_text
        
        elif npc.has_active_quest and npc.quest_complete:
            # Quest completion dialogue
            prompt = (
                f"You are an NPC in a RPG. The player just completed your quest "
                f"and brought you the {npc.quest_item_name}. Thank them and react to receiving the item. Keep it brief."
            )
            response = generate_response(prompt, max_new_tokens=60)
            npc.has_active_quest = False
            npc.quest_complete = False
            npc.quest_item_name = None
            return response.strip()
        
        else:
            # Casual conversation
            prompt = f"You are an NPC in a RPG world. Have small talk with the player. Keep it brief."
            response = generate_response(prompt, max_new_tokens=70)
            return response.strip()
    
    def interact_with_nearby_npc(self):
        """Check for nearby NPCs and interact"""
        for npc in self.npcs:
            if npc.distance_to_player(self.player) < INTERACTION_DISTANCE:
                # Check if player has quest item
                if npc.has_active_quest and npc.quest_item_name in self.player.inventory:
                    # Complete quest
                    self.player.inventory.remove(npc.quest_item_name)
                    npc.quest_complete = True
                
                self.current_npc = npc
                self.dialogue_active = True
                self.dialogue_scroll = 0
                self.current_dialogue = "Generating response..."
                
                # Generate dialogue
                self.current_dialogue = self.generate_npc_interaction(npc)
                break # Only interact with one NPC at a time
    
    def pickup_nearby_item(self):
        """Check for nearby items and pick them up"""
        for item in self.items:
            if not item.picked_up and item.distance_to_player(self.player) < INTERACTION_DISTANCE:
                item.picked_up = True
                self.player.inventory.append(item.name)
                break
    
    def draw_ui(self):
        # Draw inventory and coins
        inventory_text = f"Inventory: {', '.join(self.player.inventory) if self.player.inventory else 'Empty'}"
        coins_text = f"Coins: {self.player.coins}"
        
        inv_surface = self.small_font.render(inventory_text, True, WHITE)
        coins_surface = self.small_font.render(coins_text, True, WHITE)
        
        self.screen.blit(inv_surface, (10, 10))
        self.screen.blit(coins_surface, (10, 35))
        
        # Draw dialogue box if active
        if self.dialogue_active:
            box_height = 200
            box_y = SCREEN_HEIGHT - box_height - 10
            pygame.draw.rect(self.screen, DARK_GRAY, 
                           (10, box_y, SCREEN_WIDTH - 20, box_height))
            pygame.draw.rect(self.screen, WHITE, 
                           (10, box_y, SCREEN_WIDTH - 20, box_height), 2)
            
            # Word wrap dialogue
            words = self.current_dialogue.split()
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
                self.screen.blit(text_surface, (25, y_offset))
                y_offset += 25
            
            # Draw instruction
            instruction = self.small_font.render("Press SPACE to close", True, YELLOW)
            self.screen.blit(instruction, (SCREEN_WIDTH - 200, box_y + box_height - 30))
        
        # Draw controls
        controls = self.small_font.render("ZQSD: Move | E: Talk/Pickup | SPACE: Close dialogue", True, WHITE)
        self.screen.blit(controls, (10, SCREEN_HEIGHT - 25))
    
    def run(self):
        running = True
        
        while running:
            # Event handling
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_e and not self.dialogue_active:
                        self.interact_with_nearby_npc()
                        if not self.dialogue_active:
                            self.pickup_nearby_item()
                    
                    if event.key == pygame.K_SPACE and self.dialogue_active:
                        self.dialogue_active = False
                        self.current_npc = None
            
            # Player movement
            if not self.dialogue_active:
                keys = pygame.key.get_pressed()
                dx = dy = 0
                
                if keys[pygame.K_z]:
                    dy = -PLAYER_SPEED
                if keys[pygame.K_s]:
                    dy = PLAYER_SPEED
                if keys[pygame.K_q]:
                    dx = -PLAYER_SPEED
                if keys[pygame.K_d]:
                    dx = PLAYER_SPEED
                
                self.player.move(dx, dy, self.world_width, self.world_height)
            
            # Update camera
            self.update_camera()
            
            # Drawing
            self.screen.fill(GREEN)
            
            # Draw world border
            pygame.draw.rect(self.screen, WHITE, 
                           (0 - self.camera_x, 0 - self.camera_y, 
                            self.world_width, self.world_height), 3)
            
            # Draw items
            for item in self.items:
                item.draw(self.screen, self.camera_x, self.camera_y)
            
            # Draw NPCs
            for npc in self.npcs:
                npc.draw(self.screen, self.camera_x, self.camera_y)
            
            # Draw player
            self.player.draw(self.screen, self.camera_x, self.camera_y)
            
            # Draw UI
            self.draw_ui()
            
            pygame.display.flip()
            self.clock.tick(60)
        
        pygame.quit()
        sys.exit()


# Initialize Pygame
pygame.init()

game = Game()
game.run()