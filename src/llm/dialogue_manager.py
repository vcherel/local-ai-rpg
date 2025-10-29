import threading
import pygame

from core.utils import ConversationHistory
from game.entities import NPC
from game.world import World
from llm.llm_request_queue import generate_response_stream_queued
from llm.name_generator import NPCNameGenerator
from llm.quest_system import QuestSystem
from ui.conversation_ui import ConversationUI


class DialogueManager:  
    def __init__(self, items, player):
        # Core state
        self.active = False
        self.current_npc = None
        self.waiting_for_llm = False
        self.system_prompt = ""
        self.conversation_ended = False  # Track if conversation has ended
        
        # Response streaming
        self.generator = None
        
        # Pending actions
        self.pending_quest_analysis = False
        self.pending_reward_extraction = False
        
        # Components
        self.conversation = ConversationHistory()
        self.ui = ConversationUI()
        self.quest_system = QuestSystem(items, player)
    
    def _build_system_prompt(self, npc: NPC, context: str) -> str:
        """Build the system prompt for the entire conversation"""
        system_prompt = f"Tu es {npc.name}, un PNJ dans un RPG avec ce contexte : {context}. "
        
        if npc.has_active_quest:
            if npc.quest_complete:
                system_prompt += (
                    f"Le joueur vient de te rapporter {npc.quest_item.name} que tu avais demandé ({npc.quest_content}). "
                    f"Remercie-le et mentionne sa récompense en pièces. "
                )
            elif npc.quest_item:
                system_prompt += (
                    f"Tu as demandé au joueur de récupérer {npc.quest_item.name}. "
                )
                if npc.quest_item in self.quest_system.player.inventory:
                    system_prompt += "Le joueur l'a maintenant dans son inventaire. "
                else:
                    system_prompt += "Le joueur ne l'a pas encore trouvé. "
        else:
            system_prompt += (
                "Tu peux avoir des besoins, des problèmes, ou des requêtes. "
                "Si le joueur te le demande, ou si cela émerge naturellement de la conversation, "
                "tu peux lui demander de récupérer un objet spécifique pour t'aider. "
                "Tu peux aussi n'avoir aucune quête à donner. "
            )
        
        system_prompt += (
            "Réponds naturellement en une ou deux phrases courtes et continue la conversation. "
            "Ne termine jamais un message par '[FIN]' à moins que le joueur dise explicitement au revoir. "
            "Si le joueur dit au revoir, ajoute '[FIN]' à la fin de ton message."
        )
        return system_prompt
    
    def interact_with_npc(self, npc: NPC, npc_name_generator: NPCNameGenerator, world: World):
        """Start interaction with an NPC"""
        npc.assign_name(npc_name_generator)
        
        # Check if player has quest item
        if npc.has_active_quest and npc.quest_item in self.quest_system.player.inventory:
            npc.quest_complete = True
        
        # Build system prompt once for entire conversation
        self.system_prompt = self._build_system_prompt(npc, world.context)
        
        # Initialize dialogue
        self.current_npc = npc
        self.active = True
        self.waiting_for_llm = True
        self.conversation_ended = False
        
        # Reset state
        self.conversation.clear()
        self.ui.reset()
        self.pending_quest_analysis = False
        self.pending_reward_extraction = False
        
        # Check if we need to extract reward after this conversation
        if npc.quest_complete:
            world.items.remove(npc.quest_item)
            self.pending_reward_extraction = True
            self.quest_system.complete_quest(npc)
        
        # Start conversation with initial greeting
        initial_prompt = "Le joueur s'approche de toi. Salue-le."
        self.generator = generate_response_stream_queued(initial_prompt, self.system_prompt, "First message")

    def handle_event(self, event, npc_name_generator: NPCNameGenerator):
        if not self.active:
            return False

        elif event.type == pygame.KEYDOWN:
            # Handle scrolling with arrow keys
            if event.key == pygame.K_UP:
                self.handle_scroll(1)  # Scroll up
            elif event.key == pygame.K_DOWN:
                self.handle_scroll(-1)  # Scroll down
            else:
                if not self.conversation_ended:
                    self.handle_text_input(event)
            
            if event.key == pygame.K_ESCAPE:
                self.close()
                npc_name_generator.start_generation()

        return True
    
    def handle_text_input(self, event):
        """Handle text input for chat"""
        if not self.active or self.conversation_ended:
            return
        
        message = self.ui.handle_text_input(event)
        if message:
            self._send_chat_message(message)
            self.ui.auto_scroll(self.conversation, self.current_npc.name)
    
    def handle_scroll(self, direction: int):
        """Handle scroll input"""
        if not self.active:
            return
        self.ui.handle_scroll(direction, self.conversation, self.current_npc.name)
    
    def _check_for_end_signal(self, text: str) -> bool:
        """Check if the NPC wants to end the conversation"""
        return '[FIN]' in text
    
    def update(self):
        """Update dialogue state and process streaming responses"""
        if self.active and self.generator is not None:
            try:
                partial = next(self.generator)
                self.conversation.update_last_assistant_message(partial)
                self.ui.auto_scroll(self.conversation, self.current_npc.name)
                self.waiting_for_llm = False
            except StopIteration:
                self.generator = None
                
                last_msg = self.conversation.get_last_message()

                # Avoid this:  "Elara : Elara : Hello !"
                if ":" in last_msg["content"]:
                    cleaned_content = last_msg["content"].split(":", 1)[-1].strip()
                    if len(cleaned_content) <= 25:
                        self.conversation.update_last_assistant_message(cleaned_content)
                
                # Avoid this: "How are you ?[FIN]"
                if "[FIN]" in last_msg["content"]:
                    cleaned_content = last_msg["content"].replace("[FIN]", "").strip()
                    self.conversation.update_last_assistant_message(cleaned_content)

                if last_msg and self._check_for_end_signal(last_msg["content"]):
                    # Clean the message and add end marker
                    cleaned_content = last_msg["content"].replace('[FIN]', '').strip()
                    self.conversation.update_last_assistant_message(cleaned_content)
                    
                    # Add the "[Conversation Ended]" message
                    self.conversation.add_system_message("[Conversation Ended]")
                    self.conversation_ended = True
                    self.ui.auto_scroll(self.conversation, self.current_npc.name)
                    
                    # Execute pending actions immediately when conversation ends
                    self._execute_pending_actions()
    
    def close(self):
        """Close dialogue"""
        if self.active and self.generator is None:
            if not self.current_npc.has_active_quest:
                self.pending_quest_analysis = True
            self._execute_pending_actions()
            
            # Reset state
            self.active = False
            self.waiting_for_llm = False
            self.system_prompt = ""
            self.conversation.clear()
            self.ui.reset()
            self.conversation_ended = False
    
    def _execute_pending_actions(self):
        """Execute pending quest analysis and reward extraction"""
        if self.pending_quest_analysis:
            threading.Thread(
                target=self._execute_quest_analysis,
                daemon=True
            ).start()
            self.pending_quest_analysis = False
        
        if self.pending_reward_extraction:
            threading.Thread(
                target=self._execute_reward_extraction,
                daemon=True
            ).start()
            self.pending_reward_extraction = False
    
    def draw(self, screen: pygame.Surface):
        """Draw the dialogue UI"""
        if not self.active:
            return
        self.ui.draw(screen, self.current_npc.name, self.conversation)
    
    def _send_chat_message(self, message: str):
        """Send a chat message to the NPC"""
        if self.conversation_ended:
            return
        
        self.conversation.add_user_message(message)
        
        conversation_text = self.conversation.format_for_prompt()
        conversation_text += f"Joueur: {message}"
        
        self.generator = generate_response_stream_queued(conversation_text, self.system_prompt, "Continuing conversation")
    
    def _execute_quest_analysis(self):
        """Analyze conversation for quest in background thread"""
        conversation_text = self.conversation.format_for_prompt()
        if conversation_text:
            quest_info = self.quest_system.analyze_conversation_for_quest(conversation_text)
            print(f"~~~ Generated these quest infos : {quest_info}")
            if quest_info['has_quest']:
                self.quest_system.create_quest_from_analysis(self.current_npc, quest_info)
    
    def _execute_reward_extraction(self):
        """Execute reward extraction in background thread"""
        last_msg = self.conversation.get_last_message()
        if last_msg:
            self.quest_system.extract_and_give_reward(last_msg["content"])
