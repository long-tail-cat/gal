## loading_screen.rpy

# 1. 先定义动画变换（放在 screen 外部，确保语法兼容性）
transform loading_spinner_rotate:
    anchor (0.5, 0.5)
    rotate_pad False
    subpixel True
    linear 1.0 rotate 360
    repeat

# 2. 定义 Loading 界面
screen loading_screen():
    zorder 100
    modal True

    # 背景遮罩
    add Solid("#000000bb")

    # 如果数据准备好了，自动关闭界面
    if _scene_ready:
        timer 0.1 action Return()

    vbox:
        # 使用 pos 而不是 xalign 以避免与 anchor 冲突
        pos (0.5, 0.5)
        anchor (0.5, 0.5)
        spacing 24

        # 使用刚才定义好的 transform [cite: 4]
        add Solid("#ffffff"):
            xysize (48, 48)
            at loading_spinner_rotate

        # 省略号动画
        default dot_index = 0
        $ dots = ["", ".", "..", "..."]
        timer 0.5 repeat True action SetScreenVariable("dot_index", (dot_index + 1) % 4)

        text ("正在生成剧情和画面" + dots[dot_index]):
            xalign 0.5
            color "#ffffff"
            size 22

# ─────────────────────────────────────────────
# 3. 后台请求逻辑（保持不变）
# ─────────────────────────────────────────────
default _scene_result = None
default _scene_ready  = False

label request_next_scene(player_input, location, characters):
    $ _scene_ready = False
    $ _scene_result = None

    python:
        import threading, requests, json

        def _fetch():
            global _scene_result, _scene_ready
            try:
                # 这里的参数会通过 requests 发送到你的 local LLM 后端 [cite: 7, 8]
                resp = requests.post(
                    "http://127.0.0.1:8000/next_scene",
                    json={
                        "player_input": player_input,
                        "location":     location,
                        "characters":   characters,
                    },
                    timeout=300
                )
                _scene_result = resp.json() [cite: 8]
            except Exception as e:
                _scene_result = {
                    "lines": [{"type": "narration", "text": f"（网络错误：{e}）"}],
                    "choices": ["重试"],
                } [cite: 9]
            finally:
                _scene_ready = True
                renpy.restart_interaction() [cite: 10]

        threading.Thread(target=_fetch, daemon=True).start()

    # 显示界面直到数据准备好
    call screen loading_screen
    return _scene_result