"""The investigation queue shows one row per question, not one per engine version."""

import unittest

from backend.service import ENGINE_VERSION, _latest_runs


def run(run_id, engine_version, kpi="traffic_total", region="North", date="2023-07-24"):
    return {"run_id": run_id, "kpi_id": kpi, "target_date": date, "persona": "marketing_manager",
            "engine_version": engine_version,
            "scope": {"region": region, "category": "Electronics", "persona": "marketing_manager", "target_date": date}}


class LatestRunsTests(unittest.TestCase):
    def test_duplicates_collapse_to_the_current_engine_version(self):
        items = [run("old-2", "kpi-engine-old-v2"), run("current", ENGINE_VERSION), run("old-1", "kpi-engine-old-v1")]
        latest = _latest_runs(items)
        self.assertEqual([item["run_id"] for item in latest], ["current"])
        self.assertEqual(latest[0]["superseded_runs"], 2)

    def test_without_a_current_version_the_most_recent_run_is_kept(self):
        latest = _latest_runs([run("newest", "kpi-engine-old-v2"), run("older", "kpi-engine-old-v1")])
        self.assertEqual([item["run_id"] for item in latest], ["newest"])

    def test_different_questions_are_not_merged(self):
        items = [run("a", ENGINE_VERSION), run("b", ENGINE_VERSION, kpi="orders"),
                 run("c", ENGINE_VERSION, region="South"), run("d", ENGINE_VERSION, date="2023-07-25")]
        self.assertEqual(len(_latest_runs(items)), 4)


if __name__ == "__main__":
    unittest.main()
