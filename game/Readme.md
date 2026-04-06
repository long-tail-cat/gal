需要以下
renpy8.5.2或者更新
neo4j
graphiti
ollama和gemma3:12b

要先创建数据库
运行项目前要先运行数据库和ollama，再运行server.py
在renpy中启动项目，长时间卡顿是很正常的
如果爆网络错误。一般是你的ollama（默认是http://localhost:11434/v1）或者neo4j的端口（默认是neo4j://127.0.0.1:7687）和脚本里写的不一样，去memory.py里改；或者是server.py的端口（http://127.0.0.1:8000）堵塞。

要修改世界观和角色设定，可以编辑 scene_generator.py 顶部的 WORLD_SETTING 和 CHARACTER_SETTINGS。
生图的部分没有实装，不过不影响用

3月25日更新
改变了对话的逻辑，现在旁白不一定出现在对话的开头了
实装了生图：需要comfyUI，使用的模型是AnythingXL_xl（找不到的话带着u盘我明天拷给你）
在server.py中可以开关生图了
在scene_genertor中可以在配置常量中改llm了，以后只需要改这一处了
ALIrequests.py是调用hab的api的脚本，目前能在命令行对话，没啥用，可以删了



INFO:     127.0.0.1:13908 - "POST /save_episode HTTP/1.1" 200 OK
INFO:     127.0.0.1:8618 - "GET /image_ready HTTP/1.1" 200 OK
[SceneGenerator] JSON解析失败: Invalid control character at: line 4 column 70 (char 162)
原始输出:
{
  "lines": [
    {"type": "narration", "text": "阳光透过图书馆高大的窗户，在书架上投下斑驳的光影。空气中弥漫着书页的淡淡香味。"},
    {"type": "dialogue", "character": "爱丽丝", "text": "这里真是安静…适合思考。”},
    {"type": "narration", "text": "爱丽丝坐在一个靠窗的书桌旁，戴着眼镜，翻阅着一本封面略有磨损的推理小说。"},
    {"type": "dialogue", "character": "爱丽丝", "text": "你…也来图书馆了？"},
    {"type": "narration", "text": "玩家的到来似乎打断了爱丽丝的沉思。"},
    {"type": "dialogue", "character": "玩家", "text": "嗯，我只是想看看书。"},
    {"type": "dialogue", "character": "爱丽丝", "text": "我喜欢推理小说。逻辑和谜题总能让我比较放松。"},
    {"type": "narration", "text": "爱丽丝的眼神中带着一丝淡淡的羞涩，但嘴角却微微上扬。"},
    {"type": "dialogue", "character": "玩家", "text": "你喜欢看推理小说吗？"},
    {"type": "dialogue", "character": "爱丽丝", "text": "是的，你觉得怎么样？"},
    {"type": "narration", "text": "爱丽丝似乎想借机和玩家聊聊。"},
    {"type": "dialogue", "character": "玩家", "text": "我也喜欢。"},
    {"type": "narration", "text": "玩家选择了与爱丽丝进行简单的对话。" }
  ],
  "choices": ["询问爱丽丝的推理小说推荐", "聊聊学校生活"],
  "background": "school library, warm lighting, bookshelves, a comfortable atmosphere",
  "character_emotions": {"爱丽丝": "shy"}
}
INFO:     127.0.0.1:8619 - "POST /next_scene HTTP/1.1" 200 OK