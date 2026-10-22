"""
output — block [F]: run a scenario and write the files of every device (run.py), with a data
summary per device (summary.py).
"""
from .run import device_table, run
from .plot import plot_run, zip_run
from .summary import summary
