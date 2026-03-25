"""
scene_generator.py - 剧情生成模块
调用 LLM 生成下一段剧情、对话和选项
"""

import json
from dataclasses import dataclass
from memory import GalgameMemory

# ─────────────────────────────────────────────
# 配置常量（在这里统一修改）
# ─────────────────────────────────────────────

LLM_MODEL = "gemma3:4b"   # 修改这里来切换模型，例如 "gemma3:12b"

WORLD_SETTING = """
这是一个发生在现代都市的校园故事。
主角是一名普通高中生，刚转学到新学校。
世界观平静日常，充满温情和轻微的青春感伤。
"""

CHARACTER_SETTINGS = {
    "爱丽丝": "黑发眼镜少女，图书委员，表面冷淡内心温柔，喜欢看推理小说。",
    "小樱": "活泼开朗的橙发少女，社团干部，有点大大咧咧但很关心朋友。"
}


@dataclass
class SceneResult:
    narration: str
    dialogues: list[dict]
    choices: list[str]
    background: str
    character_emotions: dict


class SceneGenerator:
    def __init__(self, memory: GalgameMemory):
        self.memory = memory
        self.llm_client = memory.llm_client

    async def generate(
        self,
        player_input: str,
        location: str,
        characters: list[str]
    ) -> SceneResult:

        context = await self.memory.get_context(
            f"{player_input} {location} {' '.join(characters)}",
            characters
        )

        char_settings = "\n".join([
            f"- {name}：{desc}"
            for name, desc in CHARACTER_SETTINGS.items()
            if name in characters
        ])

        prompt = f"""
你是一个 Galgame 的剧本引擎，请根据以下信息生成下一段剧情。
只输出 JSON，不要有任何多余文字或 markdown。
请生成8~12句角色对话。
【世界观】
{WORLD_SETTING}

【角色设定】
{char_settings}

【记忆与角色状态】
{context}

【当前场景】
地点：{location}
在场角色：{', '.join(characters)}
玩家行动/输入：{player_input}

输出格式：
{{
  "narration": "旁白描述，0~4句话",
  "dialogues": [
    {{"character": "角色名", "text": "对话内容"}},
    {{"character": "角色名", "text": "对话内容"}}
  ],
  "choices": ["选项1", "选项2", "选项3"],
  "background": "英文背景描述，用于生图，例如 school library, warm lighting, bookshelves",
  "character_emotions": {{"角色名": "smile或shy或serious或surprised或neutral之一"}}
}}
"""

        response = await self.llm_client.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.choices[0].message.content
        raw = raw.strip().strip("```json").strip("```").strip()

        try:
            data = json.loads(raw)
        except Exception as e:
            print(f"[SceneGenerator] JSON解析失败: {e}\n原始输出:\n{raw}")
            data = {
                "narration": "（剧情生成出现问题，请重试）",
                "dialogues": [],
                "choices": ["继续", "等待", "离开"],
                "background": "school corridor, daytime",
                "character_emotions": {}
            }

        return SceneResult(
            narration=data.get("narration", ""),
            dialogues=data.get("dialogues", []),
            choices=data.get("choices", []),
            background=data.get("background", ""),
            character_emotions=data.get("character_emotions", {})
        )
