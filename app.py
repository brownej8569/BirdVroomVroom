from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

try:
    # Provided by BirdBrain; may not be available on all dev machines.
    from backend.lib.BirdBrain import Finch  # type: ignore
except Exception:
    Finch = None  # type: ignore


app = Flask(
    __name__,
    template_folder="frontend",
    static_folder="images",
    static_url_path="/images",
)
socketio = SocketIO(app, cors_allowed_origins="*")


def _create_finch():
    if Finch is None:
        return None
    try:
        return Finch("A")
    except Exception:
        return None


finch = _create_finch()
avoid_obstacle = False

# Given state of whether the control buttons are pressed down or not
control_state = {
    "w": False,
    "a": False,
    "s": False,
    "d": False,
    "shift": False,
    "r": False,
}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def get_data():
    return jsonify({"message": "Hello from the Python backend!"})


@socketio.on("control_stuff")
def control_stuff(data):
    key = (data.get("currkey") or "").lower()
    pressed = bool(data.get("pressed"))

    if key in control_state:
        control_state[key] = pressed


def inputs():
    if finch is None:
        return

    prev_left = None
    prev_right = None

    while True:
        forward = control_state["w"]
        back = control_state["s"]
        left = control_state["a"]
        right = control_state["d"]
        boost = control_state["shift"]
        reset = control_state["r"]

        move_speed = 40
        turn_speed = 25
        left_speed = 0
        right_speed = 0

        if avoid_obstacle:
            continue

        if reset:
            finch.setTail("all", 0, 0, 0)
            finch.setBeak(0, 0, 0)

        if boost:
            move_speed = 100
            turn_speed = 50

        if forward:
            left_speed += move_speed
            right_speed += move_speed

        if back:
            left_speed -= move_speed
            right_speed -= move_speed

        if left:
            left_speed -= turn_speed
            right_speed += turn_speed

        if right:
            left_speed += turn_speed
            right_speed -= turn_speed

        left_speed = max(-100, min(100, left_speed))
        right_speed = max(-100, min(100, right_speed))

        if left_speed != prev_left or right_speed != prev_right:
            finch.setMotors(left_speed, right_speed)
            prev_left = left_speed
            prev_right = right_speed

        time.sleep(0.005)


def sensors():
    global avoid_obstacle

    if finch is None:
        return

    prev_incline = [""] * 10

    while True:
        distance = finch.getDistance()
        left_line = finch.getLine("L")
        right_line = finch.getLine("R")
        incline_state = ""

        prev_incline = prev_incline[1:] + [finch.getOrientation()]
        last_ten_level = sum(1 for x in prev_incline if x == "Level")

        incline_state = "Level" if last_ten_level > 6 else "In between"

        if distance < 15:
            avoid_obstacle = True
            finch.stop()
            finch.playNote(60, 1)
            finch.setMove("B", 20, 50)
            time.sleep(0.5)
            finch.stop()
            avoid_obstacle = False

        if left_line < 50 or right_line < 50:
            finch.playNote(40, 1)
            finch.setBeak(100, 100, 0)
            finch.setTail("all", 100, 100, 0)
            finch.stop()

        if incline_state != "Level":
            finch.setDisplay([1] * 25)
        else:
            finch.setDisplay([0] * 25)

        time.sleep(0.05)


@app.route("/first_finch_test", methods=["POST"])
def first_finch_test():
    script_path = os.path.join("backend", "meow.py")
    try:
        result = subprocess.check_output(
            [sys.executable, script_path],
            text=True,
            stderr=subprocess.STDOUT,
        )
        return jsonify({"status": "success", "output": result.strip()})
    except FileNotFoundError:
        error_msg = f"Error: The file '{script_path}' was not found."
        return jsonify({"status": "error", "message": error_msg}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500


if __name__ == "__main__":
    if finch is not None:
        threading.Thread(target=inputs, daemon=True).start()
        threading.Thread(target=sensors, daemon=True).start()

    socketio.run(app, debug=True, use_reloader=False)
