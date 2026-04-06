"""
scene_generator.py - 剧情生成模块
"""

import json
from dataclasses import dataclass, field
from memory import GalgameMemory

# ─────────────────────────────────────────────
# 配置常量
# ─────────────────────────────────────────────

LLM_MODEL = "gemma3:4b"

WORLD_SETTING = """
这是一个发生在现代都市的校园故事。
主角是一名普通高中生，刚转学到新学校。
世界观平静日常，充满温情和轻微的青春感伤。
"""

CHARACTER_SETTINGS = {
    "爱丽丝": "黑发眼镜少女，图书委员，表面冷淡内心温柔，喜欢看推理小说。",
}

# JSON 解析失败时的最大重试次数
JSON_MAX_RETRIES = 2


@dataclass
class SceneResult:
    # lines 是混排列表：
    # {"type": "narration", "text": "..."}
    # {"type": "dialogue", "character": "爱丽丝", "text": "..."}
    lines: list = field(default_factory=list)
    choices: list = field(default_factory=list)
    background: str = ""
    character_emotions: dict = field(default_factory=dict)
    location: str = ""


class SceneGenerator:
    def __init__(self, memory: GalgameMemory):
        self.memory = memory
        self.llm_client = memory.llm_client

    def _build_prompt(self, player_input: str, location: str, characters: list, context: str) -> str:
        char_settings = "\n".join([
            f"- {name}：{desc}"
            for name, desc in CHARACTER_SETTINGS.items()
            if name in characters
        ])

        return f"""
你是一个 Galgame 的剧本引擎，请根据以下信息生成下一段剧情。
只输出 JSON，不要有任何多余文字或 markdown 代码块。

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

【要求】
- lines 是旁白和对话的混排列表，顺序由你决定，要自然合理
- 旁白和对话总计 6~10 条
- 选项只需要 2 个
- 旁白用 type=narration，对话用 type=dialogue 并附带 character 字段

输出格式（严格遵守，只输出这个 JSON）：
{{
  "lines": [
    {{"type": "narration", "text": "旁白内容"}},
    {{"type": "dialogue", "character": "角色名", "text": "对话内容"}},
    {{"type": "narration", "text": "旁白内容"}},
    {{"type": "dialogue", "character": "角色名", "text": "对话内容"}}
  ],
  "choices": ["选项1", "选项2"],
  "background": "英文背景描述，例如 school library, warm lighting, bookshelves",
  "character_emotions": {{"角色名": "smile或shy或serious或surprised或neutral之一"}}
}}
1. 你必须且只能生成一个 JSON 对象。
2. "lines" 数组中只能包含 "narration" 或 "dialogue" 类型的对象。
3. 严禁在 "lines" 内部出现 "choices" 或 "options"。
4. 选项部分必须放在 JSON 的最外层，且只能出现在全文的最末尾。
"""

    async def _call_llm(self, prompt: str) -> str:
        response = await self.llm_client.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.7
        )
        raw = response.choices[0].message.content
        return raw.strip().strip("```json").strip("```").strip()

    async def generate(self, player_input: str, location: str, characters: list) -> SceneResult:

        context = await self.memory.get_context(
            f"{player_input} {location} {' '.join(characters)}",
            characters
        )

        prompt = self._build_prompt(player_input, location, characters, context)

        # ── JSON 解析，失败时最多重试 JSON_MAX_RETRIES 次 ──
        data = None
        last_raw = ""
        last_error = None

        for attempt in range(1 + JSON_MAX_RETRIES):
            if attempt > 0:
                print(f"[SceneGenerator] 第 {attempt} 次重试（共 {JSON_MAX_RETRIES} 次）...")

            try:
                raw = await self._call_llm(prompt)
                last_raw = raw
                data = json.loads(raw)
                if attempt > 0:
                    print(f"[SceneGenerator] 第 {attempt} 次重试成功")
                break   # 解析成功，跳出循环

            except Exception as e:
                last_error = e
                print(
                    f"[SceneGenerator] JSON 解析失败（第 {attempt + 1} 次尝试）: {e}\n"
                    f"原始输出:\n{last_raw}"
                )

        # 全部重试耗尽仍失败，使用兜底数据
        if data is None:
            print(
                f"[SceneGenerator] 已达最大重试次数 ({JSON_MAX_RETRIES})，使用兜底剧情。"
                f"最后一次错误: {last_error}"
            )
            data = {
                "lines": [{"type": "narration", "text": "（剧情生成出现问题，请重试）"}],
                "choices": ["继续", "离开"],
                "background": "school corridor, daytime",
                "character_emotions": {}
            }

        return SceneResult(
            lines=data.get("lines", []),
            choices=data.get("choices", []),
            background=data.get("background", ""),
            character_emotions=data.get("character_emotions", {}),
            location=location
        )
