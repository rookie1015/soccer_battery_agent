from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


BRIDGE_PATH = (
    Path(__file__).parents[1]
    / "android"
    / "FootballLotteryAndroid"
    / "app"
    / "src"
    / "main"
    / "python"
    / "android_bridge.py"
)


def _load_bridge():
    spec = importlib.util.spec_from_file_location("android_bridge_for_test", BRIDGE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 Android Python 桥接模块。")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AndroidBridgeTests(unittest.TestCase):
    def test_analysis_returns_sanitized_chinese_error_json(self) -> None:
        bridge = _load_bridge()
        with patch.object(
            bridge,
            "run_analysis",
            side_effect=RuntimeError("Traceback: internal/path.py SECRET_CODE"),
        ):
            result = json.loads(bridge.analysis('{"issue":"26090"}', "."))

        self.assertFalse(result["ok"])
        self.assertTrue(result["error"].startswith("完整分析失败："))
        self.assertNotIn("Traceback", result["error"])
        self.assertNotIn("internal/path.py", result["error"])
        self.assertNotIn("SECRET_CODE", result["error"])


if __name__ == "__main__":
    unittest.main()
