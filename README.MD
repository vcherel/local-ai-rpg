## Prompt

I want to create an open-world 2D RPG video game for my own use with Pygame. In this game, we spawn in a world without any objective, and every goal we will have in the game will be determined by AI. We encounter random characters, and we can talk with all of them, and quests are created during the game by a LLM.


Instead of having a loading time and then all text at once, I would like it to come bit by bit during the generation of the LLM.
Also, for the item part, make this in background AFTER completion of first prompt.


## Commands
Launch main.py :    CTRL + MAJ + B

Settings :          CTRL + ,

Fold all :          CTRL + K  ;  CTRL + 0
Unfold all :        CTRL + K  ; CTRL + J
Fold functions :   CTRL + K  ; CTRL + 2

See all shorcuts :  CTRL + K  ; CTRL + S

### Install llama_cpp
CMAKE_ARGS="-DGGML_CUDA=1 -DCMAKE_CUDA_COMPILER=/usr/local/cuda-13.0/bin/nvcc -DCMAKE_CUDA_ARCHITECTURES=75" pip install llama-cpp-python --force-reinstall --no-cache-dir