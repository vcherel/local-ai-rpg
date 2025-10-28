import colorsys
import random

import core.constants as c

def random_color():
    h = random.random()
    s = 0.3 + 0.2 * random.random()
    l = 0.4 + 0.2 * random.random()
    r, g, b = [int(x * 255) for x in colorsys.hls_to_rgb(h, l, s)]
    return (r, g, b)

def random_coordinates():
    return tuple(random.randint(0, c.Game.WORLD_SIZE) for _ in range(2))

class ConversationHistory:
    """Manages conversation message history"""
    
    def __init__(self):
        self.messages = []  # List of {"role": "user"/"assistant", "content": str}
    
    def add_user_message(self, content: str):
        """Add a user message to history"""
        self.messages.append({"role": "user", "content": content})
    
    def add_assistant_message(self, content: str):
        """Add an assistant message to history"""
        self.messages.append({"role": "assistant", "content": content})
    
    def update_last_assistant_message(self, content: str):
        """Update the last assistant message (for streaming)"""
        if self.messages and self.messages[-1]["role"] == "assistant":
            self.messages[-1]["content"] = content
        else:
            self.add_assistant_message(content)
    
    def get_recent_messages(self, limit: int = 10):
        """Get recent messages for context"""
        return self.messages[-limit:]
    
    def get_last_message(self):
        """Get the last message"""
        return self.messages[-1] if self.messages else None
    
    def clear(self):
        """Clear all messages"""
        self.messages.clear()
    
    def format_for_prompt(self, exclude_last: bool = True):
        """Format conversation history for LLM prompt"""
        messages = self.messages[:-1] if exclude_last else self.messages
        conversation_text = ""
        for msg in messages:
            if msg['role'] == 'user':
                conversation_text += f"Joueur: {msg['content']}\n"
            else:
                conversation_text += f"PNJ: {msg['content']}\n"
        return conversation_text
