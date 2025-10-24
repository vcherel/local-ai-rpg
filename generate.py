from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
if device.type == "cpu":
    print("Using CPU. This may be slow.")

tokenizer = AutoTokenizer.from_pretrained("LiquidAI/LFM2-700M")
model = AutoModelForCausalLM.from_pretrained("LiquidAI/LFM2-700M").to(device)

def generate_response(prompt, max_new_tokens=150, temperature=0.7, repetition_penalty=1.2):
    # Ensure pad_token is defined
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    formatted_prompt = f"Please answer the following question concisely in one paragraph:\n{prompt}\nAnswer:"
    encoded = tokenizer(formatted_prompt, return_tensors="pt", padding=True)
    input_ids = encoded.input_ids.to(device)
    attention_mask = encoded.attention_mask.to(device)

    output_ids = input_ids.clone()

    for _ in range(max_new_tokens):
        outputs = model.generate(
            output_ids,
            max_new_tokens=1,
            do_sample=True,
            temperature=temperature,
            repetition_penalty=repetition_penalty,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
            attention_mask=attention_mask
        )

        new_token_id = outputs[0, -1].unsqueeze(0).unsqueeze(0)
        output_ids = torch.cat([output_ids, new_token_id], dim=-1)

        # Update attention mask
        new_mask = torch.ones((1, 1), device=device)
        attention_mask = torch.cat([attention_mask, new_mask], dim=-1)

        new_token = tokenizer.decode(new_token_id[0], skip_special_tokens=True)
        print(new_token, end="", flush=True)

        if new_token_id.item() == tokenizer.eos_token_id:
            break
    print()