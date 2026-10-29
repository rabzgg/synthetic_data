"""
motion.py — how the body (the person or thing carrying the devices) moves, and what that means for
body.accel_g, body.gyro_dps and body.mag_ut.

A motion plan is a list of segments, each one of
    still       a living body at rest, standing or lying (posture): small movements (fidget_deg)
    motionless  no movement at all, standing or lying (events no_motion and collapse)
    walk        walking: forward speed, small turns, vertical bob and sway at the step frequency
    fall        from upright to lying: free fall to the ground, an impact, a 90° forward rotation
    rise        from lying back to upright, smoothly
    stir        lying but moving (stir_deg), e.g. between a fall and losing consciousness
From the plan, one kinematic description is built on the body grid: heading, pitch and roll, and
the position. Everything else is derived from it:
    orientation   body -> world quaternion (world: x = magnetic north, y = west, z = up)
    angular rate  from consecutive orientations (world frame), so it integrates back to them
    specific force second derivative of the position, minus gravity, in g (world frame): 1 g up at rest
    height        of the device above the floor (for pressure)
The body frame is x forward, y left, z up while upright. Sensors are mounted on the body with their
part's mounting_orientation; the measurement model turns world vectors into sensor axes.
"""
import numpy as np

from core.quantities import rotation as rot

from .physics import G

KINDS = ("still", "walk", "fall", "rise", "stir", "motionless")


def v(p):
    return p["value"] if isinstance(p, dict) and "value" in p else p


class MotionPlan:
    def __init__(self, duration_s: float, segments: list = None):
        self.duration_s = float(duration_s)
        self.segments = segments or [{"start": 0.0, "end": self.duration_s, "kind": "still", "posture": "upright"}]

    @classmethod
    def walk_still(cls, duration_s, rng, walk_bout_s, still_bout_s, start_with="still"):
        """Alternating still and walking bouts, lengths drawn uniformly from the given ranges."""
        segs, t, kind = [], 0.0, start_with
        while t < duration_s:
            lo, hi = walk_bout_s if kind == "walk" else still_bout_s
            e = min(duration_s, t + rng.uniform(lo, hi))
            segs.append({"start": t, "end": e, "kind": kind, "posture": "upright"})
            t, kind = e, ("still" if kind == "walk" else "walk")
        return cls(duration_s, segs)

    def walks(self):
        return [(s["start"], s["end"]) for s in self.segments if s["kind"] == "walk"]

    def moving(self) -> bool:
        return any(s["kind"] not in ("still", "motionless") for s in self.segments) or \
            len({s.get("posture") for s in self.segments}) > 1

    def at(self, t: float) -> dict:
        """The segment at time t."""
        for s in self.segments:
            if s["start"] <= t < s["end"]:
                return s
        return self.segments[-1]

    def insert(self, start: float, end: float, kind: str, posture: str = "upright"):
        """Put a segment over [start, end), cutting what was there (used by events)."""
        if kind not in KINDS:
            raise ValueError(f"unknown motion kind {kind!r}")
        out = []
        for s in self.segments:
            if s["end"] <= start or s["start"] >= end:
                out.append(s)
                continue
            if s["start"] < start:
                out.append(dict(s, end=start))
            if s["end"] > end:
                out.append(dict(s, start=end))
        out.append({"start": float(start), "end": float(min(end, self.duration_s)), "kind": kind, "posture": posture})
        self.segments = sorted(out, key=lambda s: s["start"])


def _euler_quat(yaw, pitch, roll):
    """Arrays of angles (rad) -> q = yaw(z) ⊗ pitch(y) ⊗ roll(x)."""
    cy, sy, cp, sp, cr, sr = (np.cos(yaw / 2), np.sin(yaw / 2), np.cos(pitch / 2), np.sin(pitch / 2),
                              np.cos(roll / 2), np.sin(roll / 2))
    return np.stack([cy * cp * cr + sy * sp * sr, cy * cp * sr - sy * sp * cr,
                     cy * sp * cr + sy * cp * sr, sy * cp * cr - cy * sp * sr], axis=-1)


def angular_rate_world(q, dt):
    """°/s, world frame: from q[k] to q[k+1] (last sample repeats)."""
    if len(q) < 2:
        return np.zeros((len(q), 3))
    dq = rot.mul(q[1:], rot.conj(q[:-1]))
    dq = np.where(dq[:, :1] < 0, -dq, dq)
    vn = np.linalg.norm(dq[:, 1:], axis=1, keepdims=True)
    angle = 2 * np.arctan2(vn, dq[:, :1])
    with np.errstate(invalid="ignore", divide="ignore"):
        axis = np.where(vn > 0, dq[:, 1:] / vn, 0.0)
    w = np.degrees(axis * angle / dt)
    return np.vstack([w, w[-1:]])


def kinematics(plan: MotionPlan, dt: float, params: dict, rng) -> dict:
    """Body tracks on a grid of step dt: orientation (n, 4), gyro (n, 3) °/s, specific force (n, 3) g,
    height (n,) m, state (n,) labels. A plan without movement gives one sample (a constant)."""
    p = {k: v(x) for k, x in params.items()}
    h_up, h_lying = p["device_height_m"], p["lying_height_m"]
    heading0 = np.radians(p.get("heading_deg", rng.uniform(0, 360)))
    if not plan.moving() and not (p.get("fidget_deg", 0) and any(x["kind"] == "still" for x in plan.segments)):
        q = _euler_quat(np.array([heading0]), np.zeros(1), np.zeros(1))
        return {"orientation": q, "gyro": np.zeros((1, 3)), "force": np.array([[0.0, 0.0, 1.0]]),
                "height": np.array([h_up]), "state": np.array(["still"], dtype=object)}
    n = int(round(plan.duration_s / dt)) + 1
    t = np.arange(n) * dt
    state = np.empty(n, dtype=object)
    walking = np.zeros(n)                 # 0..1, ramps over 1 s at the ends of a walk
    tilt = np.zeros(n)                    # forward rotation: 0 upright, pi/2 lying face down
    fidget = np.zeros(n)                  # amplitude (rad) of small movements of a living body
    z = np.full(n, h_up)
    h_cur, last = h_up, plan.segments[-1]
    for s in plan.segments:
        m = (t >= s["start"]) & ((t < s["end"]) | ((s is last) & (t >= s["end"])))
        kind, lying = s["kind"], s.get("posture") == "lying"
        state[m] = "lying" if (kind == "still" and lying) else kind
        tau = t[m] - s["start"]
        if kind == "walk":
            walking[m] = np.clip(np.minimum(tau, s["end"] - t[m]), 0, 1)
        elif kind == "fall":
            t_ff = np.sqrt(2 * (h_cur - h_lying) / G)
            imp = p["impact_s"]
            vz = np.where(tau < t_ff, -G * tau, np.where(tau < t_ff + imp, -G * t_ff * (1 - (tau - t_ff) / imp), 0.0))
            z[m] = h_cur + np.cumsum(vz) * dt
            tilt[m] = np.pi / 2 * np.clip(tau / (t_ff + imp), 0, 1)
            h_cur = z[m][-1] if m.any() else h_lying
            continue
        elif kind == "rise":
            frac = 0.5 - 0.5 * np.cos(np.pi * np.clip(tau / (s["end"] - s["start"]), 0, 1))
            z[m] = h_cur + (h_up - h_cur) * frac
            tilt[m] = np.pi / 2 * (1 - frac)
            h_cur = h_up
            continue
        z[m] = h_cur
        tilt[m] = np.pi / 2 if lying else 0.0
        if kind == "still":
            fidget[m] = np.radians(p.get("fidget_deg", 0.0))
        elif kind == "stir":
            fidget[m] = np.radians(p.get("stir_deg", 0.0))
    from .primitives import _ou as ou, _smooth as smooth
    fidget = smooth(fidget, max(1, int(round(1.0 / dt))))            # no jumps in amplitude
    tau_f = p.get("fidget_tau_s", 2.0)
    wob_p = ou(n, dt, 0.0, 1.0, tau_f, rng, x0=0.0) * fidget
    wob_r = ou(n, dt, 0.0, 1.0, tau_f, rng, x0=0.0) * fidget
    # heading: small turns while walking
    yaw_rate = ou(n, dt, 0.0, np.radians(p["turn_rate_sd_dps"]), p["turn_tau_s"], rng, x0=0.0) * walking
    yaw = heading0 + np.cumsum(yaw_rate) * dt
    f = p["step_hz"]
    phase = 2 * np.pi * f * t
    sway = np.radians(p["sway_deg"]) * walking
    pitch = sway * np.sin(phase) + tilt + wob_p
    roll = sway * np.sin(phase / 2) + wob_r
    q = _euler_quat(yaw, pitch, roll)
    # position: forward speed along the heading, vertical bob while walking
    speed = (p["speed_m_s"] + p["surge_m_s"] * np.sin(phase)) * walking
    xy = np.cumsum(np.stack([speed * np.cos(yaw), speed * np.sin(yaw)], -1), axis=0) * dt
    z = z + p["bob_m"] * walking * np.sin(phase)
    pos = np.column_stack([xy, z])
    acc = np.gradient(np.gradient(pos, dt, axis=0), dt, axis=0)
    force = acc / G + np.array([0.0, 0.0, 1.0])
    return {"orientation": q, "gyro": angular_rate_world(q, dt), "force": force, "height": z, "state": state}
