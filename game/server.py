"""
server.py - 中间层 FastAPI 服务
"""

import asyncio
import sys
import httpx
import json
import os
import glob
import shutil
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel

from memory import GalgameMemory
from scene_generator import SceneGenerator

if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ─────────────────────────────────────────────
# 配置常量（在这里统一修改）
# ─────────────────────────────────────────────

ENABLE_IMAGE_GENERATION = True          # 生图开关，False 则跳过所有生图逻辑

IMAGE_MODEL     = "counterfeitxl_v25.safetensors"
COMFYUI_URL     = "http://127.0.0.1:8188"
COMFYUI_OUTPUT  = r"C:\Users\Administrator\ComfyUI\output"
RENPY_IMAGE_DIR = r"C:\Users\Administrator\Desktop\test_gal\game\images\generated"

OLLAMA_URL      = "http://localhost:11434"   # Ollama API 地址
LLM_MODEL_NAME  = "gemma3:12b"               # 与 scene_generator.py 里保持一致

# 背景分辨率（横版）→ 1080p
BG_WIDTH  = 1920
BG_HEIGHT = 1080

# 立绘分辨率（竖版，适配 1080p 背景比例）
SPRITE_WIDTH  = 768
SPRITE_HEIGHT = 1280


# ─────────────────────────────────────────────
# 全局状态
# ─────────────────────────────────────────────

memory   = GalgameMemory()
generator: SceneGenerator = None

# 记录最新图片的时间戳，供 /image_ready 接口使用
_latest_bg_mtime:     float = 0.0
_latest_sprite_mtime: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global generator
    if ENABLE_IMAGE_GENERATION:
        os.makedirs(RENPY_IMAGE_DIR, exist_ok=True)
    await memory.init()
    generator = SceneGenerator(memory)
    print("[Server] 启动完成，等待 Ren'Py 连接...")
    yield
    await memory.close()
    print("[Server] 已关闭")

app = FastAPI(lifespan=lifespan)


# ─────────────────────────────────────────────
# 请求/响应模型
# ─────────────────────────────────────────────

class PlayerAction(BaseModel):
    player_input: str
    location: str
    characters: list[str]

class SceneResponse(BaseModel):
    lines: list[dict]
    choices: list[str]
    image_triggered: bool


# ─────────────────────────────────────────────
# 显存管理：Ollama <-> ComfyUI 互斥
# ─────────────────────────────────────────────

async def unload_ollama():
    """让 Ollama 释放显存（keep_alive=0 立即卸载）"""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": LLM_MODEL_NAME, "keep_alive": 0},
                timeout=10.0
            )
        print("[VRAM] Ollama 模型已从显存卸载")
    except Exception as e:
        print(f"[VRAM] Ollama 卸载失败（可忽略）: {e}")


async def unload_comfyui():
    """
    让 ComfyUI 释放显存。
    ComfyUI 没有官方卸载接口，通过 /free 端点（部分版本支持）
    或发送空 interrupt 来尽量释放。
    """
    try:
        async with httpx.AsyncClient() as client:
            # 新版 ComfyUI 支持 /free，旧版会 404 但不影响流程
            resp = await client.post(
                f"{COMFYUI_URL}/free",
                json={"unload_models": True, "free_memory": True},
                timeout=10.0
            )
            if resp.status_code == 200:
                print("[VRAM] ComfyUI 模型已从显存卸载")
            else:
                print(f"[VRAM] ComfyUI /free 返回 {resp.status_code}，跳过卸载")
    except Exception as e:
        print(f"[VRAM] ComfyUI 卸载失败（可忽略）: {e}")


# ─────────────────────────────────────────────
# 生图逻辑
# ─────────────────────────────────────────────

def _build_workflow(positive_prompt: str, negative_prompt: str, width: int, height: int, prefix: str) -> dict:
    """构建 ComfyUI workflow"""
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                "latent_image": ["5", 0], "seed": 0, "steps": 20,
                "cfg": 7, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0
            }
        },
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": IMAGE_MODEL}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": positive_prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": negative_prompt}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}}
    }


async def _send_to_comfyui(workflow: dict):
    async with httpx.AsyncClient() as client:
        await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow}, timeout=10.0)


async def _wait_for_new_file(prefix: str, known_files: set, timeout: int = 120) -> str | None:
    """等待 ComfyUI output 目录出现新的以 prefix 开头的 PNG 文件"""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        files = set(glob.glob(os.path.join(COMFYUI_OUTPUT, f"{prefix}*.png")))
        new_files = files - known_files
        if new_files:
            return max(new_files, key=os.path.getmtime)
        await asyncio.sleep(1)
    return None


async def generate_background(background_desc: str):
    """生成背景图并保存到 Ren'Py 目录"""
    global _latest_bg_mtime
    
    # 清除旧文件以确保更新
    bg_path = os.path.join(RENPY_IMAGE_DIR, "current_bg.png")
    if os.path.exists(bg_path):
        os.remove(bg_path)

    positive = (
        f"masterpiece, best quality, anime background, {background_desc}, "
        f"no people, no characters, scenic, detailed, soft lighting"
    )
    negative = "worst quality, low quality, watermark, text, people, characters, nsfw"

    known = set(glob.glob(os.path.join(COMFYUI_OUTPUT, "bg_*.png")))
    workflow = _build_workflow(positive, negative, BG_WIDTH, BG_HEIGHT, "bg_")

    try:
        await _send_to_comfyui(workflow)
        new_file = await _wait_for_new_file("bg_", known)
        if new_file:
            dest = os.path.join(RENPY_IMAGE_DIR, "current_bg.png")
            shutil.copy2(new_file, dest)
            _latest_bg_mtime = os.path.getmtime(dest)
            
            # 确保文件确实被覆盖
            print(f"[Image] 背景已更新，新文件路径: {dest}")
            print(f"[Image] 背景已就绪")
    except Exception as e:
        print(f"[Image] 背景生成失败: {e}")


async def generate_sprite(character_emotions: dict):
    """生成角色立绘，用 rembg 去背景，保存为透明 PNG"""
    global _latest_sprite_mtime

    if not character_emotions:
        return
        
    # 清除旧文件以确保更新
    sprite_path = os.path.join(RENPY_IMAGE_DIR, "current_sprite.png")
    if os.path.exists(sprite_path):
        os.remove(sprite_path)

    # 取第一个角色生成立绘
    char_name, emotion = next(iter(character_emotions.items()))
    
    # 获取角色设定
    from scene_generator import CHARACTER_SETTINGS
    char_setting = CHARACTER_SETTINGS.get(char_name, "")
    
    positive = (
        f"masterpiece, best quality, anime girl, {char_name}, {char_setting}, {emotion} expression, "
        f"upper body, from waist up, showing arms and hands, detailed clothing, "
        f"simple white background, flat background, detailed eyes, soft lighting"
    )
    negative = "worst quality, low quality, watermark, text, nsfw, complex background, scenery, head only, neck only, floating head, no body, cropped"

    known = set(glob.glob(os.path.join(COMFYUI_OUTPUT, "sprite_*.png")))
    workflow = _build_workflow(positive, negative, SPRITE_WIDTH, SPRITE_HEIGHT, "sprite_")

    try:
        await _send_to_comfyui(workflow)
        new_file = await _wait_for_new_file("sprite_", known)
        if new_file:
            # rembg 去背景
            from rembg import remove
            from PIL import Image
            import io

            with open(new_file, "rb") as f:
                img_data = f.read()

            result = remove(img_data)
            dest = os.path.join(RENPY_IMAGE_DIR, "current_sprite.png")
            with open(dest, "wb") as f:
                f.write(result)

            _latest_sprite_mtime = os.path.getmtime(dest)
            
            # 确保文件确实被覆盖
            print(f"[Image] 立绘已更新，新文件路径: {dest}")
            print(f"[Image] 立绘已就绪（已去背景）")
    except Exception as e:
        print(f"[Image] 立绘生成失败: {e}")


async def trigger_image_generation(background: str, character_emotions: dict):
    """
    生图前先卸载 Ollama，生图完后 Ollama 下次调用自动重新加载。
    背景和立绘并行生成。
    """
    print("[VRAM] 生图前卸载 Ollama 模型...")
    await unload_ollama()

    print("[Image] 开始并行生成背景和立绘...")
    await asyncio.gather(
        generate_background(background),
        generate_sprite(character_emotions)
    )
    print("[Image] 背景和立绘均已生成完毕")


# ─────────────────────────────────────────────
# API 路由
# ─────────────────────────────────────────────

@app.post("/next_scene", response_model=SceneResponse)
async def next_scene(action: PlayerAction):
    # 调用 LLM 前先卸载 ComfyUI 模型，释放显存给 Ollama
    if ENABLE_IMAGE_GENERATION:
        print("[VRAM] LLM 调用前卸载 ComfyUI 模型...")
        await unload_comfyui()

    result = await generator.generate(
        player_input=action.player_input,
        location=action.location,
        characters=action.characters
    )

    if ENABLE_IMAGE_GENERATION:
        # 阻塞等待图片生成完毕，再把文字+图片一起返回给 Ren'Py
        await trigger_image_generation(result.background, result.character_emotions)

    return SceneResponse(
        lines=result.lines,
        choices=result.choices,
        image_triggered=ENABLE_IMAGE_GENERATION
    )


@app.post("/save_episode")
async def save_episode(data: dict):
    await memory.save_episode(
        scene_text=data["scene_text"],
        player_choice=data["player_choice"],
        characters=data["characters"]
    )
    return {"status": "ok"}


@app.get("/character_state/{name}")
async def character_state(name: str):
    from memory import get_or_create_character
    char = get_or_create_character(memory.character_states, name)
    return {
        "name": char.name,
        "affection": char.affection,
        "trust": char.trust,
        "mood": char.mood,
        "relationship": char.relationship
    }


@app.get("/image_ready")
async def image_ready():
    """
    返回背景和立绘的最新时间戳
    Ren'Py 通过比较时间戳来判断新图是否生成完毕
    """
    return {
        "bg_mtime":     _latest_bg_mtime,
        "sprite_mtime": _latest_sprite_mtime,
        "bg_exists":     os.path.exists(os.path.join(RENPY_IMAGE_DIR, "current_bg.png")),
        "sprite_exists": os.path.exists(os.path.join(RENPY_IMAGE_DIR, "current_sprite.png"))
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
