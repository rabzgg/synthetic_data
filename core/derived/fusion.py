"""
fusion.py — orientation quaternion fused from accelerometer, gyroscope and (optionally)
magnetometer readings.

Algorithm: Madgwick's gradient-descent filter (S. Madgwick, "An efficient orientation filter for
inertial and inertial/magnetic sensor arrays", 2010), MARG form with the magnetometer, IMU form
without. It is an ASSUMPTION: a device's own fusion algorithm (e.g. a vendor library) is usually
not published, so this stands in for it.

Output: q from sensor frame to world frame, [w, x, y, z]; world x = horizontal magnetic north,
y = west, z = up (gravity points along −z, so a sensor at rest reads +1 g up). The first sample sets
the initial orientation from gravity and the magnetic field (TRIAD), then the filter runs.
"""
import numpy as np

from core.quantities import rotation as rot

from .base import DerivedChannel

AXES_IN = ("body.accel_g", "body.gyro_dps", "body.mag_ut")


def initial_orientation(acc, mag=None):
    """Sensor -> world quaternion from one gravity and one magnetic field reading (TRIAD)."""
    up = np.asarray(acc, float) / np.linalg.norm(acc)
    if mag is None:
        ref = np.array([1.0, 0, 0]) if abs(up[0]) < 0.9 else np.array([0, 1.0, 0])
    else:
        ref = np.asarray(mag, float)
    north = ref - ref.dot(up) * up
    north /= np.linalg.norm(north)
    west = np.cross(up, north)
    return rot.from_matrix(np.vstack([north, west, up]))


def madgwick(acc, gyr_dps, mag, dt, beta, q0=None):
    """acc (n, 3) any unit, gyro (n, 3) in °/s, mag (n, 3) any unit or None -> q (n, 4)."""
    acc, gyr = np.asarray(acc, float), np.radians(np.asarray(gyr_dps, float))
    use_mag = mag is not None
    mag = np.asarray(mag, float) if use_mag else None
    w, x, y, z = q0 if q0 is not None else initial_orientation(acc[0], None if mag is None else mag[0])
    out = np.empty((len(acc), 4))
    for i in range(len(acc)):
        gx, gy, gz = gyr[i]
        dw = 0.5 * (-x * gx - y * gy - z * gz)
        dx = 0.5 * (w * gx + y * gz - z * gy)
        dy = 0.5 * (w * gy - x * gz + z * gx)
        dz = 0.5 * (w * gz + x * gy - y * gx)
        ax, ay, az = acc[i]
        na = (ax * ax + ay * ay + az * az) ** 0.5
        if na > 0:
            ax, ay, az = ax / na, ay / na, az / na
            f1 = 2 * (x * z - w * y) - ax
            f2 = 2 * (w * x + y * z) - ay
            f3 = 1 - 2 * (x * x + y * y) - az
            sw = -2 * y * f1 + 2 * x * f2
            sx = 2 * z * f1 + 2 * w * f2 - 4 * x * f3
            sy = -2 * w * f1 + 2 * z * f2 - 4 * y * f3
            sz = 2 * x * f1 + 2 * y * f2
            if use_mag:
                mx, my, mz = mag[i]
                nm = (mx * mx + my * my + mz * mz) ** 0.5
                if nm > 0:
                    mx, my, mz = mx / nm, my / nm, mz / nm
                    hx = mx * (1 - 2 * (y * y + z * z)) + my * 2 * (x * y - w * z) + mz * 2 * (x * z + w * y)
                    hy = mx * 2 * (x * y + w * z) + my * (1 - 2 * (x * x + z * z)) + mz * 2 * (y * z - w * x)
                    bz = mx * 2 * (x * z - w * y) + my * 2 * (y * z + w * x) + mz * (1 - 2 * (x * x + y * y))
                    bx = (hx * hx + hy * hy) ** 0.5
                    f4 = bx * (1 - 2 * (y * y + z * z)) + bz * 2 * (x * z - w * y) - mx
                    f5 = bx * 2 * (x * y - w * z) + bz * 2 * (w * x + y * z) - my
                    f6 = bx * 2 * (w * y + x * z) + bz * (1 - 2 * (x * x + y * y)) - mz
                    sw += -2 * bz * y * f4 + (-2 * bx * z + 2 * bz * x) * f5 + 2 * bx * y * f6
                    sx += 2 * bz * z * f4 + (2 * bx * y + 2 * bz * w) * f5 + (2 * bx * z - 4 * bz * x) * f6
                    sy += (-4 * bx * y - 2 * bz * w) * f4 + (2 * bx * x + 2 * bz * z) * f5 + (2 * bx * w - 4 * bz * y) * f6
                    sz += (-4 * bx * z + 2 * bz * x) * f4 + (-2 * bx * w + 2 * bz * y) * f5 + 2 * bx * x * f6
            ns = (sw * sw + sx * sx + sy * sy + sz * sz) ** 0.5
            if ns > 0:
                dw, dx, dy, dz = dw - beta * sw / ns, dx - beta * sx / ns, dy - beta * sy / ns, dz - beta * sz / ns
        w, x, y, z = w + dw * dt, x + dx * dt, y + dy * dt, z + dz * dt
        n = (w * w + x * x + y * y + z * z) ** 0.5
        w, x, y, z = w / n, x / n, y / n, z / n
        out[i] = w, x, y, z
    return out


class OrientationQuat(DerivedChannel):
    kind = "orientation_quat"
    name = "Orientation (sensor fusion)"
    algorithm = ("ASSUMPTION: Madgwick 2010 gradient-descent filter (MARG with magnetometer, IMU without), initial "
                 "orientation from the first gravity and magnetic reading; a device's own fusion is not published.")
    PARAMS = {
        "beta": {"value": 0.1, "unit": "-",
                 "source": "ASSUMPTION: default gain of Madgwick's reference implementation"},
        "use_mag": {"value": True, "unit": "-", "source": "ASSUMPTION: magnetometer used when the device has one"},
        "write_w": {"value": True, "unit": "-",
                    "source": "ASSUMPTION: write w; false = write x, y, z only, sign chosen so that w >= 0"},
    }

    def __init__(self, params: dict = None, prefix: str = "orientation"):
        super().__init__(params, prefix=prefix)
        self.prefix = prefix

    def inputs(self):
        return list(AXES_IN if self.p("use_mag") else AXES_IN[:2])

    def columns(self):
        return [f"{self.prefix}_{c}" for c in ("wxyz" if self.p("write_w") else "xyz")]

    def compute(self, readings, dt):
        q = madgwick(readings["body.accel_g"], readings["body.gyro_dps"],
                     readings["body.mag_ut"] if self.p("use_mag") else None, dt, float(self.p("beta")))
        q = np.where(q[:, :1] < 0, -q, q)                  # same rotation, w >= 0
        cols = self.columns()
        comps = q if self.p("write_w") else q[:, 1:]
        return {c: comps[:, i] for i, c in enumerate(cols)}
