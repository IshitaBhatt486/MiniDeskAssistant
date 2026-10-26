"""
Obstacle-to-obstacle navigation: "go from the cup to the bottle".

    costmap.py    the live maps -> a planning grid that knows what the motor safety rules will allow
    planners.py   direct line, visibility graph, Theta*, A*, weighted A*, RRT-Connect
    selector.py   measures the problem and picks the planner (the adaptive part)
    navigator.py  finds the named obstacles, follows the route, replans when the world disagrees
    scenes.py     synthetic maps for the tests and `navigate.py --compare`

Design and every constant: docs/navigation.md
"""

from .navigator import Navigator
from .selector import plan_route

__all__ = ["Navigator", "plan_route"]
