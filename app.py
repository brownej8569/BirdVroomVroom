from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, render_template, request, send_from_directory
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

_FRONTEND_DIR = pathlib.Path(__file__).parent / "frontend"


def _create_finch():
    if Finch is None:
        return None
    try:
        return Finch("A")
    except BaseException:
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
    "space": False,
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
    raw = data.get("currkey")
    key = (raw or "").lower() if raw != " " else "space"
    if key == " ":
        key = "space"
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
        boost = control_state["shift"] or control_state["space"]
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


def _connector_paths():
    """Typical install locations for Bluebird Connector (Windows)."""
    return [
        os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            "BirdBrain Technologies",
            "Bluebird Connector",
            "Bluebird Connector.exe",
        ),
        os.path.join(
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            "BirdBrain Technologies",
            "Bluebird Connector",
            "Bluebird Connector.exe",
        ),
    ]


@app.route("/open_connector", methods=["POST"])
def open_connector():
    """Launch Bluebird Connector from the local machine (localhost dev only)."""
    for path in _connector_paths():
        if path and os.path.isfile(path):
            try:
                subprocess.Popen([path], close_fds=True)  # noqa: S603
                return jsonify({"status": "success", "message": f"Started: {path}"})
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify(
        {
            "status": "error",
            "message": "Bluebird Connector not found. Install it or open it manually, then refresh.",
        }
    ), 404


@app.route("/robot/pause", methods=["POST"])
def robot_pause():
    """Stop motors / pause — used when Finch is connected to this backend."""
    if finch is None:
        return jsonify({"status": "ok", "message": "No Finch on this server session."})
    try:
        finch.stop()
        for k in list(control_state.keys()):
            control_state[k] = False
        return jsonify({"status": "success", "message": "Stopped."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/<path:page>")
def pages(page: str):
    # Serve other HTML templates by filename (e.g. /multiplayer-join.html).
    if page.endswith(".html") and (_FRONTEND_DIR / page).is_file():
        return render_template(page)

    # Serve frontend assets living next to the templates (styles.css, script.js).
    if page.endswith((".css", ".js")) and (_FRONTEND_DIR / page).is_file():
        return send_from_directory(_FRONTEND_DIR, page)

    return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    if finch is not None:
        threading.Thread(target=inputs, daemon=True).start()
        threading.Thread(target=sensors, daemon=True).start()

    socketio.run(app, debug=True, use_reloader=False)
