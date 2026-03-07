from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from backend.lib.BirdBrain import Finch
import threading
import time

finch = Finch('A')
#keys_active = set()
app = Flask(__name__, template_folder='frontend')
socketio = SocketIO(app, cors_allowed_origins="*")
avoid_obstacle = False
#CORS(app)

# given state of whether the control buttons are pressed down or not
control_state = {"w" : False,
                 "a": False,
                 "s": False,
                 "d": False,
                 "shift": False,
                 "r": False}

# Route to serve the main HTML page
@app.route('/')
def index():
    return render_template('index.html')

# API endpoint to serve data to the frontend
@app.route('/api/data')
def get_data():
    # You can return any data here (e.g., from a database)
    data = {"message": "Hello from the Python backend!"}
    return jsonify(data)

# Our socket connecting the key inputs from the frontend (currkeys and those
# that have been pressed). Updates only for the keys that actually control stuff.
@socketio.on("control_stuff")
def control_stuff(data):
    key = data.get("currkey").lower()
    pressed = data.get("pressed")
    
    if key in control_state:
        control_state[key] = pressed

#@app.route('/controller', methods=['POST'])
#def controller():
#    data = request.json
#    key = data.get('key')
#    pressed = data.get('pressed')
#
#    if pressed:
#        keys_active.add(key.lower())
#    else:
#        keys_active.discard(key.lower())
#        
#    return jsonify({"status": "ok"})

def inputs():
    prev_left = None
    prev_right = None

    while True:
        # Mini Key Library
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
            left_speed = left_speed + move_speed
            right_speed = right_speed + move_speed

        if back:
            left_speed = left_speed - move_speed
            right_speed = right_speed - move_speed

        if left:
            left_speed = left_speed - turn_speed
            right_speed = right_speed + turn_speed

        if right:
            left_speed = left_speed + turn_speed
            right_speed = right_speed - turn_speed

        left_speed = max(-100, min(100, left_speed))
        right_speed = max(-100, min(100, right_speed))

        if left_speed != prev_left or right_speed != prev_right:
            finch.setMotors(left_speed, right_speed)
            prev_left = left_speed
            prev_right = right_speed

        time.sleep(0.005)

def sensors():
    prev_incline = ["", "", "", "", "", "", "", "", "", ""]
    
    while True:
        distance = finch.getDistance()
        left_line = finch.getLine('L')
        right_line = finch.getLine('R')
        last_ten_level = 0
        incline_state = ""

        for i in range(len(prev_incline) - 1):
            prev_incline[i] = prev_incline[i + 1]    
        prev_incline[-1] = finch.getOrientation()

        for i in range(len(prev_incline)):
            if prev_incline[i] == "Level":
                last_ten_level = last_ten_level + 1

        if last_ten_level > 6:
            incline_state = "Level"
        else:
            incline_state = "In between"

        if distance < 15:
            avoid_obstacle = True
            finch.stop()
            finch.playNote(60, 1)
            finch.setMove('B', 20, 50)
            time.sleep(0.5)
            finch.stop()
            avoid_obstacle = False

        if left_line < 50 or right_line < 50:
            finch.playNote(40, 1)
            finch.setBeak(100, 100, 0)
            finch.setTail("all",100, 100, 0)
            finch.stop()

        if incline_state != "Level":
            finch.setDisplay([1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1])

        finch.setDisplay([0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0])
        time.sleep(0.05)

if __name__ == '__main__':
    threading.Thread(target=inputs, daemon=True).start()
    threading.Thread(target=sensors, daemon=True).start()
    socketio.run(app, debug=True, use_reloader=False)

#@app.route('/first_finch_test', methods=['POST'])
#def first_finch_test():
#    script_path = os.path.join('backend', 'meow.py')
#    try:
#        result = subprocess.check_output(
#            [sys.executable, script_path],
#            text=True,
#            stderr=subprocess.STDOUT
#        )
#        return jsonify({"status": "success", "output": result.strip()})
#
#    except FileNotFoundError:
#        error_msg = f"Error: The file '{script_path}' was not found."
#        print(error_msg)
#        return jsonify({"status": "error", "message": error_msg}), 500
#
#    except Exception as e:
#        print(f"General Error: {str(e)}")
#        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500


