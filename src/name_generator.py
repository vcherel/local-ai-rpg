import queue
import threading

from llm_request_queue import generate_response_queued


class NPCNameGenerator:
    """Background generator for NPC names"""
    
    def __init__(self):
        self.name_queue = queue.Queue(maxsize=1)  # Only keep 1 name ready
        self.is_generating = False
        self.lock = threading.Lock()
        
        # Start generating the first name immediately
        self._start_generation()
    
    def _start_generation(self):
        """Start a background thread to generate a name"""
        with self.lock:
            if self.is_generating or not self.name_queue.empty():
                return  # Already generating or have a name ready
            
            self.is_generating = True
        
        thread = threading.Thread(target=self._generate_name_background, daemon=True)
        thread.start()
    
    def _generate_name_background(self):
        system_prompt = "Tu es un générateur de PNJ pour un RPG. Réponds uniquement avec UN prénom et/ou UNE profession, sur une seule ligne, sans répétition, sans explication."
        prompt = "Génère un prénom et/ou une profession pour un PNJ de RPG."
        
        # Use the queued function to avoid blocking
        name = generate_response_queued(prompt, system_prompt)
            
        # Put result in queue (will block if queue is full, but we set maxsize=1)
        self.name_queue.put(name.strip())
    
        with self.lock:
            self.is_generating = False
    
    def get_name(self) -> str:
        """
        Get a generated name (waits if necessary), then start generating the next one.
        """
        # Wait until a name is ready
        name = self.name_queue.get()
        
        # Start generating the next name in background
        self._start_generation()
        
        return name


# Global instance
_npc_name_generator = None

def get_npc_name_generator() -> NPCNameGenerator:
    """Get or create the global NPC name generator"""
    global _npc_name_generator
    if _npc_name_generator is None:
        _npc_name_generator = NPCNameGenerator()
    return _npc_name_generator