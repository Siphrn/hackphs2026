"""Camera-relative forecast. A frame exit is not a measured landing."""
import math


def predict_flight(samples, frame_width, frame_height):
    result = dict(speed=0, angle=0, points=[], remaining_airtime=0,
                  projected_distance=0, landing_x=None, confidence=0,
                  forecast_endpoint=None, forecast_kind=None)
    recent = list(samples)[-10:]
    if len(recent) < 3 or recent[-1][0] - recent[0][0] <= .03:
        return result
    # Fit all recent positions rather than using two noisy endpoints.
    times = [sample[0] - recent[-1][0] for sample in recent]
    mean_t = sum(times) / len(times)
    denominator = sum((t - mean_t) ** 2 for t in times)
    if denominator <= 0:
        return result
    vx = sum((t - mean_t) * p[1] for t, p in zip(times, recent)) / denominator
    vy = sum((t - mean_t) * p[2] for t, p in zip(times, recent)) / denominator
    _, x, y = recent[-1]
    result.update(speed=math.hypot(vx, vy),
                  angle=math.degrees(math.atan2(-vy, max(abs(vx), .01))))
    ground = frame_height * .9
    if not (0 <= x <= frame_width and 0 <= y < ground):
        return result
    points = [[round(x, 1), round(y, 1)]]
    previous_x, previous_y, previous_time = x, y, 0
    kind = "horizon"
    for step in range(1, 51):
        t = step * .04
        px, py = x + vx * t, y + vy * t + .5 * 420 * t * t
        intersections = []
        if px < 0:
            intersections.append(((0 - previous_x) / (px - previous_x), "exit"))
        elif px > frame_width:
            intersections.append(((frame_width - previous_x) / (px - previous_x), "exit"))
        if py < 0:
            intersections.append(((0 - previous_y) / (py - previous_y), "exit"))
        elif py >= ground:
            intersections.append(((ground - previous_y) / (py - previous_y), "landing"))
        if intersections:
            fraction, kind = min(intersections)
            px = previous_x + fraction * (px - previous_x)
            py = previous_y + fraction * (py - previous_y)
            t = previous_time + fraction * (t - previous_time)
        points.append([round(px, 1), round(py, 1)])
        result["remaining_airtime"] = t
        if intersections:
            break
        previous_x, previous_y, previous_time = px, py, t
    endpoint = points[-1]
    result.update(points=points, projected_distance=abs(endpoint[0] - x),
                  landing_x=endpoint[0] if kind == "landing" else None,
                  confidence=min(92, 35 + len(recent) * 6),
                  forecast_endpoint=endpoint, forecast_kind=kind)
    return result
