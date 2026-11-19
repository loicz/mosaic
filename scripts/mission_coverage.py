"""Conservative route coverage planning from map priors or measured anchors.

This is a geometry/range feasibility estimate, not an accuracy certificate.
It never consumes simulated personnel truth or future sensor samples.
"""
import math


def geometry(sites, point):
    a = b = d = 0.
    for site in sites:
        dx, dy = (point[i] - site['position'][i] for i in range(2))
        length = max(.2, math.hypot(dx, dy))
        x, y = dx / length, dy / length
        a += x*x; b += x*y; d += y*y
    determinant = a*d - b*b
    return math.sqrt((a+d)/determinant) if determinant > .01 else 100.


def route_points(route):
    yield route[0]
    for a, b in zip(route, route[1:]):
        steps = max(1, math.ceil(math.dist(a, b) / .5))
        for step in range(1, steps + 1):
            yield [a[i] + (b[i]-a[i])*step/steps for i in range(2)]


def coverage(sites, route, maximum_range):
    minimum = len(sites)
    worst = 0.
    for point in route_points(route):
        # Reserve a small margin for anchor calibration error and tag height.
        available = [s for s in sites if math.dist(point, s['position'][:2]) <= maximum_range-.25]
        minimum = min(minimum, len(available))
        worst = max(worst, geometry(available, point))
    return dict(covered=minimum >= 3 and worst <= 2.5,
                minimum_nodes=minimum, worst_geometry=worst)
