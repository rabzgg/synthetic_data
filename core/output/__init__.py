"""
output — block [F]: run a scenario and write the files of every device (run.py), with a data
profile per device (profile.py).
"""
from .run import device_table, run
from .plot import plot_run, zip_run
from .profile import profile, profile_range
