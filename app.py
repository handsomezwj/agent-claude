# app.py —— 云平台的启动入口（薄薄一层，真正的页面在 learn-agent/webchat/app.py）
#
# 为什么要有这个文件：
#   · 云平台的启动命令普遍是 gunicorn app:app —— 它只会去根目录找 app.py；
#   · 而 learn-agent 这个目录名带连字符，不是合法的 Python 包名，没法用
#     learn-agent.webchat.app:app 这种点号路径 import 进来。
# 所以这里用跟 agent_brain 一样的"门"手法：按文件路径把 webchat/app.py 加载成模块，
# 再把它建好的 Flask app 交出去。不多一行逻辑。
#
# 本地开发仍然可以直接跑 webchat/app.py（绑 127.0.0.1:5001），这个文件只在云上生效。
import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_WEBCHAT = _ROOT / "learn-agent" / "webchat"

# webchat/app.py 里那句 `from agent_brain import ...` 靠这条路径找得到
sys.path.insert(0, str(_WEBCHAT))

# 注意：这里故意不叫 "app"。本文件自己就是 app 模块，若再 `from app import app`
# 会 import 到自己（半成品模块）→ 报错。换个模块名，绕开这个坑。
_spec = importlib.util.spec_from_file_location("webchat_app", _WEBCHAT / "app.py")
_module = importlib.util.module_from_spec(_spec)
sys.modules["webchat_app"] = _module      # 先登记再执行，模块里的相对引用才找得到自己
_spec.loader.exec_module(_module)

app = _module.app                        # gunicorn app:app 要的就是它
create_app = _module.create_app


if __name__ == "__main__":
    # 本地也能 `python app.py` 直接跑（跟 webchat/app.py 同一个行为，不重复实现）
    _module.run_local()
