"""Explicit opt-in LeRobot hardware transport; no auto-connect/calibration."""
import math
from .isaac_lab import JOINTS


class SO101Transport:
    def __init__(self,robot, *, limits, authorized=False):
        if set(limits) != set(JOINTS):raise ValueError('exact hardware joint limits required')
        self.robot,self.limits,self.authorized = robot,limits,authorized
    @classmethod
    def from_lerobot(cls, *, port, robot_id, limits, authorized=False):
        if not authorized:raise PermissionError('physical actuation requires explicit authorization')
        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
        robot = SO101Follower(SO101FollowerConfig(port=port,id=robot_id))
        return cls(robot,limits=limits,authorized=True)
    def connect(self):
        if not self.authorized:raise PermissionError('physical connection requires explicit authorization')
        self.robot.connect(calibrate=False)
    def step(self,action):
        if not self.authorized:raise PermissionError('physical actuation requires explicit authorization')
        if set(action) != {joint+'.pos' for joint in JOINTS}:raise ValueError('hardware joint action schema mismatch')
        for joint,(lo,hi) in self.limits.items():
            value = action[joint+'.pos']
            if type(value) not in (int,float) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError('hardware action outside calibrated limits')
        sent = self.robot.send_action(action)
        return {'sent':sent,'observations':self.robot.get_observation()}
    def close(self):
        self.robot.disconnect()
