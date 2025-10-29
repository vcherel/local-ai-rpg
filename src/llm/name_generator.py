import queue
import threading
import time

from core.save import SaveSystem
from llm.llm_request_queue import generate_response_queued


class NPCNameGenerator:
    """Background generator for NPC names"""

    def __init__(self, save_system, get_context_callback):
        self.name_queue = queue.Queue(maxsize=1)  # Only keep 1 name ready
        self.lock = threading.Lock()
        self.get_context = get_context_callback
        self.is_generating = False

        self.save_system: SaveSystem = save_system
        
        # Start generating the first name immediately
        self.start_generation()
    
    def start_generation(self):
        """Start a background thread to generate a name"""
        with self.lock:
            if self.is_generating or not self.name_queue.empty():
                return  # Already generating or have a name ready
            
            loaded_name: str = self.save_system.load("name", None)
            if loaded_name:
                self.name_queue.put(loaded_name.strip())
                self.save_system.update("name", None)
                return  # Loaded name from memory
            
            self.is_generating = True
        
        threading.Thread(target=self._generate_name_background, daemon=True).start()

    def _generate_name_background(self):
        # Wait for context to be ready
        context = None
        while context is None:
            context = self.get_context()
            if context is None:
                time.sleep(0.1)  # avoid busy waiting

        system_prompt = f"Tu es un générateur de PNJ pour un RPG. Contexte: {context}. Réponds uniquement avec UN prénom et/ou UNE profession, sur une seule ligne, sans répétition, sans explication."
        prompt = "Génère un prénom et/ou une profession pour un PNJ de RPG."
        
        name = generate_response_queued(prompt, system_prompt, "Name generation")
        self.name_queue.put(name.strip())

        with self.lock:
            self.is_generating = False
    
    def get_name(self) -> str:
        """
        Get a generated name (waits if necessary)
        """
        # Wait until a name is ready
        name = self.name_queue.get()
        
        return name
