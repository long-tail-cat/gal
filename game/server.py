"""
server.py - 中间层 FastAPI 服务
Ren'Py 通过 HTTP 调用这里，这里再调用 LLM、Graphiti、ComfyUI
"""

import asyncio
import sys
import httpx
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel

from memory import GalgameMemory
from scene_generator import SceneGenerator

if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ─────────────────────────────────────────────
# 全局实例
# ─────────────────────────────────────────────

memory = GalgameMemory()
generator: SceneGenerator = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global generator
    await memory.init()
    generator = SceneGenerator(memory)
    print("[Server] 启动完成，等待 Ren'Py 连接...")
    yield
    await memory.close()
    print("[Server] 已关闭")

app = FastAPI(lifespan=lifespan)

COMFYUI_URL = "http://127.0.0.1:8188"


# ─────────────────────────────────────────────
# 请求/响应模型
# ─────────────────────────────────────────────

class PlayerAction(BaseModel):
    player_input: str        # 玩家输入或选择
    location: str            # 当前地点
    characters: list[str]    # 在场角色

class SceneResponse(BaseModel):
    narration: str
    dialogues: list[dict]
    choices: list[str]
    image_triggered: bool    # 是否已触发生图


# ─────────────────────────────────────────────
# ComfyUI 生图（异步触发，不阻塞剧情返回）
# ─────────────────────────────────────────────

async def trigger_image_generation(background: str, character_emotions: dict):
    """
    向 ComfyUI 发送生图请求
    这里使用简化的 prompt，你可以根据需要扩展 workflow
    """
    # 拼接角色表情到 prompt
    char_prompts = ", ".join([
        f"{name} {emotion}" for name, emotion in character_emotions.items()
    ])

    positive_prompt = (
        f"masterpiece, best quality, anime style, {background}, "
        f"2girls, cat ears, {char_prompts}, soft lighting, detailed"
    )

    # ComfyUI API 的简化 workflow（文生图）
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
            "inputs": {"ckpt_name": "counterfeitV30_v30.safetensors"}
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
                "text": "worst quality, low quality, bad anatomy, extra fingers, watermark, text, nsfw"
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
            await client.post(
                f"{COMFYUI_URL}/prompt",
                json={"prompt": workflow},
                timeout=10.0
            )
        print(f"[Image] 已触发生图：{background}")
    except Exception as e:
        print(f"[Image] 生图触发失败: {e}")


# ─────────────────────────────────────────────
# API 路由
# ─────────────────────────────────────────────

@app.post("/next_scene", response_model=SceneResponse)
async def next_scene(action: PlayerAction):
    """
    Ren'Py 调用此接口获取下一段剧情
    """
    # 生成剧情
    result = await generator.generate(
        player_input=action.player_input,
        location=action.location,
        characters=action.characters
    )

    # 异步触发生图（不等待，不阻塞）
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
    """
    场景结束后，Ren'Py 调用此接口保存记忆
    """
    await memory.save_episode(
        scene_text=data["scene_text"],
        player_choice=data["player_choice"],
        characters=data["characters"]
    )
    return {"status": "ok"}


@app.get("/character_state/{name}")
async def character_state(name: str):
    """
    查询某个角色当前状态（好感度等）
    """
    from memory import get_or_create_character
    char = get_or_create_character(memory.character_states, name)
    return {
        "name": char.name,
        "affection": char.affection,
        "trust": char.trust,
        "mood": char.mood,
        "relationship": char.relationship
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


# ─────────────────────────────────────────────
# 启动
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
