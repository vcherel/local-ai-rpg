from llama_cpp import Llama
import time

# Load the model
llm = Llama(
    model_path="./model/LFM2-2.6B-Q4_0.gguf",
    n_gpu_layers=20,
    verbose=False,
    n_ctx=128000,
    flash_attn=True,
    seed=int(time.time() * 1000) % (2**31)
)

def generate_response(prompt, max_new_tokens=100, temperature=0.8, repetition_penalty=1.2):
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
    formatted_prompt = f"{prompt}\nAnswer:"
    
    # Reset the model state
    llm.reset()
    
    # Generate response
    response = llm(
        prompt=formatted_prompt,
        max_tokens=max_new_tokens,
        temperature=temperature,
        repeat_penalty=repetition_penalty,
        stop=["\n"]  # Stop at newline like the original
    )
    
    # Extract the generated text
    generated_text = response.get("choices", [{}])[0].get("text", "").strip()
    
    # Remove any quotation marks
    generated_text = generated_text.replace('"', '')
    
    return generated_text


def generate_response_stream(prompt, max_new_tokens=100, temperature=0.8, repetition_penalty=1.2):
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
    formatted_prompt = f"{prompt}\nAnswer:"
    
    # Reset the model state
    llm.reset()
    
    # Generate response with streaming
    stream = llm(
        prompt=formatted_prompt,
        max_tokens=max_new_tokens,
        temperature=temperature,
        repeat_penalty=repetition_penalty,
        stream=True
    )
    
    accumulated_text = ""
    
    # Iterate through the stream and yield accumulated tokens
    for output in stream:
        new_token = output.get("choices", [{}])[0].get("text", "")
        
        # Remove any quotation marks from the new token
        new_token = new_token.replace('"', '')
        
        accumulated_text += new_token
        
        # Stop if newline is generated (matching original behavior)
        if '\n' in new_token:
            break
            
        yield accumulated_text