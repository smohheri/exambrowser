"""Watchdog for the Exam Browser.

Supervises ``exam_browser.py`` and relaunches it automatically if the app
is closed or crashes unexpectedly. A clean shutdown (admin password) writes
the ``exit.flag`` file, which tells the watchdog to stop restarting.
"""

import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(BASE_DIR, "exam_browser.py")
FLAG = os.path.join(BASE_DIR, "exit.flag")


def run():
    if os.path.exists(FLAG):
        os.remove(FLAG)

    # Prefer a windowless interpreter when available.
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pythonw):
        exe = pythonw

    while True:
        proc = subprocess.Popen([exe, MAIN], cwd=BASE_DIR)
        proc.wait()
        if os.path.exists(FLAG):
            os.remove(FLAG)
            break
        time.sleep(1.0)


if __name__ == "__main__":
    run()
