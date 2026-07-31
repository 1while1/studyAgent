"""示例插件工具实现"""


def word_count(ctx, args):
    """统计文本字数"""
    text = args.get("text", "")
    return {"count": len(text), "words": len(text.split())}
