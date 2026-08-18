# 第一课：一个"只会接话"的 AI（还没有工具，先看懂骨架）
import os                      # 库：用来读环境变量（等下解释）
import anthropic               # 库：这是官方提供的"打电话工具"
from dotenv import load_dotenv # 库：用来读 .env 文件

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))  # 读脚本所在目录的 .env，钥匙不写死在代码里

# 造一个"电话机"：所有对模型的通话都通过它
client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),  # 你的钥匙
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),   # 打给哪个服务商
)

# 用哪个"大脑"？默认用便宜快的，你的 .env 里可以改成别的
model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")

history = []  # 这是它的"记忆"。现在空的。所有说过的话都会存进来

# 主循环：一直重复"听你说 → 问大脑 → 说出答案"
while True:
    user = input("你：")                  # ① 听你说话
    if not user.strip():                  #    如果你只按回车，就再听一次
        continue
    history.append({"role": "user", "content": user})  # ② 把你说的话记住

    # ③ 打电话给大脑：把整段聊天记录发给它，让它接着往下说
    resp = client.messages.create(
        model=model,          # 用哪个大脑
        max_tokens=1000,      # 最多让它说多长
        messages=history,     # 它需要看到全部聊天记录，才知道该接什么
    )

    # ④ 从回复里挑出"文字"部分
    answer = "".join(b.text for b in resp.content if b.type == "text")

    print("AI：", answer)     # ⑤ 把它说的话讲给你听
    history.append({"role": "assistant", "content": answer})  # ⑥ 它的回答也记住
