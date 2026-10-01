"""Trusted damped least-squares joint planning, optional NumPy dependency.

Residuals are returned as evidence, never declared feasible merely because a
joint target exists. Five arm joints plus a separately commanded gripper can
leave Cartesian orientation goals unsatisfied on SO-101.
"""
import math


def damped_joint_target(joints, jacobian, error, limits, *, damping=.05, max_delta=.08):
    import numpy as np
    q,j,e = np.asarray(joints,dtype=float),np.asarray(jacobian,dtype=float),np.asarray(error,dtype=float)
    if q.ndim != 1 or j.shape != (len(e),len(q)) or len(limits) != len(q) or e.ndim != 1:
        raise ValueError('IK dimensions mismatch')
    if not all(np.isfinite(v).all() for v in (q,j,e)) or not math.isfinite(damping) or not math.isfinite(max_delta) or damping <= 0 or max_delta <= 0:
        raise ValueError('invalid measured IK inputs')
    bounds=np.asarray(limits,dtype=float)
    if bounds.shape != (len(q),2) or not np.isfinite(bounds).all() or np.any(bounds[:,0]>bounds[:,1]):
        raise ValueError('invalid IK joint limits')
    dq=j.T @ np.linalg.solve(j@j.T+damping**2*np.eye(len(e)),e)
    dq=np.clip(dq,-max_delta,max_delta)
    target=np.clip(q+dq,bounds[:,0],bounds[:,1])
    predicted=e-j@(target-q)
    return {'joint_target':target.tolist(),'linearized_residual':float(np.linalg.norm(predicted)),
            'requested_error':float(np.linalg.norm(e)),'feasibility_status':'unknown_until_measured_execution'}
