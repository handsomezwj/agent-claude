# 被测对象：流式输出——真模型"边生成边吐字"，不再憋一口气。
#
# 之前每一课都是等模型憋出完整回答才返回，用户盯着"…"干等。
# 流式让模型把话一字一句/一块一块吐出来——打字机效果。
#
# 核心心法（跟第八课同款）：
#   流式接口也是个对象，给它开一个"门"（stream_factory），
#   门后面是真是假都能进——真流打字机，假流一分钱不花。
# 还有一条免费红利：get_final_message() 会把"完整回答"拼好还回来，
# 里面 stop_reason/content 一个不少 → 老循环的护栏判断一行不用改。


def assemble_text(chunks):
    """把流式吐出来的文字碎片拼成完整回答。纯函数，可测。"""
    return "".join(chunks)


def run_stream(stream_factory, on_chunk=None):
    """跑一次流式请求，逐块回调，结束返回 (完整回答, 最后的消息对象)。

    stream_factory: 一个"开一次流"的函数。
        真流：lambda: client.messages.stream(**kwargs)
        假流：lambda: FakeStream(剧本)         —— 第八课假模型的流式版
    on_chunk: 每吐一块文字就回调一次；打印用，可留空。
    返回的最后消息对象里有 stop_reason / content，
    所以原本"看 stop_reason 决定下一步"的循环逻辑可以直接复用。
    """
    chunks = []
    with stream_factory() as stream:
        for text in stream.text_stream:            # 边生成边吐
            chunks.append(text)
            if on_chunk:
                on_chunk(text)
        final_message = stream.get_final_message() # 流完，拼好的完整回答
    return assemble_text(chunks), final_message
