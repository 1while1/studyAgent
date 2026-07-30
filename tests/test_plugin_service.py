"""M2.4 Plugin/Skill 系统单元测试。"""
import unittest
from unittest.mock import patch, MagicMock
from backend.services.plugin_service import (
    PluginSpec, PluginRegistry, PluginLoader, ENTRY_POINT_GROUP,
)


class TestPluginSpec(unittest.TestCase):
    """PluginSpec 数据类测试。"""

    def test_defaults(self):
        spec = PluginSpec(name="test_plugin")
        self.assertEqual(spec.name, "test_plugin")
        self.assertEqual(spec.version, "")
        self.assertEqual(spec.tools, [])
        self.assertEqual(spec.commands, [])
        self.assertEqual(spec.resources_dir, "")
        self.assertEqual(spec.permissions, {})

    def test_to_dict(self):
        spec = PluginSpec(
            name="my_plugin", version="1.0.0",
            tools=[{"name": "tool_a", "permission": "readonly"}],
            commands=[{"name": "cmd_a"}],
            resources_dir="/tmp/res",
            permissions={"network": False},
        )
        d = spec.to_dict()
        self.assertEqual(d["name"], "my_plugin")
        self.assertEqual(d["version"], "1.0.0")
        self.assertEqual(len(d["tools"]), 1)
        self.assertEqual(d["tools"][0]["name"], "tool_a")
        self.assertEqual(d["commands"], [{"name": "cmd_a"}])
        self.assertEqual(d["resources_dir"], "/tmp/res")
        self.assertEqual(d["permissions"], {"network": False})

    def test_to_dict_round_trip_keys(self):
        spec = PluginSpec(name="x")
        d = spec.to_dict()
        expected_keys = {"name", "version", "tools", "commands",
                         "resources_dir", "permissions"}
        self.assertEqual(set(d.keys()), expected_keys)


class TestPluginRegistry(unittest.TestCase):
    """PluginRegistry 注册与查询测试。"""

    def test_register_and_get(self):
        reg = PluginRegistry()
        spec = PluginSpec(name="alpha")
        reg.register(spec)
        self.assertIs(reg.get_plugin("alpha"), spec)

    def test_get_missing_returns_none(self):
        reg = PluginRegistry()
        self.assertIsNone(reg.get_plugin("nonexistent"))

    def test_get_all_plugins(self):
        reg = PluginRegistry()
        reg.register(PluginSpec(name="a"))
        reg.register(PluginSpec(name="b"))
        all_plugins = reg.get_all_plugins()
        self.assertEqual(len(all_plugins), 2)
        names = {p.name for p in all_plugins}
        self.assertEqual(names, {"a", "b"})

    def test_register_overwrites(self):
        reg = PluginRegistry()
        s1 = PluginSpec(name="x", version="1")
        s2 = PluginSpec(name="x", version="2")
        reg.register(s1)
        reg.register(s2)
        self.assertEqual(reg.get_plugin("x").version, "2")

    def test_scan_entry_points_no_plugins(self):
        """无插件安装时 scan_entry_points 返回空列表。"""
        reg = PluginRegistry()
        with patch("importlib.metadata.entry_points", return_value=[]):
            result = reg.scan_entry_points()
        self.assertEqual(result, [])

    def test_scan_entry_points_discovers_spec(self):
        """模拟 entry_point 返回 PluginSpec 实例。"""
        reg = PluginRegistry()
        mock_spec = PluginSpec(name="discovered_plugin", version="0.1")
        mock_ep = MagicMock()
        mock_ep.load.return_value = mock_spec

        mock_eps = MagicMock()
        mock_eps.select.return_value = [mock_ep]

        with patch("importlib.metadata.entry_points", return_value=mock_eps):
            result = reg.scan_entry_points()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "discovered_plugin")

    def test_scan_entry_points_discovers_factory(self):
        """模拟 entry_point 返回带 get_plugin_spec 工厂的模块对象。"""
        reg = PluginRegistry()
        expected = PluginSpec(name="factory_plugin")

        class Factory:
            def get_plugin_spec(self):
                return expected

        mock_ep = MagicMock()
        mock_ep.load.return_value = Factory()  # 返回实例而非类

        mock_eps = MagicMock()
        mock_eps.select.return_value = [mock_ep]

        with patch("importlib.metadata.entry_points", return_value=mock_eps):
            result = reg.scan_entry_points()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "factory_plugin")

    def test_scan_entry_points_skips_bad_ep(self):
        """加载异常的 entry_point 被静默跳过。"""
        reg = PluginRegistry()
        bad_ep = MagicMock()
        bad_ep.load.side_effect = ImportError("boom")

        mock_eps = MagicMock()
        mock_eps.select.return_value = [bad_ep]

        with patch("importlib.metadata.entry_points", return_value=mock_eps):
            result = reg.scan_entry_points()
        self.assertEqual(result, [])


class TestPluginLoader(unittest.TestCase):
    """PluginLoader 白名单过滤测试。"""

    def test_no_config_loads_nothing(self):
        loader = PluginLoader(config=None)
        loaded = loader.load_all()
        self.assertEqual(loaded, [])

    def test_empty_enabled_loads_nothing(self):
        config = MagicMock()
        config.get.return_value = {"enabled": [], "autoload": True}
        loader = PluginLoader(config=config)
        loaded = loader.load_all()
        self.assertEqual(loaded, [])

    def test_whitelist_filters(self):
        """只有白名单内的插件被加载。"""
        config = MagicMock()
        config.get.return_value = {"enabled": ["allowed"], "autoload": True}

        loader = PluginLoader(config=config)
        # 模拟 scan_entry_points 返回两个插件
        loader._registry.scan_entry_points = lambda: [
            PluginSpec(name="allowed"),
            PluginSpec(name="blocked"),
        ]
        loaded = loader.load_all()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].name, "allowed")
        # registry 也只有 allowed
        self.assertIsNotNone(loader.registry.get_plugin("allowed"))
        self.assertIsNone(loader.registry.get_plugin("blocked"))

    def test_registry_property(self):
        loader = PluginLoader()
        self.assertIsInstance(loader.registry, PluginRegistry)

    def test_non_list_enabled_treated_as_empty(self):
        config = MagicMock()
        config.get.return_value = {"enabled": "not_a_list"}
        loader = PluginLoader(config=config)
        loader._registry.scan_entry_points = lambda: [PluginSpec(name="x")]
        loaded = loader.load_all()
        self.assertEqual(loaded, [])


if __name__ == "__main__":
    unittest.main()
