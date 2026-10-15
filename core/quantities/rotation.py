"""
rotation.py — quaternions [w, x, y, z] for frames: world, body (the thing that moves) and sensor.

Convention: a quaternion q_ab rotates a vector from frame a into frame b, v_b = R(q_ab) v_a.
The world gives the body orientation as q_body_to_world; a part's mounting_orientation is
q_sensor_to_body. All functions take single quaternions (4,) or arrays (n, 4).
"""
import numpy as np


def normalize(q):
    q = np.asarray(q, float)
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def conj(q):
    return np.asarray(q, float) * np.array([1.0, -1.0, -1.0, -1.0])


def mul(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    w1, x1, y1, z1 = np.moveaxis(a, -1, 0)
    w2, x2, y2, z2 = np.moveaxis(b, -1, 0)
    return np.stack([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
                     w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                     w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2], axis=-1)


def to_matrix(q):
    w, x, y, z = np.moveaxis(normalize(q), -1, 0)
    return np.stack([np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], -1),
                     np.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], -1),
                     np.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1)], -2)


def from_matrix(R):
    """Rotation matrix (3, 3) -> quaternion with w >= 0."""
    R = np.asarray(R, float)
    t = np.trace(R)
    if t > 0:
        s = 2 * np.sqrt(1 + t)
        q = [s / 4, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s]
    else:
        i = int(np.argmax(np.diag(R)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = 2 * np.sqrt(1 + R[i, i] - R[j, j] - R[k, k])
        v = np.empty(3)
        v[i], v[j], v[k] = s / 4, (R[j, i] + R[i, j]) / s, (R[k, i] + R[i, k]) / s
        q = [(R[k, j] - R[j, k]) / s, *v]
    q = normalize(q)
    return q if q[0] >= 0 else -q


def rotate(q, v):
    """R(q) v for q (4,) or (n, 4) and v (3,) or (n, 3)."""
    return np.einsum("...ij,...j->...i", to_matrix(q), np.asarray(v, float))


def from_axis_angle(axis_angle):
    """Rotation vector (rad; direction = axis, length = angle) -> quaternion."""
    v = np.asarray(axis_angle, float)
    a = np.linalg.norm(v, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        u = np.where(a > 0, v / a, 0.0)
    return np.concatenate([np.cos(a / 2), u * np.sin(a / 2)], axis=-1)


def from_euler_deg(roll, pitch, yaw):
    """Z-Y-X (yaw, then pitch, then roll about the moving axes), degrees -> quaternion."""
    r, p, y = np.radians([roll, pitch, yaw]) / 2
    return mul(mul([np.cos(y), 0, 0, np.sin(y)], [np.cos(p), 0, np.sin(p), 0]), [np.cos(r), np.sin(r), 0, 0])


def angle_between(a, b):
    """Rotation angle (rad) between two orientations; sign of q ignored."""
    d = np.abs(np.sum(normalize(a) * normalize(b), axis=-1))
    return 2 * np.arccos(np.clip(d, 0, 1))
