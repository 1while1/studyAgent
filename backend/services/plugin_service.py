"""Plugin/Skill 系统（M2.4 扩展层）

基于 pip entry_points 的外部包插件机制。
插件通过 settings.toml 白名单授权加载。
"""
from __future__ import annotations
import importlib.metadata
from dataclasses import dataclass, field
from typing import Optional

ENTRY_POINT_GROUP = "studyagent.plugins"


@dataclass
class PluginSpec:
    name: str
    version: str = ""
    tools: list[dict] = field(default_factory=list)
    commands: list[dict] = field(default_factory=list)
    resources_dir: str = ""
    permissions: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "version": self.version,
                "tools": self.tools, "commands": self.commands,
                "resources_dir": self.resources_dir, "permissions": self.permissions}


class PluginRegistry:
    def __init__(self):
        self._plugins: dict[str, PluginSpec] = {}

    def scan_entry_points(self) -> list[PluginSpec]:
        discovered = []
        try:
            eps = importlib.metadata.entry_points()
            plugin_eps = eps.select(group=ENTRY_POINT_GROUP) if hasattr(eps, 'select') else eps.get(ENTRY_POINT_GROUP, [])
            for ep in plugin_eps:
                try:
                    obj = ep.load()
                    if isinstance(obj, PluginSpec):
                        discovered.append(obj)
                    elif hasattr(obj, 'get_plugin_spec'):
                        spec = obj.get_plugin_spec()
                        if isinstance(spec, PluginSpec):
                            discovered.append(spec)
                except Exception:
                    continue
        except Exception:
            pass
        return discovered

    def register(self, spec: PluginSpec):
        self._plugins[spec.name] = spec

    def get_plugin(self, name: str) -> Optional[PluginSpec]:
        return self._plugins.get(name)

    def get_all_plugins(self) -> list[PluginSpec]:
        return list(self._plugins.values())


class PluginLoader:
    def __init__(self, config=None):
        self._config = config
        self._registry = PluginRegistry()

    def _get_enabled_plugins(self) -> list[str]:
        if not self._config:
            return []
        # 兼容 ConfigService（嵌套 dict）和普通 dict
        plugins_section = None
        if hasattr(self._config, 'get'):
            plugins_section = self._config.get("plugins")
        if isinstance(plugins_section, dict):
            enabled = plugins_section.get("enabled", [])
        else:
            enabled = []
        return enabled if isinstance(enabled, list) else []

    def load_all(self) -> list[PluginSpec]:
        discovered = self._registry.scan_entry_points()
        enabled_names = set(self._get_enabled_plugins())
        loaded = []
        for spec in discovered:
            if spec.name in enabled_names:
                self._registry.register(spec)
                loaded.append(spec)
        return loaded

    @property
    def registry(self) -> PluginRegistry:
        return self._registry
