import pygame
import random
import math
import sys
import threading
from queue import Queue
from typing import Callable, Optional

from constants import GREEN, BLACK, INTERACTION_DISTANCE, PLAYER_SPEED, SCREEN_HEIGHT, SCREEN_WIDTH, WHITE
from classes import Player, NPC
from dialogue_manager import DialogueManager


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
        self.world_width = SCREEN_WIDTH * 2
        self.world_height = SCREEN_HEIGHT * 2
        
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
        for i in range(3):
            x = random.randint(100, self.world_width - 100)
            y = random.randint(100, self.world_height - 100)
            self.npcs.append(NPC(x, y, i))
        
        # Background task manager
        self.task_manager = BackgroundTaskManager()
        
        # Dialogue manager
        self.dialogue_manager = DialogueManager(self.world_width, self.world_height, self.task_manager)
        self.dialogue_manager.items_list = self.items
        self.dialogue_manager.player = self.player
        
        # Camera
        self.camera_x = 0
        self.camera_y = 0
        
        # Fonts
        self.small_font = pygame.font.SysFont("arial", 22)
    
    def update_camera(self):
        """Center camera on player"""
        self.camera_x = self.player.x - SCREEN_WIDTH // 2
        self.camera_y = self.player.y - SCREEN_HEIGHT // 2
        
        # Clamp camera to world bounds
        self.camera_x = max(0, min(self.camera_x, self.world_width - SCREEN_WIDTH))
        self.camera_y = max(0, min(self.camera_y, self.world_height - SCREEN_HEIGHT))
    
    def interact_with_nearby_npc(self):
        """Check for nearby NPCs and interact"""
        for npc in self.npcs:
            if npc.distance_to_player(self.player) < INTERACTION_DISTANCE:
                self.dialogue_manager.interact_with_npc(npc)
                break  # Only interact with one NPC at a time
    
    def pickup_nearby_item(self):
        """Check for nearby items and pick them up"""
        for item in self.items:
            if not item.picked_up and item.distance_to_player(self.player) < INTERACTION_DISTANCE:
                item.picked_up = True
                self.player.inventory.append(item.name)
                break
    
    def draw_ui(self):
        """Draw inventory, coins, and controls"""
        # Draw inventory and coins
        inventory_text = f"Inventaire: {', '.join(self.player.inventory) if self.player.inventory else 'Vide'}"
        coins_text = f"Pièces: {self.player.coins}"
        
        inv_surface = self.small_font.render(inventory_text, True, WHITE)
        coins_surface = self.small_font.render(coins_text, True, WHITE)
        
        self.screen.blit(inv_surface, (10, 10))
        self.screen.blit(coins_surface, (10, 35))
        
        # Draw controls
        controls = self.small_font.render("ZQSD : Déplacer | E : Parler/Ramasser | ESPACE : Fermer le dialogue", True, WHITE)
        self.screen.blit(controls, (10, SCREEN_HEIGHT - 25))
    
    def draw_world(self):
        """Draw all world elements"""
        # Background
        self.screen.fill(GREEN)
        
        # Floor details
        for (x, y, kind) in self.floor_details:
            if kind == "stone":
                pygame.draw.circle(self.screen, (100, 100, 100), 
                                (x - self.camera_x, y - self.camera_y), 3)
            else:
                pygame.draw.circle(self.screen, (255, 0, 0), 
                                (x - self.camera_x, y - self.camera_y), 2)
        
        # World border
        pygame.draw.rect(self.screen, WHITE, 
                    (0 - self.camera_x, 0 - self.camera_y, 
                        self.world_width, self.world_height), 3)
        
        # NPCs
        for npc in self.npcs:
            npc.draw(self.screen, self.camera_x, self.camera_y)
        
        # Items
        for item in self.items:
            item.draw(self.screen, self.camera_x, self.camera_y)
        
        # Player
        self.player.draw(self.screen, self.camera_x, self.camera_y)
        
        # Off-screen item indicators
        self.draw_offscreen_indicators()

    def draw_offscreen_indicators(self):
        """Draw arrows pointing to items that are off-screen"""
        margin = 30
        arrow_size = 32
        
        for item in self.items:
            if item.picked_up:
                continue
            
            # Calculate item position relative to camera
            item_screen_x = item.x - self.camera_x
            item_screen_y = item.y - self.camera_y
            
            # Check if item is off-screen
            is_offscreen = (item_screen_x < 0 or item_screen_x > SCREEN_WIDTH or
                        item_screen_y < 0 or item_screen_y > SCREEN_HEIGHT)
            
            if is_offscreen:
                # Calculate direction to item
                dx = item.x - (self.camera_x + SCREEN_WIDTH // 2)
                dy = item.y - (self.camera_y + SCREEN_HEIGHT // 2)
                
                # Normalize direction
                distance = math.sqrt(dx * dx + dy * dy)
                if distance > 0:
                    dx /= distance
                    dy /= distance
                
                # Find intersection with screen bounds
                arrow_x = SCREEN_WIDTH // 2 + dx * (SCREEN_WIDTH // 2 - margin)
                arrow_y = SCREEN_HEIGHT // 2 + dy * (SCREEN_HEIGHT // 2 - margin)
                
                # Clamp to screen edges
                arrow_x = max(margin, min(arrow_x, SCREEN_WIDTH - margin))
                arrow_y = max(margin, min(arrow_y, SCREEN_HEIGHT - margin))
                
                # Calculate angle for arrow rotation
                angle = math.atan2(dy, dx)
                
                # Create arrow points (pointing right initially)
                arrow_points = [
                    (arrow_size, 0),
                    (-arrow_size // 2, -arrow_size // 2),
                    (-arrow_size // 2, arrow_size // 2)
                ]
                
                # Rotate and translate arrow points
                rotated_points = []
                for px, py in arrow_points:
                    # Rotate
                    rx = px * math.cos(angle) - py * math.sin(angle)
                    ry = px * math.sin(angle) + py * math.cos(angle)
                    # Translate
                    rotated_points.append((arrow_x + rx, arrow_y + ry))
                
                # Draw semi-transparent arrow
                # Create a surface for transparency
                arrow_surface = pygame.Surface((arrow_size * 3, arrow_size * 3), pygame.SRCALPHA)
                
                # Translate points to local surface coordinates
                local_points = [(p[0] - arrow_x + arrow_size * 1.5, 
                            p[1] - arrow_y + arrow_size * 1.5) for p in rotated_points]
                
                # Draw arrow with item's color but semi-transparent
                arrow_color = (*item.color, 120)  # Add alpha channel
                pygame.draw.polygon(arrow_surface, arrow_color, local_points)
                pygame.draw.polygon(arrow_surface, (*BLACK, 150), local_points, 1)
                
                # Blit to screen
                self.screen.blit(arrow_surface, (arrow_x - arrow_size * 1.5, arrow_y - arrow_size * 1.5))

    def handle_input(self):
        """Handle keyboard input"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_e and not self.dialogue_manager.active:
                    self.interact_with_nearby_npc()
                    if not self.dialogue_manager.active:
                        self.pickup_nearby_item()
                
                if event.key == pygame.K_SPACE:
                    self.dialogue_manager.close()
        
        return True
    
    def update_player_movement(self):
        """Update player position based on input"""
        if not self.dialogue_manager.active:
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
    
    def run(self):
        """Main game loop"""
        running = True
        
        while running:
            # Process background task callbacks
            self.task_manager.process_callbacks()
            
            # Handle input
            running = self.handle_input()
            if not running:
                break
            
            # Update dialogue
            self.dialogue_manager.update()
            
            # Update player movement
            self.update_player_movement()
            
            # Update camera
            self.update_camera()
            
            # Draw everything
            self.draw_world()
            self.draw_ui()
            self.dialogue_manager.draw(self.screen)
            
            pygame.display.flip()
            self.clock.tick(60)
        
        pygame.quit()
        sys.exit()


# Initialize Pygame
pygame.init()

game = Game()
game.run()