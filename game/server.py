"""
server.py - 中间层 FastAPI 服务
Ren'Py 通过 HTTP 调用这里，这里再调用 LLM、Graphiti、ComfyUI
"""

import asyncio
import sys
import httpx
import json
import os
import glob
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

IMAGE_MODEL = "counterfeitxl_v25.safetensors"   # 生图模型文件名
COMFYUI_URL = "http://127.0.0.1:8188"
COMFYUI_OUTPUT_DIR = r"C:\Users\Administrator\ComfyUI\output"
RENPY_IMAGE_DIR = r"C:\Users\Administrator\Desktop\test_gal\game\images\generated"


# ─────────────────────────────────────────────
# 全局实例
# ─────────────────────────────────────────────

memory = GalgameMemory()
generator: SceneGenerator = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global generator
    # 确保 Ren'Py 图片目录存在
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
    narration: str
    dialogues: list[dict]
    choices: list[str]
    image_triggered: bool


# ─────────────────────────────────────────────
# ComfyUI 生图
# ─────────────────────────────────────────────

async def trigger_image_generation(background: str, character_emotions: dict):
    char_prompts = ", ".join([
        f"{emotion}" for name, emotion in character_emotions.items()
    ])

    positive_prompt = (
        f"masterpiece, best quality, anime style, {background}, "
        f"1girl, {char_prompts}, soft lighting, detailed eyes, "
        f"ultra-detailed, highres"
    )

    workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
                "seed": 0,
                "steps": 20,
                "cfg": 7,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": 1.0
            }
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": IMAGE_MODEL}
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 768, "batch_size": 1}
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["4", 1], "text": positive_prompt}
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["4", 1],
                "text": "worst quality, low quality, bad anatomy, extra fingers, watermark, text, nsfw, multiple girls"
            }
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "galgame"}
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{COMFYUI_URL}/prompt",
                json={"prompt": workflow},
                timeout=10.0
            )
        print(f"[Image] 已触发生图：{background}")

        # 等待生图完成后复制到 Ren'Py 目录
        asyncio.create_task(wait_and_copy_image())

    except Exception as e:
        print(f"[Image] 生图触发失败: {e}")


async def wait_and_copy_image():
    """
    等待 ComfyUI 生成完成，把最新的图片复制到 Ren'Py images 目录
    文件名固定为 current_scene.png，Ren'Py 始终读取这一个文件
    """
    import shutil

    # 记录触发前的最新文件时间，用于判断新图是否生成完毕
    await asyncio.sleep(3)  # 等待 ComfyUI 开始生成

    for _ in range(60):  # 最多等 60 秒
        files = glob.glob(os.path.join(COMFYUI_OUTPUT_DIR, "galgame*.png"))
        if files:
            latest = max(files, key=os.path.getmtime)
            dest = os.path.join(RENPY_IMAGE_DIR, "current_scene.png")
            try:
                shutil.copy2(latest, dest)
                print(f"[Image] 已复制图片到 Ren'Py: {dest}")
                return
            except Exception as e:
                print(f"[Image] 复制图片失败: {e}")
        await asyncio.sleep(1)

    print("[Image] 等待生图超时")


# ─────────────────────────────────────────────
# API 路由
# ─────────────────────────────────────────────

@app.post("/next_scene", response_model=SceneResponse)
async def next_scene(action: PlayerAction):
    result = await generator.generate(
        player_input=action.player_input,
        location=action.location,
        characters=action.characters
    )

    asyncio.create_task(
        trigger_image_generation(result.background, result.character_emotions)
    )

    return SceneResponse(
        narration=result.narration,
        dialogues=result.dialogues,
        choices=result.choices,
        image_triggered=True
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
    Ren'Py 轮询此接口，检查新图片是否已就绪
    """
    dest = os.path.join(RENPY_IMAGE_DIR, "current_scene.png")
    if os.path.exists(dest):
        mtime = os.path.getmtime(dest)
        return {"ready": True, "mtime": mtime}
    return {"ready": False, "mtime": 0}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
