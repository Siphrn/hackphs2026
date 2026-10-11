import tempfile
import unittest
from pathlib import Path

from dashboard_server import DashboardState
from flight_history import FlightHistory


class HistoryTests(unittest.TestCase):
    def test_once_per_completed_flight_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.sqlite3"
            archive = FlightHistory(path)
            state = DashboardState(archive)
            points = [[10, 20], [30, 40]]
            state.update(status="FLYING", trajectory=points)
            self.assertEqual(archive.list(), [])
            state.update(status="COMPLETE", score=83, airtime=.5, trajectory=points, trajectory_times=[0,.5])
            state.update(status="COMPLETE", score=99)
            points.clear()
            records = FlightHistory(path).list()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["score"], 83)
            self.assertEqual(records[0]["trajectory"], [[10,20],[30,40]])
            self.assertEqual(records[0]["trajectory_times"], [0,.5])
            self.assertEqual(state.snapshot()["history_id"], records[0]["history_id"])
            state.update(status="ARMED")
            state.update(status="COMPLETE", score=91)
            self.assertEqual([r["score"] for r in archive.list()], [91,83])

    def test_bounded_and_no_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = FlightHistory(Path(directory) / "history.sqlite3", limit=2)
            for score in (70,80,90):
                archive.save(dict(score=score, trajectory=[], api_key="must-not-save", voice={"audio":"private"}))
            records = archive.list()
            self.assertEqual([r["score"] for r in records], [90,80])
            self.assertNotIn("must-not-save", str(records))
            self.assertNotEqual(records[0]["history_id"], records[1]["history_id"])


if __name__ == "__main__":
    unittest.main()
