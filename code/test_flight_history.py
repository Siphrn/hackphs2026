import unittest

from dashboard_server import DashboardState
from flight_history import FlightHistory


class HistoryTests(unittest.TestCase):
    def test_video_budget_eviction_and_history_pruning(self):
        archive = FlightHistory(limit=2, video_limit_bytes=10)
        first = archive.save(dict(airtime=1, video_status="pending"))
        second = archive.save(dict(airtime=1, video_status="pending"))
        archive.attach_video(first, b"123456", 1)
        archive.attach_video(second, b"abcdef", 1, True)
        self.assertIsNone(archive.video(first))
        self.assertEqual(archive.video(second), b"abcdef")
        self.assertEqual(archive.list()[1]["video_status"], "expired")
        self.assertTrue(archive.list()[0]["video_truncated"])
        self.assertNotIn("abcdef", str(archive.list()))
        third = archive.save(dict(airtime=1))
        fourth = archive.save(dict(airtime=1))
        self.assertIsNone(archive.video(second))
        archive.attach_video(first, b"late")
        self.assertIsNone(archive.video(first))
        archive.attach_video(third, b"a" * 11)
        self.assertEqual(archive.list()[1]["video_status"], "unavailable")
        self.assertIsNone(FlightHistory().video(fourth))

    def test_plane_profiles_order_assignment_and_capture(self):
        archive = FlightHistory()
        state = DashboardState(archive)
        archive.change_profile("create", name="  Dart  ")
        dart = archive.profiles()["active_profile_id"]
        state.update(status="ARMED")
        archive.change_profile("create", name="Glider")
        glider = archive.profiles()["active_profile_id"]
        state.update(status="FLYING")
        state.update(status="COMPLETE", airtime=1)
        record = archive.list()[0]
        self.assertEqual(record["profile_id"], dart, "Selection after arming must not change the recorded plane")
        archive.change_profile("reorder", order=[glider, dart])
        self.assertEqual([p["name"] for p in archive.profiles()["profiles"]], ["Glider", "Dart"])
        archive.change_profile("assign", history_id=record["history_id"], profile_id=glider)
        self.assertEqual(archive.list()[0]["profile_id"], glider)
        state.update(status="ARMED")
        state.update(status="COMPLETE", airtime=1)
        self.assertEqual(archive.list()[0]["profile_id"], glider)
        archive.change_profile("select", profile_id=None)
        self.assertIsNone(archive.profiles()["active_profile_id"])
        self.assertEqual(FlightHistory().profiles(), {"profiles": [], "active_profile_id": None})
        for invalid in ([dart, dart], [dart], [dart, "unknown"], [[], dart]):
            with self.assertRaises(ValueError):
                archive.change_profile("reorder", order=invalid)
        for invalid in ("", "a" * 61, None, "bad\nname"):
            with self.assertRaises(ValueError):
                archive.change_profile("create", name=invalid)
        with self.assertRaises(ValueError):
            archive.change_profile("select", profile_id="unknown")
        with self.assertRaises(KeyError):
            archive.change_profile("assign", history_id="missing", profile_id=dart)
        external = archive.profiles()
        external["profiles"].clear()
        self.assertEqual(len(archive.profiles()["profiles"]), 2)

    def test_once_per_completed_flight_and_resets(self):
        archive = FlightHistory()
        state = DashboardState(archive)
        points = [[10, 20], [30, 40]]
        state.update(status="FLYING", trajectory=points)
        self.assertEqual(archive.list(), [])
        state.update(status="COMPLETE", score=83, airtime=.5, trajectory=points, trajectory_times=[0,.5])
        state.update(status="COMPLETE", score=99)
        points.clear()
        records = archive.list()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["score"], 83)
        self.assertEqual(records[0]["trajectory"], [[10,20],[30,40]])
        self.assertEqual(records[0]["trajectory_times"], [0,.5])
        self.assertEqual(state.snapshot()["history_id"], records[0]["history_id"])
        self.assertEqual(FlightHistory().list(), [])
        state.update(status="ARMED")
        state.update(status="COMPLETE", score=91)
        self.assertEqual([r["score"] for r in archive.list()], [91,83])

    def test_bounded_and_no_secrets(self):
        archive = FlightHistory(limit=2)
        for score in (70,80,90):
            archive.save(dict(score=score, airtime=1, trajectory=[], api_key="must-not-save", voice={"audio":"private"}))
        records = archive.list()
        self.assertEqual([r["score"] for r in records], [90,80])
        self.assertNotIn("must-not-save", str(records))
        self.assertNotEqual(records[0]["history_id"], records[1]["history_id"])

    def test_duration_boundary(self):
        archive = FlightHistory()
        for duration in (0, .1, .499999, float("nan"), None):
            self.assertIsNone(archive.save(dict(airtime=duration)))
        self.assertEqual(archive.list(), [])
        self.assertIsNotNone(archive.save(dict(airtime=.5)))
        self.assertIsNotNone(archive.save(dict(airtime=.501)))
        self.assertEqual(len(archive.list()), 2)

    def test_rename_validation_and_isolation(self):
        archive = FlightHistory()
        identifier = archive.save(dict(airtime=1, flight_id=1))
        self.assertEqual(archive.rename(identifier, "  Sky Glider  "), "Sky Glider")
        self.assertEqual(archive.list()[0]["name"], "Sky Glider")
        for invalid in ("", "  ", "a" * 61, "line\nbreak", None):
            with self.assertRaises(ValueError):
                archive.rename(identifier, invalid)
        with self.assertRaises(KeyError):
            archive.rename("missing", "Valid name")
        result = archive.list()
        result[0]["name"] = "Changed externally"
        self.assertEqual(archive.list()[0]["name"], "Sky Glider")


if __name__ == "__main__":
    unittest.main()
