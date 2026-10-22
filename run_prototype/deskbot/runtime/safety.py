"""
The motor process's safety rules: EXACTLY the proven rules of the single-process robot, re-used.

MultiSonarRobot._check_safety (dashboard/multisonar.py) extends Robot._check_safety
(dashboard/robot.py, same rules as 3Nov-latest.py):
    forward   front IR must see the desk, front sonar > stop distance
    backward  rear IR must see the desk, rear sonar > stop distance
    turns     both IRs on the desk, side sonars > side stop distance
SafetyRules inherits that method without the Robot's threads or hardware (its __init__ is skipped),
so both runtimes always share one implementation.
"""

from multisonar import SIDE_STOP_DISTANCE, MultiSonarRobot  # dashboard/
from robot import DEFAULT_STOP_DISTANCE  # dashboard/


class SafetyRules(MultiSonarRobot):
    def __init__(self, stop_distance=DEFAULT_STOP_DISTANCE, side_stop_distance=SIDE_STOP_DISTANCE):
        # deliberately NOT calling Robot.__init__ (no hardware, no sensor thread)
        self.stop_distance = stop_distance
        self.side_stop_distance = side_stop_distance

    def check(self, direction, reading):
        """(kind, reason) if the move must stop, else None."""
        return self._check_safety(direction, reading)
