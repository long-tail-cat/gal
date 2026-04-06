# game/script.rpy

init python:
    import requests
    import json
    import os
    import time

    SERVER_URL       = "http://127.0.0.1:8000"
    BG_IMAGE_PATH    = "images/generated/current_bg.png"
    SPRITE_IMAGE_PATH = "images/generated/current_sprite.png"

    # ─── 角色介绍 & 故事背景（移入 init python，避免裸赋值报错）───
    瑶光的介绍 = """瑶光是一位神秘而优雅的少女，拥有着银白色的长发和明亮的蓝色眼睛。她来自一个遥远的星球，为了寻找失落的宝藏而来到地球。她聪明、勇敢，但也有点孤独。她喜欢阅读古老的书籍，并且对未知的事物充满好奇。"""

    故事背景 = """在一个普通的小镇上，隐藏着一个古老的秘密。传说中，这里曾是宇宙中的一颗璀璨明珠，拥有着无尽的宝藏。然而，随着时间的流逝，这个秘密被遗忘在了历史的尘埃中。直到有一天，一位名叫瑶光的少女从遥远的星球来到这里，她的到来将揭开这个小镇的神秘面纱。

瑶光的任务是找到失落的宝藏，但她需要人类的帮助。玩家将扮演一个普通的学生，在学校图书馆偶遇瑶光，并开始了一段奇妙的冒险旅程。在这个过程中，玩家将帮助瑶光解开谜题，探索未知的世界，并最终找到宝藏。"""

    def show_bg_full():
        """用 renpy.show + what= 在运行时显示全屏背景，无需 renpy.image"""
        d = Transform(
            renpy.display.im.Image(BG_IMAGE_PATH),
            fit="fill",
            xsize=config.screen_width,
            ysize=config.screen_height
        )
        renpy.show("bg_full", what=d, layer="master")

    def call_next_scene(player_input, location, characters):
        try:
            resp = requests.post(f"{SERVER_URL}/next_scene", json={
                "player_input": player_input,
                "location": location,
                "characters": characters
            }, timeout=1000)
            return resp.json()
        except requests.exceptions.RequestException as e:
            return {
                "lines": [{"type": "narration", "text": f"（连接服务器失败：{e}）"}],
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
        except requests.exceptions.RequestException:
            pass

    def get_image_status():
        """获取图片状态和时间戳"""
        try:
            resp = requests.get(f"{SERVER_URL}/image_ready", timeout=5)
            return resp.json()
        except:
            return {"bg_mtime": 0, "sprite_mtime": 0, "bg_exists": False, "sprite_exists": False}

    def wait_for_new_images(old_bg_mtime, old_sprite_mtime, timeout=120):
        """
        等待直到背景和立绘都更新完毕（时间戳比触发前更新），
        或者超时为止。实时轮询，图片好了立刻返回。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = get_image_status()
            bg_ready     = status.get("bg_mtime", 0) > old_bg_mtime and status.get("bg_exists")
            sprite_ready = status.get("sprite_mtime", 0) > old_sprite_mtime and status.get("sprite_exists")
            if bg_ready and sprite_ready:
                return True
            time.sleep(1)
        return False


# ─── 角色设定 ───────────────────────────────
define 瑶光 = Character("瑶光", color="#FFD700")


# ─── 游戏开始 ───────────────────────────────

label start:
    $ current_location   = "学校图书馆"
    $ current_characters = ["瑶光"]
    $ player_choice      = "走进图书馆，四处张望"

label game_loop:

    # 1. 记录触发生图前的时间戳
    python:
        old_status       = get_image_status()
        old_bg_mtime     = old_status.get("bg_mtime", 0)
        old_sprite_mtime = old_status.get("sprite_mtime", 0)

        # 2. 请求下一段剧情（同时后台开始生图）
        scene           = call_next_scene(player_choice, current_location, current_characters)
        lines           = scene.get("lines", [])
        choices         = scene.get("choices", ["继续"])
        image_triggered = scene.get("image_triggered", False)

        # 3. 暂存所有待播放文字（不立即显示）
        pending_lines = []
        for line in lines:
            ltype = line.get("type", "")
            text  = line.get("text", "")
            if ltype == "narration":
                pending_lines.append(("narration", None, text))
            elif ltype == "dialogue":
                speaker = line.get("character", "???")
                pending_lines.append(("dialogue", speaker, text))

    # 4. 等待图片就绪并显示
    if image_triggered:
        python:
            images_ready = wait_for_new_images(old_bg_mtime, old_sprite_mtime, timeout=120)

        if images_ready:
            # 先显示背景和立绘
            if renpy.loadable(BG_IMAGE_PATH):
                $ show_bg_full()
            if renpy.loadable(SPRITE_IMAGE_PATH):
                show expression SPRITE_IMAGE_PATH as sprite at center

            # 再逐条播放暂存的文字
            python:
                i = 0
                len_pending = len(pending_lines)
                while i < len_pending:
                    line_type, speaker, text = pending_lines[i]
                    if line_type == "narration":
                        renpy.say(None, text)
                    elif line_type == "dialogue":
                        renpy.say(speaker, text)
                    i += 1
        else:
            scene black

    # 5. 显示选项
    $ player_choice = choices[0]
    menu:
        "[choices[0]]" if len(choices) > 0:
            $ player_choice = choices[0]
        "[choices[1]]" if len(choices) > 1:
            $ player_choice = choices[1]

    # 6. 保存记忆
    python:
        scene_texts = []
        for line_type, speaker, text in pending_lines:
            if line_type == "narration":
                scene_texts.append(text)
            elif line_type == "dialogue":
                scene_texts.append(f"{speaker}: {text}")
        scene_text = " ".join(scene_texts)
        save_episode(scene_text, player_choice, current_characters)

    # 7. 循环
    jump game_loop
