# AI Book-to-Game Engine

Turn any book into a playable text adventure! Search thousands of books from Project Gutenberg or upload your own files, and the AI will analyze the story to build a fully playable world.

## How to Install (For Players)

You do **not** need to be a programmer or install Python to play this!

1. Go to the **[Releases page](https://github.com/Billflorio/ai-text-adventure-engine/releases)**.
2. Download the latest `AI Text Adventure Setup.exe`.
3. Double-click to install and run the app. It will open like a normal desktop application.

## Setting up the AI (Required)

To make the game work, it needs an "AI Brain" (LLM). You have two choices: use a free local AI, or use a paid cloud AI (like OpenAI).

### Option A: Free Local AI (Recommended)
If you have a decent computer and want everything to run 100% locally and privately:
1. Download and install [Ollama](https://ollama.com/).
2. Open your command prompt/terminal and run: `ollama run qwen2.5-coder:7b` (This will download the AI model — it may take a few minutes).
3. Keep Ollama running in the background.
4. Open the AI Text Adventure App, go to **Settings**, and select **Ollama** as your LLM Backend.

### Option B: Cloud AI (OpenAI, Anthropic, Gemini)
If you prefer to use an existing API key:
1. Open the AI Text Adventure App and go to **Settings**.
2. Select your provider (e.g., OpenAI).
3. Paste your API Key in the box provided.

## (Optional) Setting up Image Generation

If you want the game to automatically generate beautiful scene art for every location in your story, you need an image generator:
* **Cloud:** You can use DALL-E 3 by putting in an OpenAI API key.
* **Local:** If you have a strong graphics card (GPU), you can install [ComfyUI](https://github.com/comfyanonymous/ComfyUI). Make sure ComfyUI is running in the background before you start generating a game!

## How It Works

1. **Load a book** — Search Project Gutenberg or upload your own PDF/EPUB/TXT.
2. **AI analysis** — The engine reads the book and extracts characters, locations, and plot events.
3. **Game generation** — A full text adventure world is built from the source material.
4. **Play** — Explore the story world, talk to characters, solve puzzles, and answer comprehension questions.
5. **Images** — If an image backend is configured, each location gets AI-generated scene art.

## Content Profiles

Parents and teachers can set up profiles to control the experience:
- **Content level** (1 = Strictly Clean → 5 = Explicit)
- **Individual dials** for violence, romance, language, religious tone, and horror.

For example, the exact same book plays very differently on a "Sunday School" profile versus an "Adult" profile!

---

### For Developers

If you want to run the engine from source:
```bash
git clone https://github.com/Billflorio/ai-text-adventure-engine.git
cd ai-text-adventure-engine
pip install -r requirements.txt
python main.py
```
