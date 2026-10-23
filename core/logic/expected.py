"""
expected.py — what a device's motion blocks should report, from the world's truth.

The same block (stillness_timer, spike_then_still) runs on the acceleration the device's mount
really feels (world truth turned into the body frame, no sensor errors). Its states become labels
with scope "expected", named <output without _state>_<state>, e.g. no_motion_pre_alarm, fall_alert.
The gate compares the device's own column with these.
"""
import numpy as np

from core.events.base import Label
from core.quantities import rotation as rot

from .blocks import MOTION_BLOCKS, build


def truth_accel(world, mount):
    view = world.view(mount)
    t = np.arange(0, world.duration_s + 1e-9, world.body_dt)
    return t, rot.rotate(rot.conj(view.at("body.orientation", t)), view.at("body.accel_g", t))


def state_labels(t, states, output, slug, scope="expected"):
    name = output[:-len("_state")] if output.endswith("_state") else output
    out, i, n = [], 0, len(states)
    while i < n:
        if states[i] == "ok":
            i += 1
            continue
        j = i
        while j < n and states[j] == states[i]:
            j += 1
        end = t[j] if j < n else t[-1]
        out.append(Label(float(t[i]), float(end), f"{name}_{states[i]}", "", scope, (slug,)))
        i = j
    return out


def expected_labels(world, view) -> list:
    blocks = [b for b in (build(s, view.device.name) for s in view.device.logic) if b.kind in MOTION_BLOCKS]
    if not blocks:
        return []
    t, a = truth_accel(world, view.mount)
    out = []
    for b in blocks:
        out += state_labels(t, b.states(t, a), b.output, view.slug)
    return out
