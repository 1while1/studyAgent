"""M1.1 错误模式库测试"""
import unittest
from backend.domain.error_pattern import ErrorPatternMajor, extract_error_pattern


class TestErrorPatternMajor(unittest.TestCase):
    """错误模式大类枚举测试"""

    def test_five_categories(self):
        """5 个枚举值"""
        self.assertEqual(len(ErrorPatternMajor), 5)

    def test_values(self):
        """枚举值正确"""
        expected = {"CONCEPT_CONFUSION", "DETAIL_ERROR", "LOGIC_BREAK",
                    "CANNOT_APPLY", "FORGOTTEN"}
        self.assertEqual(set(ErrorPatternMajor.values()), expected)

    def test_str_enum(self):
        """str 枚举可直接比较"""
        self.assertEqual(ErrorPatternMajor.CONCEPT_CONFUSION, "CONCEPT_CONFUSION")


class TestExtractErrorPattern(unittest.TestCase):
    """错误模式提取测试"""

    def test_valid_json(self):
        """合法 JSON 提取"""
        output = ('评分结果：{"score": 3.5, "error_major": "CONCEPT_CONFUSION", '
                  '"error_minor": "将BFS当成DFS"}')
        major, minor = extract_error_pattern(output)
        self.assertEqual(major, "CONCEPT_CONFUSION")
        self.assertEqual(minor, "将BFS当成DFS")

    def test_null_error(self):
        """回答正确（null）"""
        output = '{"score": 5.0, "error_major": null, "error_minor": null}'
        major, minor = extract_error_pattern(output)
        self.assertIsNone(major)

    def test_invalid_major(self):
        """非法 major 值"""
        output = '{"error_major": "INVALID_TYPE", "error_minor": "test"}'
        major, minor = extract_error_pattern(output)
        self.assertIsNone(major)

    def test_no_json(self):
        """无 JSON 内容"""
        major, minor = extract_error_pattern("普通文本没有JSON")
        self.assertIsNone(major)
        self.assertIsNone(minor)

    def test_malformed_json(self):
        """格式错误 JSON"""
        major, minor = extract_error_pattern('{"error_major": "CONCEPT_CONFUSION"')
        self.assertIsNone(major)

    def test_all_categories(self):
        """所有 5 个类别都能正确提取"""
        for cat in ErrorPatternMajor.values():
            output = f'{{"error_major": "{cat}", "error_minor": "test"}}'
            major, _ = extract_error_pattern(output)
            self.assertEqual(major, cat)

    def test_empty_minor(self):
        """minor 为空字符串时返回 None"""
        output = '{"error_major": "FORGOTTEN", "error_minor": ""}'
        major, minor = extract_error_pattern(output)
        self.assertEqual(major, "FORGOTTEN")
        self.assertIsNone(minor)

    def test_missing_minor(self):
        """缺少 minor 字段"""
        output = '{"error_major": "DETAIL_ERROR"}'
        major, minor = extract_error_pattern(output)
        self.assertEqual(major, "DETAIL_ERROR")
        self.assertIsNone(minor)

    def test_embedded_in_text(self):
        """JSON 嵌在文本中"""
        output = ('一些分析文字\n{"error_major": "LOGIC_BREAK", '
                  '"error_minor": "忽略了边界条件"}\n更多文字')
        major, minor = extract_error_pattern(output)
        self.assertEqual(major, "LOGIC_BREAK")
        self.assertEqual(minor, "忽略了边界条件")


if __name__ == "__main__":
    unittest.main()
