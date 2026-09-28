import os

os.environ["LIVE_JOBS"] = "0"  # no background watcher / scout loops in tests (backend/live/scheduler.py)
