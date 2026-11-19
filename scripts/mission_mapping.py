"""Local occupancy from lidar and contemporaneous onboard odometry only."""
import math


class LidarMap:
    def __init__(self, walls, dock):
        self.walls = walls
        self.dock = dock
        self.cells = set()
        self.last_stamp = -math.inf

    def update(self, sample):
        ranges, angle_min, angle_step, stamp, position, yaw, position_stamp = sample
        if stamp <= self.last_stamp or position is None or not 0 <= stamp-position_stamp <= .2:
            return False
        self.last_stamp = stamp
        before = self.cells.copy()
        # A later unobstructed beam clears a former hit. Keep unseen occupancy;
        # elapsed time alone is not evidence that an obstacle disappeared.
        for cell in before:
            dx, dy = cell[0]*.4-position[0], cell[1]*.4-position[1]
            bearing = (math.atan2(dy, dx)-yaw+math.pi) % (2*math.pi)-math.pi
            index = round((bearing-angle_min)/angle_step)
            if 1 <= index < len(ranges)-1:
                free = min(ranges[index-1:index+2])
                if free > math.hypot(dx, dy)+.65:
                    self.cells.discard(cell)
        for index in range(0, len(ranges), 2):
            distance = ranges[index]
            if not math.isfinite(distance) or not .5 < distance < 6:
                continue
            angle = yaw+angle_min+index*angle_step
            x = position[0]+distance*math.cos(angle)
            y = position[1]+distance*math.sin(angle)
            known = any(a-.4 <= x <= a+w+.4 and b-.4 <= y <= b+h+.4
                        for a, b, w, h in self.walls)
            if not known and math.dist([x, y], self.dock) > 1.4:
                self.cells.add((round(x/.4), round(y/.4)))
        return self.cells != before
