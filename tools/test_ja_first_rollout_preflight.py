#!/usr/bin/env python3
"""Synthetic tests for read-only Japanese-first rollout preflight."""
import unittest

try:
    from tools import ja_first_rollout_preflight as p
except ModuleNotFoundError:
    import ja_first_rollout_preflight as p


def base_state():
    return {
        "health": {"providers": [{"name": "opensubtitles", "initialized": True,
                                   "healthy": True, "gate": "ok"}]},
        "budget": {"providers": [{"name": "opensubtitles", "tier": "free",
                                  "limits": {"day": 1000}, "usage": {"day": 1}}]},
        "config": {"upgrade_enabled": True, "provider_budget_enabled": True,
                   "wanted_auto_translate": False, "wanted_anime_only": False},
        "folders": [{"id": 4, "path": "/media/small", "enabled": False}],
        "standalone": {"enabled": True},
        "wanted_summary": {"total": 1},
        "wanted_scanner": {"is_scanning": False, "is_searching": False},
    }


class RolloutTests(unittest.TestCase):
    def test_native_healthy_and_warn_on_upgrade(self):
        state = base_state()
        page = {"items": [{"id": 42, "target_language": "ja",
                           "status": "wanted", "subtitle_type": "full",
                           "item_type": "episode", "file_path": "/media/A.mkv"}]}
        report = p.analyze(state, [page])
        self.assertFalse(report["blockers"])
        self.assertEqual(report["samples"][0]["id"], 42)
        self.assertTrue(any("upgrades enabled" in x for x in report["warnings"]))

    def test_read_only_fetch_only(self):
        states = base_state()
        path_data = {path: states[name] for name, path in p.API_PATHS.items()}
        visited = []
        def fake_fetch(path):
            visited.append(path)
            if path.startswith("/api/v1/wanted?"):
                return {"items": [], "total": 0}
            return path_data[path]
        result = p.collect(fake_fetch, max_pages=3, row_limit=2)
        self.assertEqual(result["pages_checked"], 1)
        self.assertFalse(result["errors"])
        self.assertTrue(all(url.startswith("/api/v1/") for url in visited))
        self.assertFalse(any("/scan" in u or "/download" in u for u in visited))

    def test_bad_gate_blocks(self):
        state = base_state()
        state["health"]["providers"][0]["gate"] = "no_pool_key"
        self.assertTrue(any("no_pool_key" in x for x in p.analyze(state, [])["blockers"]))

    def test_missing_health_blocks(self):
        state = base_state()
        state["health"] = None
        self.assertTrue(p.analyze(state, [])["blockers"])

    def test_other_language_and_forced_not_selected(self):
        state = base_state()
        page = {"items": [
            {"id": 1, "target_language": "en", "status": "wanted"},
            {"id": 2, "target_language": "ja", "status": "wanted", "subtitle_type": "forced"},
            {"id": 3, "target_language": "ja", "status": "found"},
            {"id": 4, "target_language": "ja", "status": "failed", "subtitle_type": "full"},
        ]}
        self.assertEqual([r["id"] for r in p.analyze(state, [page])["samples"]], [4])

    def test_provider_budget_not_assumed_quota(self):
        state = base_state()
        paths = {v: state[k] for k, v in p.API_PATHS.items()}
        def fetch(path):
            return {"items": []} if path.startswith("/api/v1/wanted?") else paths[path]
        result = p.collect(fetch, max_pages=1, row_limit=1)
        self.assertIn("NOT the remaining", result["download_quota_notice"])


if __name__ == "__main__":
    unittest.main()
