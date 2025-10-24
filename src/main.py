import pygame
import random
import sys
import threading
import time
from queue import Queue
from typing import Callable, Optional

from constants import DARK_GRAY, GREEN, INTERACTION_DISTANCE, PLAYER_SPEED, SCREEN_HEIGHT, SCREEN_WIDTH, WHITE, YELLOW
from generate import generate_response, generate_response_stream
from classes import Player, NPC, Item


class BackgroundTaskManager:
    """Manages background tasks to avoid race conditions"""
    
    def __init__(self):
        self.active_tasks = []
        self.task_queue = Queue()
        self.lock = threading.Lock()
    
    def add_task(self, func: Callable, callback: Optional[Callable] = None):
        """Add a task to run in background. Callback runs on main thread."""
        task = {
            'thread': None,
            'func': func,
            'callback': callback,
            'completed': False,
            'result': None
        }
        
        def wrapper():
            try:
                result = func()
                with self.lock:
                    task['result'] = result
                    task['completed'] = True
                    if callback:
                        self.task_queue.put(lambda: callback(result))
            except Exception as e:
                print(f"Background task error: {e}")
                with self.lock:
                    task['completed'] = True
        
        task['thread'] = threading.Thread(target=wrapper, daemon=True)
        
        with self.lock:
            self.active_tasks.append(task)
        
        task['thread'].start()
    
    def process_callbacks(self):
        """Process completed task callbacks on main thread"""
        while not self.task_queue.empty():
            callback = self.task_queue.get()
            callback()
        
        # Clean up completed tasks
        with self.lock:
            self.active_tasks = [t for t in self.active_tasks if not t['completed']]


class Game:
    def __init__(self):
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        
        # World settings
        self.world_width = 2500
        self.world_height = 2000

        # World items
        self.floor_details = [
            (random.randint(0, self.world_width), random.randint(0, self.world_height), 
             random.choice(["stone", "flower"])) 
            for _ in range(300)
        ]

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
        self.dialogue_generator = None
        self.current_dialogue = ""
        self.current_npc = None
        self.dialogue_scroll = 0
        self.font = pygame.font.SysFont("arial", 28, bold=True)
        self.small_font = pygame.font.SysFont("arial", 22)
        
        # Camera
        self.camera_x = 0
        self.camera_y = 0
        
        # Background task manager
        self.task_manager = BackgroundTaskManager()
    
    def update_camera(self):
        # Center camera on player
        self.camera_x = self.player.x - SCREEN_WIDTH // 2
        self.camera_y = self.player.y - SCREEN_HEIGHT // 2
        
        # Clamp camera to world bounds
        self.camera_x = max(0, min(self.camera_x, self.world_width - SCREEN_WIDTH))
        self.camera_y = max(0, min(self.camera_y, self.world_height - SCREEN_HEIGHT))
    
    def generate_npc_interaction(self, npc: NPC):
        """Generate interaction dialogue with NPC"""
        # Choose type of interaction
        # interaction_type = random.choice(["quest", "talk"])
        interaction_type = random.choice(["quest"])
        
        if interaction_type == "quest" and not npc.has_active_quest:
            # Generate quest
            prompt = (
                f"You are an NPC in an RPG game. Give a quest asking the player to find a single item."
                f"Reply ONLY as the NPC would, in one short sentence. Do not add extra details or explanations."
            )

            self.dialogue_generator = generate_response_stream(prompt)
            
            # Create quest
            npc.has_active_quest = True
            
            # Wait for dialogue to complete, then generate quest item
            self.schedule_quest_item_generation(npc)
        
        elif npc.has_active_quest and npc.quest_complete:
            # Quest completion dialogue (NPC rewards player)
            prompt = (
                f"You are an NPC in an RPG. The player completed your quest ({npc.quest_content}) and brought you the {npc.quest_item_name}. "
                f"You must thank the player and explicitly give them a specific number of coins as a reward. "
                f"Reply only as the NPC, in one short sentence."
            )

            self.dialogue_generator = generate_response_stream(prompt)
            
            # Extract reward after dialogue completes
            self.schedule_reward_extraction()

            # Reset quest status
            npc.has_active_quest = False
            npc.quest_complete = False
            npc.quest_item_name = None
        
        else:
            # Casual conversation
            prompt = (
                f"You are an NPC in a RPG world. Have small talk with the player. "
                f"Say ONLY one sentence in your reply, stay in character."
            )
            self.dialogue_generator = generate_response_stream(prompt)
    
    def schedule_quest_item_generation(self, npc: NPC):
        """Schedule quest item generation after dialogue completes"""
        def generate_when_ready():
            # Wait for dialogue to finish accumulating
            while self.dialogue_generator is not None:
                time.sleep(0.1)
            
            # Now extract quest item from completed dialogue
            npc.quest_content = self.current_dialogue
            extract_prompt = f"From this quest: '{npc.quest_content}', extract ONLY the item name. Respond with nothing else, no explanations, no quotes, just the item name."
            item_name = generate_response(extract_prompt).strip()
            
            return (npc, item_name)
        
        def on_complete(result):
            npc, item_name = result
            npc.quest_item_name = item_name
            
            # Spawn the item
            item_x = random.randint(100, self.world_width - 100)
            item_y = random.randint(100, self.world_height - 100)
            self.items.append(Item(item_x, item_y, item_name))
        
        self.task_manager.add_task(generate_when_ready, on_complete)
    
    def schedule_reward_extraction(self):
        """Schedule coin reward extraction after dialogue completes"""
        def extract_when_ready():
            # Wait for dialogue to finish
            while self.dialogue_generator is not None:
                time.sleep(0.1)
            
            # Extract coin number from NPC's message
            import re
            match = re.search(r'\b(\d+)\b', self.current_dialogue)
            if match:
                return int(match.group(1))
            return 0
        
        def on_complete(reward):
            if reward > 0:
                self.player.coins += reward
        
        self.task_manager.add_task(extract_when_ready, on_complete)

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
                self.current_dialogue = ""
                
                # Generate dialogue
                self.generate_npc_interaction(npc)
                
                break  # Only interact with one NPC at a time
    
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
            box_y = SCREEN_HEIGHT - box_height - 25
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
            self.screen.blit(instruction, (SCREEN_WIDTH - 250, box_y + box_height - 30))
        
        # Draw controls
        controls = self.small_font.render("ZQSD: Move | E: Talk/Pickup | SPACE: Close dialogue", True, WHITE)
        self.screen.blit(controls, (10, SCREEN_HEIGHT - 25))
    
    def run(self):
        running = True
        
        while running:
            # Process background task callbacks
            self.task_manager.process_callbacks()
            
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

            # Update dialogue text if generator is active
            if self.dialogue_active and self.dialogue_generator is not None:
                try:
                    # Get next partial text from generator
                    partial = next(self.dialogue_generator)
                    self.current_dialogue = partial
                except StopIteration:
                    # Generator finished
                    self.dialogue_generator = None
            
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
            for (x, y, kind) in self.floor_details:
                if kind == "stone":
                    pygame.draw.circle(self.screen, (100, 100, 100), 
                                     (x - self.camera_x, y - self.camera_y), 3)
                else:
                    pygame.draw.circle(self.screen, (255, 0, 0), 
                                     (x - self.camera_x, y - self.camera_y), 2)
            
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