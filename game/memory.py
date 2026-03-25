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

# Windows 异步修复
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ["OPENAI_API_KEY"] = "ollama"
os.environ["OPENAI_BASE_URL"] = "http://localhost:11434/v1"


# ─────────────────────────────────────────────
# 角色情感状态（结构化，独立于图谱存储）
# ─────────────────────────────────────────────

@dataclass
class CharacterState:
    name: str
    affection: int = 50       # 好感度 0~100
    trust: int = 50           # 信任度 0~100
    mood: str = "neutral"     # 当前情绪
    relationship: str = "陌生人"  # 关系标签

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
# 情感状态持久化（存 JSON 文件）
# ─────────────────────────────────────────────

STATE_FILE = "character_states.json"

def load_character_states() -> dict[str, CharacterState]:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {name: CharacterState(**state) for name, state in data.items()}

def save_character_states(states: dict[str, CharacterState]):
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

    async def init(self):
        """初始化 Graphiti 连接"""
        self.llm_client = OpenAIGenericClient(config=LLMConfig(
            api_key="ollama",
            model="gemma3:4b",
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
        # 在独立task中运行，避免FastAPI lifespan的事件循环冲突
        try:
            task = asyncio.ensure_future(self.graphiti.build_indices_and_constraints())
            await asyncio.wait_for(task, timeout=30)
        except asyncio.TimeoutError:
            print("[Memory] 索引建立超时，继续启动（索引可能已存在）")
        except Exception as e:
            print(f"[Memory] 索引建立警告（可忽略）: {e}")
        print("[Memory] 初始化完成")

    async def close(self):
        if self.graphiti:
            await self.graphiti.close()

    # ── 写入记忆 ──────────────────────────────

    async def save_episode(self, scene_text: str, player_choice: str, characters: list[str]):
        return#我加的，暂时不写入记忆了
        """
        一个场景结束后，提取关键事实写入图谱，同时更新角色情感状态
        """
        # 用 LLM 从场景中提取结构化信息
        extract_prompt = f"""
从以下游戏场景中提取关键信息，以 JSON 格式返回，不要有多余文字。

场景内容：
{scene_text}

玩家选择：{player_choice}
在场角色：{', '.join(characters)}

请返回如下格式：
{{
  "event_summary": "一句话总结发生了什么",
  "character_changes": [
    {{
      "name": "角色名",
      "affection_delta": 数字（-10到10，玩家选择对该角色好感度的影响）,
      "trust_delta": 数字（-10到10）,
      "mood": "角色当前情绪（happy/sad/angry/nervous/neutral等）"
    }}
  ]
}}
"""
        response = await self.llm_client.client.chat.completions.create(
            model="gemma3:4b",
            messages=[{"role": "user", "content": extract_prompt}]
        )

        try:
            raw = response.choices[0].message.content
            # 去掉可能的 markdown 代码块
            raw = raw.strip().strip("```json").strip("```").strip()
            extracted = json.loads(raw)
        except Exception as e:
            print(f"[Memory] 提取失败，使用原始文本写入: {e}")
            extracted = {"event_summary": scene_text[:200], "character_changes": []}

        # 写入图谱
        await self.graphiti.add_episode(
            name=f"scene_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            episode_body=extracted["event_summary"],
            source_description="galgame场景",
            reference_time=datetime.now()
        )

        # 更新角色情感状态
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
        print(f"[Memory] 已写入场景记忆：{extracted['event_summary']}")

    # ── 读取记忆 ──────────────────────────────

    async def get_context(self, current_situation: str, characters: list[str]) -> str:
        """
        查询和当前场景相关的记忆，返回格式化的上下文字符串供 LLM 使用
        """
        # 从图谱检索相关事件记忆
        results = await self.graphiti.search(current_situation, num_results=5)

        memory_lines = []
        for res in results:
            fact = res.fact if hasattr(res, 'fact') else str(res)
            time = res.valid_at.strftime('%Y-%m-%d') if hasattr(res, 'valid_at') and res.valid_at else "未知时间"
            memory_lines.append(f"- [{time}] {fact}")

        memory_text = "\n".join(memory_lines) if memory_lines else "（暂无相关记忆）"

        # 拼接角色情感状态
        char_state_lines = []
        for name in characters:
            char = get_or_create_character(self.character_states, name)
            char_state_lines.append(char.to_prompt_text())

        char_state_text = "\n\n".join(char_state_lines) if char_state_lines else "（无角色状态）"

        return f"""【事件记忆】
{memory_text}

【角色状态】
{char_state_text}"""
