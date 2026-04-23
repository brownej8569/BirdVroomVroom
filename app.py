from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import threading
import time
import random

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_socketio import SocketIO, join_room, leave_room

try:
    # Provided by BirdBrain; may not be available on all dev machines.
    from backend.lib.BirdBrain import Finch  # type: ignore
except Exception:
    Finch = None  # type: ignore


_ROOT_DIR = pathlib.Path(__file__).parent
_FRONTEND_DIR = _ROOT_DIR / "frontend"

app = Flask(
    __name__,
    template_folder=str(_FRONTEND_DIR),
    # Images are imported manually into frontend/images/
    static_folder=str(_FRONTEND_DIR / "images"),
    static_url_path="/images",
)
socketio = SocketIO(app, cors_allowed_origins="*")

# -------------------------
# Multiplayer (simple rooms)
# -------------------------
_MP_LOCK = threading.Lock()
_MP_ROOMS: dict[str, dict] = {}
_MP_DISCONNECT_GRACE_S = 15.0


def _mp_norm_code(raw: str | None) -> str:
    """Match frontend: uppercase A–Z / 0–9 only, max 6 chars."""
    return "".join(ch for ch in (raw or "").upper() if ch.isalnum())[:6]


def _mp_generate_code(length: int = 6) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(alphabet) for _ in range(length))


def _mp_room_snapshot(code: str, you_sid: str | None = None) -> dict:
    room = _MP_ROOMS.get(code)
    if not room:
        return {
            "code": code,
            "players": [],
            "max_players": 3,
            "host_player_id": None,
            "connectedCount": 0,
            "readyConnectedCount": 0,
            "allReadyConnected": False,
            "canStart": False,
            "statusMessage": "Room not found.",
        }

    players = []
    for pid, p in room["players"].items():
        # Consider player "connected" if they have a live sid.
        players.append(
            {
                "player_id": pid,
                "username": p.get("username") or "",
                "ready": bool(p.get("ready")),
                "connected": bool(p.get("sid")),
                "role": p.get("role") or "guest",
            }
        )

    connected = [pl for pl in players if pl["connected"]]
    connected_count = len(connected)
    ready_connected_count = sum(1 for pl in connected if pl["ready"])
    all_ready_connected = connected_count >= 2 and ready_connected_count == connected_count
    host_pid = room.get("host_player_id")
    can_start = bool(host_pid and all_ready_connected)
    if connected_count < 2:
        status = "Waiting for more players..."
    elif all_ready_connected:
        status = "All connected players are ready. Host can start."
    else:
        status = "Ready up!"

    return {
        "code": code,
        "players": players,
        "max_players": 3,
        "host_player_id": host_pid,
        "connectedCount": connected_count,
        "readyConnectedCount": ready_connected_count,
        "allReadyConnected": all_ready_connected,
        "canStart": can_start,
        "statusMessage": status,
    }


def _mp_cleanup_room(room: dict) -> None:
    """Remove players that disconnected beyond grace window."""
    now = time.time()
    stale: list[str] = []
    for pid, p in room["players"].items():
        sid = p.get("sid")
        if sid:
            continue
        last_seen = float(p.get("last_seen") or 0.0)
        if now - last_seen >= _MP_DISCONNECT_GRACE_S:
            stale.append(pid)

    for pid in stale:
        room["players"].pop(pid, None)

    # Host reassignment if needed
    host_pid = room.get("host_player_id")
    if host_pid and host_pid not in room["players"]:
        players = room["players"]
        prefer = [pid for pid, p in players.items() if p.get("role") == "host"]
        if prefer:
            room["host_player_id"] = prefer[0]
        else:
            room["host_player_id"] = next(iter(players.keys()), None)


@app.route("/images/<path:filename>")
def images(filename: str):
    # Our catch-all route below can otherwise intercept /images/... and 404 it.
    return send_from_directory(app.static_folder, filename)


@app.route("/__debug/routes")
def debug_routes():
    return jsonify(
        {
            "static_url_path": app.static_url_path,
            "static_folder": app.static_folder,
            "rules": sorted([r.rule for r in app.url_map.iter_rules()]),
        }
    )


def _create_finch():
    if Finch is None:
        return None
    print("FINCH CREATE: attempting Finch('A')")
    try:
        f = Finch("A")
        print("FINCH CREATE: Finch('A') object created")
        return f
    except BaseException:
        print("FINCH CREATE: failed to create Finch('A')")
        return None


finch = _create_finch()
avoid_obstacle = False
_MOTOR_THREADS_STARTED = False

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


@app.route("/api/finch/test", methods=["POST"])
def finch_test():
    """
    Lightweight connectivity sanity check for the UI.
    Must never crash the server if Finch isn't connected.
    """
    global finch
    try:
        print("FINCH TEST ROUTE HIT")
        print("FINCH AVAILABLE:", finch is not None)
        if finch is None:
            finch = _create_finch()
        if finch is None:
            return jsonify(
                {
                    "ok": False,
                    "message": "Finch test: Finch object missing (not detected).",
                }
            ), 200

        print("FINCH TEST: attempting getDistance()")
        distance = None
        try:
            distance = finch.getDistance()
        except Exception as e:
            err = str(e)
            if "device is not connected" in err.lower():
                return jsonify(
                    {
                        "ok": False,
                        "message": "Finch test: Finch object exists but device is not connected.",
                        "detail": err,
                    }
                ), 200
            if any(s in err.lower() for s in ["access", "denied", "busy", "in use", "exclusive"]):
                return jsonify(
                    {
                        "ok": False,
                        "message": "Finch test: Finch command failed (robot may be busy/locked by another app).",
                        "detail": err,
                    }
                ), 200
            return jsonify({"ok": False, "message": "Finch test: Finch command failed.", "detail": err}), 200

        try:
            print("FINCH TEST: attempting stop()")
            finch.stop()
        except Exception as e:
            # If this fails, keep it as detail but don't claim success.
            return jsonify(
                {
                    "ok": False,
                    "message": "Finch test: Finch responded, but stop() failed.",
                    "detail": str(e),
                }
            ), 200

        _ensure_motor_threads()
        return jsonify(
            {
                "ok": True,
                "message": "Finch test: OK (Finch detected and responsive).",
                "detail": f"distance={distance}",
            }
        ), 200
    except Exception as e:
        return jsonify(
            {
                "ok": False,
                "message": "Finch test: Finch connection failed.",
                "detail": str(e),
            }
        ), 200


@app.route("/api/mp/create", methods=["POST"])
def mp_create():
    print("CREATE ROOM ROUTE HIT")
    with _MP_LOCK:
        code = _mp_generate_code(6)
        for _ in range(10):
            if code not in _MP_ROOMS:
                break
            code = _mp_generate_code(6)
        _MP_ROOMS[code] = {
            "created_at": time.time(),
            "players": {},  # player_id -> {sid, username, ready, role, last_seen}
            "host_player_id": None,
        }
    return jsonify({"code": code}), 200


@app.route("/api/mp/exists/<code>", methods=["GET"])
def mp_exists(code: str):
    print("JOIN ROOM ROUTE HIT")
    code = _mp_norm_code(code)
    with _MP_LOCK:
        exists = code in _MP_ROOMS
        if exists:
            room = _MP_ROOMS.get(code)
            if room is None:
                return jsonify({"exists": False, "full": False, "players": 0}), 200
            _mp_cleanup_room(room)
            players = room.get("players") or {}
            count = len(players)
            connected = sum(1 for p in players.values() if p.get("sid"))
            # Full only when the room truly cannot accept a new live player:
            # 3 connected, OR 3 roster slots with at least one still online.
            # (All-offline 3-slot "ghost" rooms are treated as joinable; mp_join clears them.)
            full = connected >= 3 or (count >= 3 and connected > 0)
        else:
            count = 0
            full = False
    return jsonify({"exists": exists, "full": full, "players": count}), 200


@socketio.on("control_stuff")
def control_stuff(data):
    raw = data.get("currkey")
    key = (raw or "").lower() if raw != " " else "space"
    if key == " ":
        key = "space"
    pressed = bool(data.get("pressed"))

    if key in control_state:
        control_state[key] = pressed


@socketio.on("mp_join")
def mp_join(data):
    code = _mp_norm_code(data.get("code"))
    role = (data.get("role") or "").lower()
    sid = request.sid
    player_id = (data.get("playerId") or "").strip()
    username = (data.get("username") or "").strip()

    if not player_id:
        socketio.emit("mp_error", {"error": "Missing player id."}, to=sid)
        return

    with _MP_LOCK:
        room = _MP_ROOMS.get(code)
        if not room:
            socketio.emit("mp_error", {"error": "Room not found."}, to=sid)
            return
        _mp_cleanup_room(room)

        players: dict = room["players"]
        connected_n = sum(1 for p in players.values() if p.get("sid"))

        # Abandoned test room: 3 roster entries but nobody connected — clear so the code works again.
        if len(players) >= 3 and connected_n == 0:
            players.clear()
            room["host_player_id"] = None
            connected_n = 0

        if player_id not in players:
            if connected_n >= 3:
                socketio.emit("mp_error", {"error": "Room is full."}, to=sid)
                return
            if len(players) >= 3:
                socketio.emit("mp_error", {"error": "Room is full."}, to=sid)
                return

        p = players.get(player_id) or {}
        p["sid"] = sid
        p["role"] = role or p.get("role") or "guest"
        if username:
            p["username"] = username
        p["ready"] = bool(p.get("ready", False))
        p["last_seen"] = time.time()
        players[player_id] = p

        # Only a client that joined as host may claim host. Guests must never
        # become host just because they connected before the host's socket.
        if room.get("host_player_id") is None and role == "host":
            room["host_player_id"] = player_id

    join_room(code)
    socketio.emit("mp_room_update", _mp_room_snapshot(code, you_sid=sid), to=code)


@socketio.on("mp_leave")
def mp_leave(data):
    code = _mp_norm_code(data.get("code"))
    sid = request.sid
    player_id = (data.get("playerId") or "").strip()
    leave_room(code)
    with _MP_LOCK:
        room = _MP_ROOMS.get(code)
        if not room:
            return
        _mp_cleanup_room(room)

        if player_id:
            room["players"].pop(player_id, None)
        else:
            # fallback: remove whoever has this sid
            for pid, p in list(room["players"].items()):
                if p.get("sid") == sid:
                    room["players"].pop(pid, None)

        _mp_cleanup_room(room)

        if len(room["players"]) == 0:
            _MP_ROOMS.pop(code, None)
            return
    socketio.emit("mp_room_update", _mp_room_snapshot(code), to=code)


@socketio.on("disconnect")
def mp_disconnect():
    sid = request.sid
    emptied: list[str] = []
    touched: set[str] = set()
    with _MP_LOCK:
        for code, room in list(_MP_ROOMS.items()):
            players: dict = room.get("players") or {}
            for pid, p in players.items():
                if p.get("sid") == sid:
                    # Don't delete immediately; allow reconnect rebind.
                    p["sid"] = None
                    p["last_seen"] = time.time()
                    touched.add(code)
                    break

            _mp_cleanup_room(room)
            if len(room.get("players") or {}) == 0:
                emptied.append(code)
        for code in emptied:
            _MP_ROOMS.pop(code, None)
    for code in touched:
        socketio.emit("mp_room_update", _mp_room_snapshot(code), to=code)


@socketio.on("mp_ready")
def mp_ready(data):
    code = _mp_norm_code(data.get("code"))
    ready = bool(data.get("ready"))
    sid = request.sid
    player_id = (data.get("playerId") or "").strip()

    with _MP_LOCK:
        room = _MP_ROOMS.get(code)
        if not room:
            socketio.emit("mp_error", {"error": "Room not found."}, to=sid)
            return
        _mp_cleanup_room(room)
        players: dict = room["players"]
        if not player_id or player_id not in players:
            socketio.emit("mp_error", {"error": "Not in room."}, to=sid)
            return
        players[player_id]["ready"] = ready
        players[player_id]["last_seen"] = time.time()
    socketio.emit("mp_room_update", _mp_room_snapshot(code), to=code)


@socketio.on("mp_start_request")
def mp_start_request(data):
    code = _mp_norm_code(data.get("code"))
    sid = request.sid
    player_id = (data.get("playerId") or "").strip()

    with _MP_LOCK:
        room = _MP_ROOMS.get(code)
        if not room:
            socketio.emit("mp_error", {"error": "Room not found."}, to=sid)
            return
        _mp_cleanup_room(room)
        if room.get("host_player_id") != player_id:
            socketio.emit("mp_error", {"error": "Only the host can start."}, to=sid)
            return

        players = list((room.get("players") or {}).values())
        connected_players = [p for p in players if p.get("sid")]
        if len(connected_players) < 2:
            socketio.emit("mp_error", {"error": "Need at least 2 players to start."}, to=sid)
            return
        if not all(bool(p.get("ready")) for p in connected_players):
            socketio.emit("mp_error", {"error": "All connected players must be ready."}, to=sid)
            return

    socketio.emit("mp_start", {"code": code}, to=code)


@socketio.on("mp_set_username")
def mp_set_username(data):
    code = _mp_norm_code(data.get("code"))
    sid = request.sid
    player_id = (data.get("playerId") or "").strip()
    username = (data.get("username") or "").strip()
    with _MP_LOCK:
        room = _MP_ROOMS.get(code)
        if not room:
            return
        _mp_cleanup_room(room)
        p = (room.get("players") or {}).get(player_id)
        if not p:
            socketio.emit("mp_error", {"error": "Not in room."}, to=sid)
            return
        p["username"] = username
        p["last_seen"] = time.time()
    socketio.emit("mp_room_update", _mp_room_snapshot(code), to=code)


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
            turn_speed = 100

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
            try:
                print(f"FINCH MOVE: setMotors({left_speed}, {right_speed})")
                finch.setMotors(left_speed, right_speed)
            except Exception as e:
                print("FINCH MOVE ERROR:", str(e))
            prev_left = left_speed
            prev_right = right_speed

        time.sleep(0.005)


def sensors():
    global avoid_obstacle

    if finch is None:
        return

    prev_incline = [""] * 10

    while True:
        try:
            distance = finch.getDistance()
            left_line = finch.getLine("L")
            right_line = finch.getLine("R")
            orientation = finch.getOrientation()
        except Exception as e:
            print("FINCH SENSOR ERROR:", str(e))
            time.sleep(0.2)
            continue
        incline_state = ""

        prev_incline = prev_incline[1:] + [orientation]
        last_ten_level = sum(1 for x in prev_incline if x == "Level")

        incline_state = "Level" if last_ten_level > 6 else "In between"

        if distance < 15:
            print(f"FINCH OBSTACLE: distance={distance} < 15 → backing up")
            avoid_obstacle = True
            finch.stop()
            finch.playNote(60, 1)
            finch.setMove("B", 20, 50)
            time.sleep(0.5)
            finch.stop()
            avoid_obstacle = False

        if left_line < 50 or right_line < 50:
            print(f"FINCH LINE: left={left_line} right={right_line} → stop + LEDs + beep")
            finch.playNote(40, 1)
            finch.setBeak(100, 100, 0)
            finch.setTail("all", 100, 100, 0)
            finch.stop()

        if incline_state != "Level":
            finch.setDisplay([1] * 25)
        else:
            finch.setDisplay([0] * 25)

        time.sleep(0.05)


def _ensure_motor_threads() -> None:
    """Start motor/sensor loops once Finch is available (startup or after a successful test)."""
    global _MOTOR_THREADS_STARTED
    if finch is None or _MOTOR_THREADS_STARTED:
        return
    _MOTOR_THREADS_STARTED = True
    threading.Thread(target=inputs, daemon=True).start()
    threading.Thread(target=sensors, daemon=True).start()


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
    # Ensure /images/... is always served even if this route matches first.
    if page.startswith("images/"):
        return send_from_directory(app.static_folder, page[len("images/") :])

    # Serve other HTML templates by filename (e.g. /multiplayer-join.html).
    if page.endswith(".html") and (_FRONTEND_DIR / page).is_file():
        return render_template(page)

    # Serve frontend assets living next to the templates (styles.css, script.js).
    if page.endswith((".css", ".js")) and (_FRONTEND_DIR / page).is_file():
        return send_from_directory(_FRONTEND_DIR, page)

    return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    _ensure_motor_threads()

    host = os.environ.get("BIRDBRAIN_HOST", "127.0.0.1")
    port = int(os.environ.get("BIRDBRAIN_PORT", "5001"))
    socketio.run(
        app,
        host=host,
        port=port,
        debug=True,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
