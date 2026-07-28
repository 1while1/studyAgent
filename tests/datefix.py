"""测试日期钉住（2026-07-29 假红修复批）。

掌握度按**真实当天**做时间衰减（半衰期 14 天，learner_service.date.today()），
而多个测试的证据时间戳钉死在 2026-07-23——写用例时 0.8 ≥ 0.7 达标，
6 天后衰减到 0.59 跌破达标线，learner_graph/prereq/relevance_review 三处假红。
pin_today 把 learner_service 模块的 date 换成固定 today 的子类，
让衰减基准与夹具时间戳对齐（新增证据 ts 晚于钉住日 → _days_between 钳 0，安全）。
"""

from datetime import date as _date
from unittest import mock


def pin_today(testcase, iso: str) -> None:
    """在 setUp 中调用：钉住 LearnerService 的「今天」，用例结束自动还原。"""
    y, m, d = (int(x) for x in iso.split("-"))

    class _FixedDate(_date):
        @classmethod
        def today(cls):
            return cls(y, m, d)

    patcher = mock.patch("backend.services.learner_service.date", _FixedDate)
    patcher.start()
    testcase.addCleanup(patcher.stop)
