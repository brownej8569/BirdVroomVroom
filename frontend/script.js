function goToPage(page) {
  window.location.href = `/${page}`;
}

function _teamName() {
  return localStorage.getItem("teamName") || "Skipper";
}

function _setTeamNameLabel() {
  const el = document.getElementById("team-name");
  if (el) el.textContent = _teamName();
}

async function openBluetoothConnector() {
  try {
    const response = await fetch("/open_connector", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const data = await response.json();
    if (data.status === "success") {
      alert(data.message || "Opened Bluebird Connector.");
    } else {
      alert(
        data.message ||
          "Could not open Bluebird Connector automatically. Open it from the Start menu, plug in the USB dongle, then connect your Finch."
      );
    }
  } catch (err) {
    alert("Could not reach the server: " + err.message);
  }
}

async function runScript(endpoint) {
  const outputElement = document.getElementById("output");
  if (outputElement) outputElement.textContent = `Sending request to /${endpoint}...`;

  try {
    const response = await fetch(`/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const data = await response.json();

    if (outputElement) {
      if (data.status === "success") outputElement.textContent = "Success: " + data.output;
      else outputElement.textContent = "Error: " + (data.message || "Unknown error");
    }
  } catch (err) {
    if (outputElement) outputElement.textContent = "Network Error: " + err.message;
  }
}

async function pauseRobot() {
  try {
    const response = await fetch("/robot/pause", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const data = await response.json();
    const output = document.getElementById("output");
    if (output) output.textContent = (data.message || data.status || "Pause") + "";
  } catch (err) {
    alert("Pause failed: " + err.message);
  }
}

function _normControlKey(e) {
  const k = e.key;
  if (k === " " || k === "Spacebar") return "space";
  if (k === "Shift") return "shift";
  return k.length === 1 ? k.toLowerCase() : null;
}

function _emitControl(socket, key, pressed) {
  const payloadKey = key === "space" ? "space" : key;
  socket.emit("control_stuff", { currkey: payloadKey, pressed });
}

function initFinchKeyboardControls() {
  const root = document.querySelector(".controls-screen");
  if (!root || typeof io === "undefined") return;

  const socket = io();
  const allowed = new Set(["w", "a", "s", "d", "shift", "space"]);

  document.addEventListener("keydown", (e) => {
    if (!document.querySelector(".controls-screen")) return;
    const nk = _normControlKey(e);
    if (!nk || !allowed.has(nk) || e.repeat) return;
    if (nk === "space") e.preventDefault();
    _emitControl(socket, nk, true);
  });

  document.addEventListener("keyup", (e) => {
    if (!document.querySelector(".controls-screen")) return;
    const nk = _normControlKey(e);
    if (!nk || !allowed.has(nk)) return;
    if (nk === "space") e.preventDefault();
    _emitControl(socket, nk, false);
  });
}

function createRoom() {
  const code = Math.random().toString(36).slice(2, 8).toUpperCase();
  localStorage.setItem("roomCode", code);
  alert(
    `Local prototype room code: ${code}\n\nNext step (server): host a real room so all Finches join the same session. For now this is saved in your browser.`
  );
  goToPage("multiplayer-controls.html");
}

function joinRoom() {
  const code = document.getElementById("roomCode")?.value?.trim();
  if (!code) {
    alert("Enter a room code first.");
    return;
  }
  localStorage.setItem("roomCode", code);
  goToPage("multiplayer-controls.html");
}

document.addEventListener("DOMContentLoaded", () => {
  _setTeamNameLabel();
  initFinchKeyboardControls();
});
