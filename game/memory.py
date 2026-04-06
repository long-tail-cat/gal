"""
memory.py - Galgame 记忆模块
基于 Graphiti + Neo4j 管理角色记忆和剧情事件
"""

import asyncio
import os
import sys
import json
from datetime import datetime
from dataclasses import dataclass, asdict

from graphiti_core import Graphiti
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient, LLMConfig
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.driver.neo4j_driver import Neo4jDriver

if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ["OPENAI_API_KEY"] = "ollama"
os.environ["OPENAI_BASE_URL"] = "http://localhost:11434/v1"

# ─────────────────────────────────────────────
# 角色情感状态
# ─────────────────────────────────────────────

@dataclass
class CharacterState:
    name: str
    affection: int = 50
    trust: int = 50
    mood: str = "neutral"
    relationship: str = "陌生人"

    def to_prompt_text(self) -> str:
        return (
            f"角色：{self.name}\n"
            f"好感度：{self.affection}/100\n"
            f"信任度：{self.trust}/100\n"
            f"当前情绪：{self.mood}\n"
            f"与玩家关系：{self.relationship}"
        )

    def update(self, affection_delta=0, trust_delta=0, mood=None, relationship=None):
        self.affection = max(0, min(100, self.affection + affection_delta))
        self.trust = max(0, min(100, self.trust + trust_delta))
        if mood:
            self.mood = mood
        if relationship:
            self.relationship = relationship


# ─────────────────────────────────────────────
# 情感状态持久化
# ─────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "character_states.json")

def load_character_states() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {name: CharacterState(**state) for name, state in data.items()}

def save_character_states(states: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({name: asdict(s) for name, s in states.items()}, f, ensure_ascii=False, indent=2)

def get_or_create_character(states: dict, name: str) -> CharacterState:
    if name not in states:
        states[name] = CharacterState(name=name)
        save_character_states(states)
    return states[name]


# ─────────────────────────────────────────────
# 记忆管理器
# ─────────────────────────────────────────────

class GalgameMemory:
    def __init__(self):
        self.graphiti: Graphiti = None
        self.llm_client: OpenAIGenericClient = None
        self.character_states = load_character_states()
        # 用于积累对话，达到阈值才写入图谱
        self._pending_lines: list[str] = []
        self._pending_characters: set = set()
        self._flush_threshold = 5  # 每积累5轮对话写入一次

    async def init(self):
        from scene_generator import LLM_MODEL
        self.llm_client = OpenAIGenericClient(config=LLMConfig(
            api_key="ollama",
            model=LLM_MODEL,
            base_url="http://localhost:11434/v1",
            temperature=0.1
        ))
        self.llm_client.client.timeout = 300.0

        embedder = OpenAIEmbedder(config=OpenAIEmbedderConfig(
            api_key="ollama",
            model="nomic-embed-text",
            base_url="http://localhost:11434/v1"
        ))

        neo4j_driver = Neo4jDriver(
            uri="bolt://127.0.0.1:7687",
            user="neo4j",
            password="12345678"
        )

        self.graphiti = Graphiti(
            llm_client=self.llm_client,
            embedder=embedder,
            graph_driver=neo4j_driver
        )
        try:
            task = asyncio.ensure_future(self.graphiti.build_indices_and_constraints())
            await asyncio.wait_for(task, timeout=30)
        except asyncio.TimeoutError:
            print("[Memory] 索引建立超时，继续启动")
        except Exception as e:
            print(f"[Memory] 索引建立警告（可忽略）: {e}")
        print("[Memory] 初始化完成")

    async def close(self):
        # 关闭前把剩余的pending内容写入
        if self._pending_lines:
            await self._flush_to_graph()
        if self.graphiti:
            await self.graphiti.close()

    # ── 写入记忆 ──────────────────────────────

    async def save_episode(self, scene_text: str, player_choice: str, characters: list[str]):
        """
        积累对话内容，达到阈值后批量写入图谱。
        同时立即更新角色情感状态（不等积累）。
        """
        # 先用 LLM 提取角色状态变化（每轮都做）
        extract_prompt = f"""
从以下游戏场景中提取关键信息，以 JSON 格式返回，不要有多余文字。

场景内容：{scene_text}
玩家选择：{player_choice}
在场角色：{', '.join(characters)}

请返回如下格式：
{{
  "event_summary": "一句话总结发生了什么",
  "character_changes": [
    {{
      "name": "角色名",
      "affection_delta": 数字（-10到10）,
      "trust_delta": 数字（-10到10）,
      "mood": "角色当前情绪"
    }}
  ]
}}
"""
        try:
            response = await self.llm_client.client.chat.completions.create(
                model=self.llm_client.config.model,
                messages=[{"role": "user", "content": extract_prompt}]
            )
            raw = response.choices[0].message.content.strip().strip("```json").strip("```").strip()
            extracted = json.loads(raw)
        except Exception as e:
            print(f"[Memory] 提取失败: {e}")
            extracted = {"event_summary": scene_text[:100], "character_changes": []}

        # 更新角色情感状态（立即）
        for change in extracted.get("character_changes", []):
            name = change.get("name")
            if name in characters:
                char = get_or_create_character(self.character_states, name)
                char.update(
                    affection_delta=change.get("affection_delta", 0),
                    trust_delta=change.get("trust_delta", 0),
                    mood=change.get("mood")
                )
        save_character_states(self.character_states)

        # 积累到 pending，按角色分组写入图谱
        summary = extracted.get("event_summary", scene_text[:100])
        self._pending_lines.append(f"[{player_choice}] {summary}")
        for c in characters:
            self._pending_characters.add(c)

        # 达到阈值才写入图谱
        if len(self._pending_lines) >= self._flush_threshold:
            await self._flush_to_graph()

    async def _flush_to_graph(self):
        """把积累的内容按角色写入图谱"""
        if not self._pending_lines:
            return

        combined = "；".join(self._pending_lines)

        # 每个角色写一个 episode，这样图谱里按角色组织
        for char_name in self._pending_characters:
            try:
                await self.graphiti.add_episode(
                    name=f"{char_name}_{datetime.now().strftime('%Y%m%d_%H%M')}",
                    episode_body=f"关于{char_name}的记忆：{combined}",
                    source_description=f"角色{char_name}的互动记录",
                    reference_time=datetime.now()
                )
                print(f"[Memory] 已写入 {char_name} 的记忆（{len(self._pending_lines)}轮）")
            except Exception as e:
                print(f"[Memory] 写入图谱失败: {e}")

        self._pending_lines.clear()
        self._pending_characters.clear()

    # ── 读取记忆 ──────────────────────────────

    async def get_context(self, current_situation: str, characters: list[str]) -> str:
        try:
            results = await self.graphiti.search(current_situation, num_results=5)
            memory_lines = []
            for res in results:
                fact = res.fact if hasattr(res, 'fact') else str(res)
                time = res.valid_at.strftime('%Y-%m-%d') if hasattr(res, 'valid_at') and res.valid_at else "未知时间"
                memory_lines.append(f"- [{time}] {fact}")
            memory_text = "\n".join(memory_lines) if memory_lines else "（暂无相关记忆）"
        except Exception as e:
            print(f"[Memory] 查询记忆失败: {e}")
            memory_text = "（暂无相关记忆）"

        char_state_lines = []
        for name in characters:
            char = get_or_create_character(self.character_states, name)
            char_state_lines.append(char.to_prompt_text())

        char_state_text = "\n\n".join(char_state_lines) if char_state_lines else "（无角色状态）"

        return f"""【事件记忆】
{memory_text}

【角色状态】
{char_state_text}"""
