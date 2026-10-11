import unittest
from flight_prediction import predict_flight


class PredictionTests(unittest.TestCase):
    def test_left_exit_is_not_a_landing(self):
        samples = [(i * .02, 160 - 15 * i, 100) for i in range(8)]
        forecast = predict_flight(samples, 640, 480)
        self.assertEqual(forecast["forecast_kind"], "exit")
        self.assertIsNone(forecast["landing_x"])
        self.assertEqual(forecast["forecast_endpoint"][0], 0)
        self.assertAlmostEqual(forecast["projected_distance"], 55)
        self.assertEqual(forecast["points"][0], [55, 100])

    def test_landing_is_on_reference_ground(self):
        forecast = predict_flight([(i * .03, 250 + i, 220 + i) for i in range(8)], 640, 480)
        self.assertEqual(forecast["forecast_kind"], "landing")
        self.assertEqual(forecast["forecast_endpoint"][1], 432)
        self.assertIsNotNone(forecast["landing_x"])

    def test_bounds_and_top_exit(self):
        forecast = predict_flight([(i * .02, 300 + i, 250 - 30 * i) for i in range(8)], 640, 480)
        self.assertEqual(forecast["forecast_kind"], "exit")
        self.assertEqual(forecast["forecast_endpoint"][1], 0)
        for x, y in forecast["points"]:
            self.assertTrue(0 <= x <= 640)
            self.assertTrue(0 <= y <= 480)

    def test_no_forecast_without_enough_data(self):
        self.assertEqual(predict_flight([], 640, 480)["points"], [])
        self.assertEqual(predict_flight([(1, 1, 1)] * 4, 640, 480)["points"], [])


if __name__ == "__main__":
    unittest.main()
