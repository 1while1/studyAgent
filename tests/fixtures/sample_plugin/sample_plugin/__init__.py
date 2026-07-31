"""示例插件：提供一个简单的文本分析工具"""
from backend.services.plugin_service import PluginSpec


def get_plugin_spec():
    return PluginSpec(
        name="sample",
        version="0.1.0",
        tools=[{
            "name": "word_count",
            "description": "统计文本字数",
            "permission": "READONLY",
            "params": {"text": "str"},
        }],
        commands=[],
        resources_dir="",
        permissions={"level": "READONLY"},
    )
