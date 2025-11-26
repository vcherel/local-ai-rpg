import pygame

import core.constants as c
from game.quest import Quest

class QuestNotification:
    def __init__(self, screen):
        self.screen = screen
        self.active = False
        self.quest = None
        self.start_time = 0
        self.duration = 5000  # 5 seconds
        
        # Dimensions
        self.width = 1000
        self.height = 150
        self.padding = 15
        
        # Animation
        self.slide_duration = 300  # ms
        self.target_x = 20
        self.start_x = -self.width
        
    def show(self, quest: Quest):
        """Trigger notification for new quest"""
        self.quest = quest
        self.active = True
        self.start_time = pygame.time.get_ticks()
    
    def _get_current_x(self):
        """Calculate x position with slide animation"""
        elapsed = pygame.time.get_ticks() - self.start_time
        
        if elapsed < self.slide_duration:
            # Slide in
            progress = elapsed / self.slide_duration
            return self.start_x + (self.target_x - self.start_x) * progress
        elif elapsed > self.duration - self.slide_duration:
            # Slide out
            progress = (elapsed - (self.duration - self.slide_duration)) / self.slide_duration
            return self.target_x + (self.start_x - self.target_x) * progress
        else:
            # Static
            return self.target_x
    
    def _wrap_text(self, text, max_width, font):
        """Wrap text to fit width"""
        words = text.split(' ')
        lines = []
        current_line = []
        
        for word in words:
            current_line.append(word)
            line = ' '.join(current_line)
            if font.size(line)[0] > max_width:
                if len(current_line) == 1:
                    lines.append(line)
                    current_line = []
                else:
                    current_line.pop()
                    lines.append(' '.join(current_line))
                    current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines
    
    def draw(self):
        """Draw notification if active"""
        if not self.active or not self.quest:
            return
        
        # Check if notification should end
        if pygame.time.get_ticks() - self.start_time > self.duration:
            self.active = False
            return
        
        # Get animated position
        x = self._get_current_x()
        y = 20
        
        # Create notification surface
        surface = pygame.Surface((self.width, self.height))
        surface.fill(c.Colors.BUTTON)
        pygame.draw.rect(surface, c.Colors.BORDER, (0, 0, self.width, self.height), 3)
        
        # Title
        title = c.Fonts.title.render(f"Nouvelle quête de {self.quest.npc_name}", True, c.Colors.YELLOW)
        surface.blit(title, (self.padding, self.padding))
        
        # Description (wrapped)
        max_width = self.width - 2 * self.padding
        desc_lines = self._wrap_text(self.quest.description, max_width, c.Fonts.text)
        desc_y = self.padding + 65
        for line in desc_lines[:2]:  # Max 2 lines
            desc_surface = c.Fonts.text.render(line, True, c.Colors.WHITE)
            surface.blit(desc_surface, (self.padding, desc_y))
            desc_y += 20

        # NPC and item
        npc_text = f"Objet: {self.quest.item_name}"
        npc_surface = c.Fonts.button.render(npc_text, True, c.Colors.WHITE)
        surface.blit(npc_surface, (self.padding, self.padding + 35))
        
        # Blit to screen
        self.screen.blit(surface, (int(x), y))
