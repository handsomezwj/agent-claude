# 被测对象：把"纯函数"拆出来，让它们能被单独测试
def get_weather(city: str) -> str:
    fake = {"北京": "晴，32°C", "上海": "小雨，28°C", "广州": "多云，30°C"}
    return fake.get(city, f"暂无 {city} 的天气数据")


def run_tool(name: str, args: dict) -> str:
    if name == "get_weather":
        return get_weather(args["city"])
    return f"没有这个工具：{name}"
