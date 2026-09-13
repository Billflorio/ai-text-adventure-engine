"""
ui/app.py

FastAPI application — local-only web server for the AI Book-to-Game Engine.
All routes serve localhost only (enforced by main.py binding to 127.0.0.1).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.parent
_data_dir_env = os.environ.get("AITEXTGAME_DATA_DIR")
DATA_DIR = Path(_data_dir_env) if _data_dir_env else BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"
if not CONFIG_PATH.exists() and (BASE_DIR / "config.json").exists():
    import shutil
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BASE_DIR / "config.json", CONFIG_PATH)

app = FastAPI(title="AI Book-to-Game Engine", docs_url=None, redoc_url=None)

templates = Jinja2Templates(directory=str(BASE_DIR / "ui" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "ui" / "static")), name="static")
app.mount("/data/images", StaticFiles(directory=str(DATA_DIR / "images")), name="images")


def get_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def get_router():
    """Lazy-load ModelRouter with current config."""
    from ai.model_router import ModelRouter
    return ModelRouter(get_config()["llm"])


def get_image_router():
    """Lazy-load ImageRouter with current config."""
    from ai.image_router import ImageRouter
    return ImageRouter(get_config()["image"])


def get_active_profile():
    """Return active ContentProfile."""
    from engine.content_profile import ContentProfile
    cfg = get_config()
    active = cfg["profiles"]["active"]
    profile_dict = cfg["profiles"]["users"][active]
    return ContentProfile(profile_dict)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Main library / home screen."""
    config = get_config()
    active_profile = config["profiles"]["active"]
    return templates.TemplateResponse(request, "library.html", context={"request": request,
        "active_profile": active_profile,
        "profiles": list(config["profiles"]["users"].keys())})


@app.get("/game/{book_id}", response_class=HTMLResponse)
async def game_view(request: Request, book_id: str):
    """Main game screen."""
    from engine.game_state import GameStateManager, GameWorld
    from ai.game_generator import load_game_world

    world = load_game_world(DATA_DIR / "games", book_id)
    if not world:
        raise HTTPException(status_code=404, detail=f"Game world not found for book_id {book_id}. Please generate first.")

    gsm = GameStateManager(DATA_DIR / "saves")
    try:
        save = gsm.load(slot=book_id)
    except FileNotFoundError:
        if not world.locations:
            raise HTTPException(status_code=500, detail="Game generation failed or timed out. No locations were generated. Please delete from library and try again.")
        save = gsm.new_game(world, list(world.locations.keys())[0], get_config()["profiles"]["active"])
        gsm.save(save, slot=book_id)

    config = get_config()
    return templates.TemplateResponse(request, "index.html", context={"request": request,
        "book_id": book_id,
        "world": world,
        "save": save,
        "active_profile": config["profiles"]["active"]})


@app.get("/settings", response_class=HTMLResponse)
async def settings_view(request: Request):
    config = get_config()
    return templates.TemplateResponse(request, "settings.html", {"request": request,
        "config": config})


@app.get("/profiles", response_class=HTMLResponse)
async def profiles_view(request: Request):
    config = get_config()
    return templates.TemplateResponse(request, "profile_setup.html", {"request": request,
        "config": config,
        "profiles": config["profiles"]["users"],
        "active": config["profiles"]["active"]})


# ---------------------------------------------------------------------------
# API — Gutenberg
# ---------------------------------------------------------------------------

@app.get("/api/gutenberg/search")
async def gutenberg_search(q: str = "", topic: str = "", page: int = 1):
    from loader.gutenberg import search_books
    try:
        results = search_books(query=q, topic=topic or None, page=page)
        return JSONResponse(results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


GENERATION_JOBS = {}

@app.get("/api/library/status/{job_id}")
async def get_generation_status(job_id: str):
    if job_id not in GENERATION_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(GENERATION_JOBS[job_id])

def _background_generate_game(job_id: str, book_id: str, text: str, known_title: str, known_author: str):
    from ai.extractor import extract_story_bible, save_story_bible
    from ai.game_generator import generate_game_world, save_game_world
    
    try:
        router = get_router()
        profile = get_active_profile()

        def log_progress(step, current, total):
            logger.info("[%s] %s (%d/%d)", known_title or book_id, step, current, total)
            GENERATION_JOBS[job_id]["message"] = step
            GENERATION_JOBS[job_id]["progress"] = current
            GENERATION_JOBS[job_id]["total"] = total

        bible = extract_story_bible(
            text, router, profile,
            known_title=known_title, known_author=known_author,
            progress_callback=log_progress,
        )
        save_story_bible(bible, DATA_DIR / "games", str(book_id))

        world = generate_game_world(bible, router, profile, progress_callback=log_progress)
        save_game_world(world, DATA_DIR / "games", str(book_id))
        
        GENERATION_JOBS[job_id]["status"] = "done"
        GENERATION_JOBS[job_id]["title"] = world.book_title
        GENERATION_JOBS[job_id]["book_id"] = str(book_id)
        
    except Exception as e:
        logger.error("Generation failed: %s", e, exc_info=True)
        GENERATION_JOBS[job_id]["status"] = "error"
        GENERATION_JOBS[job_id]["error"] = str(e)


@app.post("/api/gutenberg/load/{book_id}")
async def gutenberg_load(book_id: int, background_tasks: BackgroundTasks):
    """Download a Gutenberg book and generate its game world in background."""
    from loader.gutenberg import download_book_text, get_book_metadata
    
    meta = get_book_metadata(book_id)
    text = download_book_text(book_id, DATA_DIR / "books")
    
    title = meta.get("title", "")
    authors = meta.get("authors", [{}])
    author = authors[0].get("name", "") if authors else ""
    
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    GENERATION_JOBS[job_id] = {
        "status": "generating", "progress": 0, "total": 0, "message": "Starting generation...",
        "book_id": str(book_id), "title": title
    }
    background_tasks.add_task(_background_generate_game, job_id, str(book_id), text, title, author)
    return JSONResponse({"status": "generating", "job_id": job_id})


# ---------------------------------------------------------------------------
# API — File Upload
# ---------------------------------------------------------------------------

@app.post("/api/library/upload")
async def upload_book(background_tasks: BackgroundTasks, book: UploadFile = File(...)):
    """Upload a user's own book file and generate a game world in background."""
    from loader.file_loader import load_file, SUPPORTED_EXTENSIONS
    
    suffix = Path(book.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    # Save upload temporarily
    book_id = f"upload_{uuid.uuid4().hex[:8]}"
    tmp_path = DATA_DIR / "books" / f"{book_id}{suffix}"
    content = await book.read()
    tmp_path.write_bytes(content)

    text = load_file(tmp_path)
    
    filename = book.filename
    try:
        filename = filename.encode('latin-1').decode('utf-8')
    except UnicodeError:
        pass
    
    known_title = Path(filename).stem
    
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    GENERATION_JOBS[job_id] = {
        "status": "generating", "progress": 0, "total": 0, "message": "Starting generation...",
        "book_id": book_id, "title": known_title
    }
    background_tasks.add_task(_background_generate_game, job_id, book_id, text, known_title, "")
    return JSONResponse({"status": "generating", "job_id": job_id})


# ---------------------------------------------------------------------------
# API — Game Actions
# ---------------------------------------------------------------------------

def _background_generate_image(book_id: str, loc_id: str):
    from ai.game_generator import load_game_world, save_game_world
    from ai.image_generator import generate_location_image
    
    world = load_game_world(DATA_DIR / "games", book_id)
    if not world or loc_id not in world.locations: return
    
    loc = world.locations[loc_id]
    if loc.image_path:
        # It's already in the pristine world, just sync it to the save file
        from engine.game_state import GameStateManager
        gsm = GameStateManager(DATA_DIR / "saves")
        try:
            save = gsm.load(slot=book_id)
            if loc_id in save.world.locations and not save.world.locations[loc_id].image_path:
                save.world.locations[loc_id].image_path = loc.image_path
                gsm.save(save, slot=book_id)
        except FileNotFoundError:
            pass
        return
    
    config = get_config()
    if config["image"]["backend"] == "none": return
    
    from ai.image_router import ImageRouter
    router = ImageRouter(config["image"])
    
    try:
        path = generate_location_image(
            location_id=loc_id,
            location_name=loc.name,
            location_description=loc.description,
            book_title=world.book_title,
            tone="adventurous",
            router=router,
            profile=get_active_profile(),
            images_dir=DATA_DIR / "images"
        )
    except Exception as e:
        print(f"Background image generation failed: {e}")
        path = None
    if path:
        loc.image_path = str(path)
        save_game_world(world, DATA_DIR / "games", book_id)
        # Also update the active save file so the user sees it!
        from engine.game_state import GameStateManager
        gsm = GameStateManager(DATA_DIR / "saves")
        try:
            save = gsm.load(slot=book_id)
            if loc_id in save.world.locations:
                save.world.locations[loc_id].image_path = str(path)
                gsm.save(save, slot=book_id)
        except FileNotFoundError:
            pass

def _build_minimap(world, current_loc):
    minimap = {}
    
    # Grid directions
    grid_dirs = ["north", "south", "east", "west"]
    
    for d in grid_dirs:
        if d in current_loc.exits:
            dest_id = current_loc.exits[d]
            dest = world.locations[dest_id]
            minimap[d] = {
                "exists": True,
                "name": dest.name if dest.visited else "???",
                "visited": dest.visited
            }
        else:
            minimap[d] = {"exists": False}
            
    # Vertical exits handled separately
    vert_exits = []
    if "up" in current_loc.exits: vert_exits.append("up")
    if "down" in current_loc.exits: vert_exits.append("down")
    minimap["vertical"] = vert_exits
    
    return minimap

@app.get("/api/game/{book_id}/state")
async def game_state(book_id: str, background_tasks: BackgroundTasks):
    """Return the current game state for a given book_id."""
    from engine.game_state import GameStateManager
    gsm = GameStateManager(DATA_DIR / "saves")
    try:
        save = gsm.load(slot=book_id)
        world = save.world
    except FileNotFoundError:
        from ai.game_generator import load_game_world
        world = load_game_world(DATA_DIR / "games", book_id)
        if not world:
            raise HTTPException(status_code=404, detail="World not found")
        save = gsm.new_game(world, list(world.locations.keys())[0], get_config()["profiles"]["active"])
        gsm.save(save, slot=book_id)

    loc = world.locations[save.player.current_location_id]
    chars_here = [
        world.characters[c_id].name
        for c_id in loc.characters_present
        if c_id in world.characters
    ]
    image_path = loc.image_path
    image_generating = False
    if not image_path and get_config()["image"]["backend"] != "none":
        image_generating = True
        background_tasks.add_task(_background_generate_image, book_id, loc.id)

    return JSONResponse({
        "text": f"**{world.book_title}**\n\n{world.story_summary}",
        "location_name": loc.name,
        "book_title": world.book_title,
        "exits": list(loc.exits.keys()),
        "minimap": _build_minimap(world, loc),
        "characters": chars_here,
        "items_here": [i.replace('_', ' ') for i in loc.items_present],
        "image_url": f"/data/images/{Path(image_path).name}" if image_path else None,
        "image_generating": image_generating,
        "inventory": [i.name for i in save.player.inventory],
        "score": save.player.score,
        "moves": save.player.move_count,
    })


@app.post("/api/game/{book_id}/action")
async def game_action(book_id: str, request: Request, background_tasks: BackgroundTasks):
    """Process a player command and return updated game state + response."""
    from engine.parser import parse
    from engine.game_state import GameStateManager
    body = await request.json()
    raw_input = body.get("command", body.get("input", "")).strip()

    gsm = GameStateManager(DATA_DIR / "saves")
    save = gsm.load(slot=book_id)
    world = save.world

    cmd = parse(raw_input)
    router = get_router()
    profile = get_active_profile()
    
    from engine.game_master import GameMaster
    game_master = GameMaster(router, profile)

    response_text = ""
    current_loc = world.locations[save.player.current_location_id]

    blocking_obstacle = next(
        (obs for obs in world.obstacles.values()
         if obs.location_id == current_loc.id and not obs.passed),
        None
    )

    if cmd["verb"] == "go":
        direction = cmd["noun"]
        if direction in current_loc.exits:
            dest_id = current_loc.exits[direction]
            new_loc = world.locations[dest_id]
            
            if blocking_obstacle and not new_loc.visited:
                response_text = f"You can't go that way yet.\n\n{blocking_obstacle.obstacle_description}"
            else:
                save.player.current_location_id = dest_id
                new_loc.visited = True
                response_text = f"You go {direction}.\n\n{new_loc.description}"
            # Show obstacle if present in new room
            new_obs = next(
                (obs for obs in world.obstacles.values()
                 if obs.location_id == dest_id and not obs.passed),
                None
            )
            if new_obs:
                response_text += f"\n\n**Obstacle:** {new_obs.obstacle_description}"
        else:
            response_text = "You can't go that way."

    elif cmd["verb"] == "inventory":
        if save.player.inventory:
            items = ", ".join(i.name for i in save.player.inventory)
            response_text = f"You are carrying: {items}."
        else:
            response_text = "You aren't carrying anything."

    elif cmd["verb"] == "help":
        from engine.parser import HELP_TEXT
        response_text = HELP_TEXT

    elif cmd["verb"] == "save":
        gsm.save(save, slot=book_id)
        response_text = "Game saved."

    elif cmd["verb"] == "quit":
        gsm.save(save, slot=book_id)
        response_text = "Game saved. Goodbye!"
        
    elif cmd["verb"] == "cheat":
        if blocking_obstacle:
            blocking_obstacle.passed = True
            save.player.obstacles_passed.append(blocking_obstacle.id)
            response_text = f"Cheat activated! You magically bypass: {blocking_obstacle.obstacle_description}"
        else:
            response_text = "There is no active obstacle in this room to skip."

    elif cmd["verb"] == "take":
        item_name = cmd["noun"]
        matching = []
        for i_id in current_loc.items_present:
            real_item = world.items.get(i_id)
            if real_item and item_name in real_item.name.lower():
                matching.append(i_id)
            elif item_name in i_id.lower().replace('_', ' '):
                matching.append(i_id)
                
        if matching:
            item_id = matching[0]
            current_loc.items_present.remove(item_id)
            real_item = world.items.get(item_id)
            if real_item:
                save.player.inventory.append(real_item)
                display_name = real_item.name
            else:
                from engine.game_state import InventoryItem
                display_name = item_id.replace("_", " ").title()
                save.player.inventory.append(InventoryItem(
                    id=item_id, name=display_name, description="", from_book=True
                ))
            response_text = f"You pick up the {display_name}."
        else:
            response_text = "You don't see that here."

    elif cmd["verb"] in ("look", "talk", "use", "unknown"):
        # Let the AI Dungeon Master handle this action!
        obs_data = blocking_obstacle.model_dump() if blocking_obstacle else None
        inventory_data = [i.model_dump() for i in save.player.inventory]
        
        passed, narrative, mutations = await game_master.evaluate_action(
            raw_input, current_loc.description, obs_data, inventory_data, world
        )
        
        if passed and blocking_obstacle:
            blocking_obstacle.passed = True
            save.player.obstacles_passed.append(blocking_obstacle.id)
            save.player.score += 25
            
        for mutation in mutations:
            if mutation.startswith("remove_item:"):
                item_name = mutation.split("remove_item:")[1].strip().lower()
                save.player.inventory = [i for i in save.player.inventory if item_name not in i.name.lower()]
            elif mutation.startswith("add_item:"):
                item_name = mutation.split("add_item:")[1].strip()
                from engine.game_state import InventoryItem
                save.player.inventory.append(InventoryItem(
                    id=item_name.replace(" ", "_").lower(), name=item_name, description="", from_book=False
                ))

        response_text = narrative

    save.updated_at = datetime.utcnow().isoformat()
    gsm.save(save, slot=book_id)

    # Build location snapshot for UI
    loc = world.locations[save.player.current_location_id]
    chars_here = [
        world.characters[c_id].name
        for c_id in loc.characters_present
        if c_id in world.characters
    ]
    image_path = loc.image_path  # may be None
    image_generating = False
    if not image_path and get_config()["image"]["backend"] != "none":
        image_generating = True
        background_tasks.add_task(_background_generate_image, book_id, loc.id)

    return JSONResponse({
        "text": response_text,
        "location_name": loc.name,
        "book_title": world.book_title,
        "exits": list(loc.exits.keys()),
        "minimap": _build_minimap(world, loc),
        "characters": chars_here,
        "items_here": [i.replace('_', ' ') for i in loc.items_present],
        "image_url": f"/data/images/{Path(image_path).name}" if image_path else None,
        "image_generating": image_generating,
        "inventory": [i.name for i in save.player.inventory],
        "score": save.player.score,
        "moves": save.player.move_count,
    })


# ---------------------------------------------------------------------------
# API — Settings
# ---------------------------------------------------------------------------

@app.post("/api/settings/save")
async def settings_save_llm(request: Request):
    body = await request.json()
    config = get_config()
    config["llm"].update(body)
    save_config(config)
    return JSONResponse({"status": "ok"})

@app.post("/api/settings/save-image")
async def settings_save_image(request: Request):
    body = await request.json()
    config = get_config()
    config["image"].update(body)
    save_config(config)
    return JSONResponse({"status": "ok"})


@app.post("/api/settings/test-llm")
async def test_llm(request: Request):
    from ai.model_router import ModelRouter
    try:
        body = await request.json()
        # Merge with existing to keep unchanged fields if any, but body takes precedence
        config = get_config()["llm"]
        config.update(body)
        router = ModelRouter(config)
        ok, msg = router.test_connection()
        return JSONResponse({"ok": ok, "message": msg})
    except Exception as e:
        return JSONResponse({"ok": False, "message": str(e)})


@app.post("/api/settings/test-image")
async def test_image(request: Request):
    from ai.image_router import ImageRouter
    try:
        body = await request.json()
        config = get_config().get("image", {})
        config.update(body)
        router = ImageRouter(config)
        ok, msg = router.test_connection()
        return JSONResponse({"ok": ok, "message": msg})
    except Exception as e:
        return JSONResponse({"ok": False, "message": str(e)})


# ---------------------------------------------------------------------------
# API — Profiles
# ---------------------------------------------------------------------------

@app.get("/api/profiles")
async def profile_list():
    config = get_config()
    # Return profiles as an array of objects
    users = config["profiles"]["users"]
    profiles_arr = []
    for name, p in users.items():
        p_copy = p.copy()
        p_copy["name"] = name
        p_copy["id"] = name  # Frontend expects id
        profiles_arr.append(p_copy)
        
    return JSONResponse({
        "profiles": profiles_arr,
        "active": config["profiles"]["active"]
    })

@app.get("/api/profiles/dial-options")
async def profile_dial_options(level: int = 2):
    """Return the allowed dial values for a given content level."""
    from engine.content_profile import ContentProfile
    constraints = ContentProfile.get_dial_constraints(level)
    return JSONResponse({"options": constraints})

@app.post("/api/profiles/save")
async def profile_save(request: Request):
    body = await request.json()
    config = get_config()
    name = body.get("name", "New Profile")
    
    # The body IS the profile dict
    config["profiles"]["users"][name] = body
    save_config(config)
    return JSONResponse({"status": "ok"})


@app.post("/api/profiles/activate")
async def profile_activate(request: Request):
    body = await request.json()
    config = get_config()
    name = body["name"]
    if name not in config["profiles"]["users"]:
        raise HTTPException(status_code=404, detail="Profile not found")
    config["profiles"]["active"] = name
    save_config(config)
    return JSONResponse({"status": "ok"})


@app.delete("/api/profiles/{name}")
async def profile_delete(name: str):
    config = get_config()
    if name == config["profiles"]["active"]:
        raise HTTPException(status_code=400, detail="Cannot delete the active profile")
    if name not in config["profiles"]["users"]:
        raise HTTPException(status_code=404, detail="Profile not found")
    del config["profiles"]["users"][name]
    save_config(config)
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Static data
# ---------------------------------------------------------------------------

@app.get("/api/library")
async def get_library():
    """List all generated game worlds on disk."""
    games_dir = DATA_DIR / "games"
    worlds = []
    for f in games_dir.glob("*_world.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            book_id = f.stem.replace("_world", "")
            worlds.append({
                "id": book_id,
                "title": data.get("book_title", book_id),
                "author": data.get("book_author", ""),
            })
        except Exception:
            pass
    return JSONResponse({"games": worlds})


@app.delete("/api/library/{book_id}")
async def delete_game(book_id: str):
    """Delete a generated game and its save file."""
    games_dir = DATA_DIR / "games"
    saves_dir = DATA_DIR / "saves"
    
    world_file = games_dir / f"{book_id}_world.json"
    save_file = saves_dir / f"{book_id}.json"
    
    deleted_any = False
    if world_file.exists():
        world_file.unlink()
        deleted_any = True
    if save_file.exists():
        save_file.unlink()
        deleted_any = True
        
    if deleted_any:
        return JSONResponse({"status": "ok"})
    else:
        raise HTTPException(status_code=404, detail="Game not found")


@app.post("/api/library/{book_id}/restart")
async def restart_game(book_id: str):
    """Delete just the save file to start over from the generated map."""
    saves_dir = DATA_DIR / "saves"
    save_file = saves_dir / f"{book_id}.json"
    
    if save_file.exists():
        save_file.unlink()
        
    return JSONResponse({"status": "ok"})
