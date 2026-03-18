# game/script.rpy
# Ren'Py 调用中间层的示例脚本

init python:
    import requests
    import json
    import os

    SERVER_URL = "http://127.0.0.1:8000"

    def call_next_scene(player_input, location, characters):
        """请求下一段剧情"""
        try:
            resp = requests.post(f"{SERVER_URL}/next_scene", json={
                "player_input": player_input,
                "location": location,
                "characters": characters
            }, timeout=60)
            return resp.json()
        except Exception as e:
            return {
                "narration": f"（连接服务器失败：{e}）",
                "dialogues": [],
                "choices": ["重试", "跳过"],
                "image_triggered": False
            }

    def save_episode(scene_text, player_choice, characters):
        """保存场景记忆"""
        try:
            requests.post(f"{SERVER_URL}/save_episode", json={
                "scene_text": scene_text,
                "player_choice": player_choice,
                "characters": characters
            }, timeout=30)
        except:
            pass

    def get_character_affection(name):
        """获取角色好感度"""
        try:
            resp = requests.get(f"{SERVER_URL}/character_state/{name}", timeout=10)
            return resp.json().get("affection", 50)
        except:
            return 50

# ─── 游戏开始 ───────────────────────────────

label start:

    # 初始场景：图书馆遇到爱丽丝
    $ current_location = "学校图书馆"
    $ current_characters = ["爱丽丝"]
    $ scene_log = []

    # 请求第一段剧情
    $ scene = call_next_scene("走进图书馆，四处张望", current_location, current_characters)

    # 显示旁白
    narrator "[scene['narration']]"

    # 显示对话
    $ dialogues = scene.get("dialogues", [])
    $ i = 0
    while i < len(dialogues):
        $ d = dialogues[i]
        $ speaker = d.get("character", "???")
        $ line = d.get("text", "")
        "[speaker]" "[line]"
        $ i += 1

    # 记录本场景内容用于写入记忆
    $ scene_log.append(scene['narration'])

    # 显示选项
    $ choices = scene.get("choices", ["继续"])
    menu:
        "[choices[0]]" if len(choices) > 0:
            $ player_choice = choices[0]
        "[choices[1]]" if len(choices) > 1:
            $ player_choice = choices[1]
        "[choices[2]]" if len(choices) > 2:
            $ player_choice = choices[2]

    # 保存记忆
    $ save_episode(
        scene_text=" ".join(scene_log),
        player_choice=player_choice,
        characters=current_characters
    )

    # 根据选择生成下一段剧情
    $ scene = call_next_scene(player_choice, current_location, current_characters)
    narrator "[scene['narration']]"

    $ dialogues = scene.get("dialogues", [])
    $ i = 0
    while i < len(dialogues):
        $ d = dialogues[i]
        $ speaker = d.get("character", "???")
        $ line = d.get("text", "")
        "[speaker]" "[line]"
        $ i += 1

    # 查询好感度并显示
    $ affection = get_character_affection("爱丽丝")
    "（爱丽丝好感度：[affection]/100）"

    return
