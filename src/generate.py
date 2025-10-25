from llama_cpp import Llama
import time

import constants as c

# Load the model
llm = Llama(
    model_path="./models/LFM2-2.6B-Q4_0.gguf",
    n_gpu_layers=20,
    verbose=False,
    n_ctx=128000,
    flash_attn=True,
    seed=int(time.time() * 1000) % (2**31)
)

def generate_response(prompt):
    """
    Generate a response from a prompt.
    
    Args:
        prompt: Input text prompt
        max_new_tokens: Maximum number of tokens to generate
        temperature: Sampling temperature (higher = more random)
        repetition_penalty: Penalty for repeating tokens
    
    Returns:
        str: Generated response text
    """    
    # Simplified prompt formatting for dialogue
    formatted_prompt = f"{prompt}\Réponse :"
    
    # Reset the model state
    llm.reset()
    
    # Generate response
    response = llm(
        prompt=formatted_prompt,
        max_tokens=c.Hyperparameters.MAX_TOKENS,
        temperature=c.Hyperparameters.TEMPERATURE,
        repeat_penalty=c.Hyperparameters.REPETITION_PENALTY
    )
    
    # Extract the generated text
    generated_text = response.get("choices", [{}])[0].get("text", "").strip()

    # Remove any quotation marks from the generated text
    generated_text = generated_text.translate(str.maketrans('', '', '"«»'))

    # Remove leading/trailing newlines
    generated_text = generated_text.strip('\n')

    # If newline in middle → keep left part only
    if '\n' in generated_text:
        generated_text = generated_text.split('\n', 1)[0].strip()
    
    return generated_text


def generate_response_stream(prompt):
    """
    Generate a response from a prompt with streaming output.
    
    Args:
        prompt: Input text prompt
        max_new_tokens: Maximum number of tokens to generate
        temperature: Sampling temperature (higher = more random)
        repetition_penalty: Penalty for repeating tokens
    
    Yields:
        str: Accumulated generated text after each token
    """
    # Simplified prompt formatting for dialogue
    formatted_prompt = f"{prompt}\Réponse :"
    
    # Reset the model state
    llm.reset()
    
    # Generate response with streaming
    stream = llm(
        prompt=formatted_prompt,
        max_tokens=c.Hyperparameters.MAX_TOKENS,
        temperature=c.Hyperparameters.TEMPERATURE,
        repeat_penalty=c.Hyperparameters.REPETITION_PENALTY,
        stream=True
    )
    
    accumulated_text = ""
    started = False
    
    # Iterate through the stream and yield accumulated tokens
    for output in stream:
        new_token = output.get("choices", [{}])[0].get("text", "")
        
        # Remove any quotation marks from the new token
        new_token = new_token.translate(str.maketrans('', '', '"«»'))

        if new_token:
            started = True

        if started and new_token == "\n":  # Do not stop if \n is first character
            break

        accumulated_text += new_token
            
        yield accumulated_text