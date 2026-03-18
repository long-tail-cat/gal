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