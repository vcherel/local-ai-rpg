import colorsys
import json
import random
import re

import core.constants as c

def random_color():
    h = random.random()
    s = 0.3 + 0.2 * random.random()
    l = 0.4 + 0.2 * random.random()
    r, g, b = [int(x * 255) for x in colorsys.hls_to_rgb(h, l, s)]
    return (r, g, b)

def random_coordinates():
    return tuple(random.randint(0, c.World.WORLD_SIZE) for _ in range(2))

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

    def add_system_message(self, content: str):
        """Add a system message to history"""
        self.messages.append({"role": "system", "content": content})
    
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
    
    def format_for_prompt(self):
        """Format conversation history for LLM prompt"""
        conversation_text = ""
        for msg in self.messages:
            if msg['role'] == 'user':
                conversation_text += f"Joueur: {msg['content']}\n"
            else:
                conversation_text += f"PNJ: {msg['content']}\n"
        return conversation_text

def parse_response(response):
    try:
        response = response.strip()
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if not match:
            return {'has_quest': False, 'quest_description': '', 'item_name': ''}
        json_str = match.group(0)

        # Quote keys
        json_str = re.sub(r'([{,]\s*)(\w+)(?=\s*:)', r'\1"\2"', json_str)

        # Replace booleans
        json_str = re.sub(r':\s*True', ': true', json_str)
        json_str = re.sub(r':\s*False', ': false', json_str)

        # Quote unquoted string values (non-boolean, non-empty)
        json_str = re.sub(
            r':\s*([^"{},\s][^,}]*)',
            lambda m: f': "{m.group(1).strip()}"',
            json_str
        )

        # Fill empty values
        json_str = re.sub(r':\s*([,}])', r': ""\1', json_str)

        result = json.loads(json_str)
        return {
            'has_quest': bool(result.get('has_quest', False)),
            'quest_description': result.get('quest_description', ''),
            'item_name': result.get('item_name', '')
        }
    except Exception as e:
        print(f"Failed to parse quest analysis: {e}, response: {response}\n")

    # Fallback
    print("Warning: Using fallback.")
    return {'has_quest': False, 'quest_description': '', 'item_name': ''}
