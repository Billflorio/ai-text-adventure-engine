# AI Book-to-Game Engine

Turn any book into a playable text adventure. Loads books from Project Gutenberg or your own files. All AI runs locally — plug in whatever models you have.

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure your AI models
Edit `config.json` — or launch the app and go to **Settings**.

Minimum to get started (pick one):

**Ollama (local, free):**
```json
"llm": { "backend": "ollama", "model": "llama3.1:8b", "base_url": "http://localhost:11434" }
```

**OpenAI:**
```json
"llm": { "backend": "openai", "model": "gpt-4o", "api_key": "sk-..." }
```

**LM Studio:**
```json
"llm": { "backend": "lmstudio", "model": "your-model-name", "base_url": "http://localhost:1234" }
```

For images, set `"image": { "backend": "none" }` to skip images, or configure Stable Diffusion / DALL-E.

### 3. Run
```bash
python main.py
```
Opens in your browser at `http://localhost:8742`.

---

## How It Works

1. **Load a book** — search Project Gutenberg or upload your own PDF/EPUB/TXT
2. **AI analysis** — the LLM reads the book and extracts characters, locations, plot events
3. **Game generation** — a full text adventure world is built from the source material
4. **Play** — explore the story world, talk to characters, solve puzzles, answer comprehension questions
5. **Images** — if an image backend is configured, each location gets AI-generated scene art

## Content Profiles

Set up profiles for different users/occasions. Control:
- **Content level** (1 = Strictly Clean → 5 = Explicit)
- **Individual dials** for violence, romance, language, religious tone, horror

Example: The same book (e.g. *Lady Chatterley's Lover*) plays very differently on a "Sunday School" profile vs an "Adult" profile.

## Supported Book Sources

- **Project Gutenberg** (~70,000 free public domain books, searchable in-app)
- **Your own files**: PDF, EPUB, TXT

## Supported AI Backends

| LLM | Image Gen |
|-----|-----------|
| Ollama (local) | Stable Diffusion (AUTOMATIC1111) |
| LM Studio (local) | ComfyUI (local) |
| OpenAI (GPT-4o etc.) | DALL-E 3 |
| Anthropic (Claude) | Any OpenAI-compatible |
| Google Gemini | None (text-only mode) |
| Any OpenAI-compatible API | |

---

## Data

All data is stored locally in `data/`:
- `data/books/` — cached downloaded books
- `data/games/` — generated game worlds
- `data/images/` — generated scene art
- `data/saves/` — player save files

Nothing leaves your machine.
