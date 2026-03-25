# game/script.rpy
# 持续游戏循环 + 生图显示

init python:
    import requests
    import json
    import os
    import time

    SERVER_URL = "http://127.0.0.1:8000"
    GENERATED_IMAGE_PATH = "images/generated/current_scene.png"

    def call_next_scene(player_input, location, characters):
        try:
            resp = requests.post(f"{SERVER_URL}/next_scene", json={
                "player_input": player_input,
                "location": location,
                "characters": characters
            }, timeout=120)
            return resp.json()
        except Exception as e:
            return {
                "narration": f"（连接服务器失败：{e}）",
                "dialogues": [],
                "choices": ["重试"],
                "image_triggered": False
            }

    def save_episode(scene_text, player_choice, characters):
        try:
            requests.post(f"{SERVER_URL}/save_episode", json={
                "scene_text": scene_text,
                "player_choice": player_choice,
                "characters": characters
            }, timeout=30)
        except:
            pass

    def wait_for_image(timeout=60):
        """
        等待新图片生成完毕，返回 True 或 False
        通过轮询 /image_ready 接口实现
        """
        try:
            # 先记录当前图片时间戳
            resp = requests.get(f"{SERVER_URL}/image_ready", timeout=5)
            old_mtime = resp.json().get("mtime", 0)
        except:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = requests.get(f"{SERVER_URL}/image_ready", timeout=5)
                data = resp.json()
                if data.get("ready") and data.get("mtime", 0) > old_mtime:
                    return True
            except:
                pass
            time.sleep(1)
        return False

    def get_character_affection(name):
        try:
            resp = requests.get(f"{SERVER_URL}/character_state/{name}", timeout=10)
            return resp.json().get("affection", 50)
        except:
            return 50


# ─── 游戏开始 ───────────────────────────────

label start:
    $ current_location = "学校图书馆"
    $ current_characters = ["爱丽丝"]
    $ player_choice = "走进图书馆，四处张望"
    $ scene_log = []

    # 主游戏循环
label game_loop:

    # 1. 请求下一段剧情
    $ scene = call_next_scene(player_choice, current_location, current_characters)

    # 2. 等待图片生成（最多等100秒，超时就跳过）
    $ image_ready = wait_for_image(100)

    # 3. 如果图片就绪则显示，否则用纯色背景
    if image_ready and renpy.loadable(GENERATED_IMAGE_PATH):
        scene black
        show expression GENERATED_IMAGE_PATH as scene_bg
    else:
        scene black

    # 4. 显示旁白
    $ narration = scene.get("narration", "")
    if narration:
        narrator "[narration]"

    # 5. 逐行显示对话
    $ dialogues = scene.get("dialogues", [])
    $ idx = 0
    while idx < len(dialogues):
        $ d = dialogues[idx]
        $ speaker = d.get("character", "???")
        $ line = d.get("text", "")
        "[speaker]" "[line]"
        $ idx += 1

    # 6. 记录场景内容
    $ scene_log = [narration] + [d.get("text","") for d in dialogues]
    $ scene_text = " ".join(scene_log)

    # 7. 显示选项
    $ choices = scene.get("choices", ["继续"])
    $ player_choice = choices[0]

    menu:
        "[choices[0]]" if len(choices) > 0:
            $ player_choice = choices[0]
        "[choices[1]]" if len(choices) > 1:
            $ player_choice = choices[1]
        "[choices[2]]" if len(choices) > 2:
            $ player_choice = choices[2]

    # 8. 保存记忆
    $ save_episode(scene_text, player_choice, current_characters)

    # 9. 循环继续
    jump game_loop
