function goToPage(page) {
  window.location.href = `/${page}`;
}

function getPlayerId() {
  // Per-tab identity so 3 windows = 3 players.
  let pid = window.sessionStorage.getItem("playerId");
  if (!pid) {
    pid = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`.toUpperCase();
    window.sessionStorage.setItem("playerId", pid);
  }
  return pid;
}

function getUsername() {
  return (window.localStorage.getItem("finchName") || "").trim();
}

function saveUsername(name) {
  window.localStorage.setItem("finchName", (name || "").trim());
}

/** Per-tab name for multiplayer (localStorage is shared across all windows on this origin). */
const MP_DISPLAY_NAME_KEY = "mpDisplayName";

function getMpDisplayName() {
  return (window.sessionStorage.getItem(MP_DISPLAY_NAME_KEY) || "").trim();
}

function setMpDisplayName(name) {
  window.sessionStorage.setItem(MP_DISPLAY_NAME_KEY, (name || "").trim());
}

/** If this tab has no multiplayer name yet, default once from saved finchName (singleplayer). */
function seedMpDisplayNameIfNeeded() {
  if (!getMpDisplayName() && getUsername()) {
    setMpDisplayName(getUsername());
  }
}

function finchTestResultText(data) {
  if (!data || typeof data !== "object") return "Finch test complete.";
  const parts = [data.message || "Finch test complete."];
  if (data.detail) parts.push(String(data.detail));
  return parts.join("\n");
}

async function runFinchTest() {
  console.log("[singleplayer] RUN FINCH TEST clicked");
  const out = document.getElementById("sp-output");
  if (out) out.textContent = "Running Finch test...";

  try {
    const res = await fetch("/api/finch/test", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data?.error || data?.message || `HTTP ${res.status}`);
    }
    if (out) out.textContent = finchTestResultText(data);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (out) out.textContent = `Finch connection failed.\n${msg}`;
  }
}

function initSingleplayerFinchControls() {
  const root = document.querySelector(".singleplayer-screen");
  if (!root || typeof io === "undefined") return;
  if (root.dataset.spFinchControls === "1") return;
  root.dataset.spFinchControls = "1";

  const socket = io();
  const controlKeys = new Set(["w", "a", "s", "d", "shift", "space"]);

  const isTypingFocus = () => {
    const el = document.activeElement;
    if (!el) return false;
    const tag = (el.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || Boolean(el.isContentEditable);
  };

  const normalizeKey = (e) => {
    const k = e.key;
    if (k === " " || k === "Spacebar") return "space";
    if (k === "Shift") return "shift";
    if (k.length === 1) return k.toLowerCase();
    return null;
  };

  const emitControl = (key, pressed) => {
    socket.emit("control_stuff", { currkey: key, pressed });
  };

  document.addEventListener(
    "keydown",
    (e) => {
      if (!document.body.contains(root)) return;
      if (isTypingFocus()) return;
      const nk = normalizeKey(e);
      if (!nk || !controlKeys.has(nk)) return;
      if (e.repeat) return;
      if (nk === "space") e.preventDefault();
      emitControl(nk, true);
    },
    true
  );

  document.addEventListener(
    "keyup",
    (e) => {
      if (!document.body.contains(root)) return;
      if (isTypingFocus()) return;
      const nk = normalizeKey(e);
      if (!nk || !controlKeys.has(nk)) return;
      if (nk === "space") e.preventDefault();
      emitControl(nk, false);
    },
    true
  );

  window.addEventListener("blur", () => {
    for (const key of controlKeys) emitControl(key, false);
  });

  const btnKeyFor = (btn) => {
    if (btn.classList.contains("sp-keybtn--w")) return "w";
    if (btn.classList.contains("sp-keybtn--a")) return "a";
    if (btn.classList.contains("sp-keybtn--s")) return "s";
    if (btn.classList.contains("sp-keybtn--d")) return "d";
    if (btn.classList.contains("sp-keybtn--space")) return "space";
    return null;
  };

  root.querySelectorAll(".sp-keybtn").forEach((btn) => {
    const key = btnKeyFor(btn);
    if (!key) return;
    const up = (ev) => {
      ev.preventDefault();
      emitControl(key, false);
    };
    btn.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      emitControl(key, true);
    });
    btn.addEventListener("pointerup", up);
    btn.addEventListener("pointerleave", up);
    btn.addEventListener("pointercancel", up);
  });
}

function initSingleplayerPage() {
  const input = document.getElementById("sp-username");
  if (input) {
    const saved = getUsername();
    if (saved) input.value = saved;

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const name = (input.value || "").trim();
        saveUsername(name);
        input.blur();

        const out = document.getElementById("sp-output");
        if (out && name) out.textContent = `Saved username: ${name}`;
        if (out && !name) out.textContent = "Username cleared.";
      }
    });
  }

  initSingleplayerFinchControls();
}

function initMultiplayerEntryPage() {
  const createBtn = document.getElementById("mp-create");
  const joinBtn = document.getElementById("mp-join");
  const codeInput = document.getElementById("mp-code");
  const status = document.getElementById("mp-status");

  let mode = null; // "host" | "guest" | null

  const setStatus = (msg) => {
    if (status) status.textContent = msg || "";
  };

  const normalizeCode = (value) =>
    String(value || "")
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, "")
      .slice(0, 6);

  if (codeInput) {
    codeInput.addEventListener("input", () => {
      const v = normalizeCode(codeInput.value);
      if (codeInput.value !== v) codeInput.value = v;
    });
  }

  const resetUI = () => {
    setStatus("");
    if (codeInput) {
      codeInput.readOnly = false;
      codeInput.value = "";
    }
  };

  if (createBtn) {
    createBtn.addEventListener("click", async () => {
      if (mode !== "host") resetUI();
      mode = "host";
      setStatus("Creating room...");

      try {
        const res = await fetch("/api/mp/create", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data?.code) throw new Error(data?.error || "Failed to create room.");

        const code = normalizeCode(data.code);
        seedMpDisplayNameIfNeeded();
        // Don't leave host stuck on entry page—go to lobby.
        window.location.href = `/multiplayer-lobby.html?code=${encodeURIComponent(code)}&role=host`;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setStatus(`Error: ${msg}`);
      }
    });
  }

  if (joinBtn) {
    joinBtn.addEventListener("click", async () => {
      if (mode !== "guest") {
        // switching from host → guest should clear previous status/code
        resetUI();
      }
      mode = "guest";

      const code = normalizeCode(codeInput?.value);
      if (!code || code.length < 6) {
        setStatus("Enter a 6-character room code first.");
        return;
      }

      setStatus("Checking room...");
      try {
        const res = await fetch(`/api/mp/exists/${encodeURIComponent(code)}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data?.exists) {
          setStatus("Room not found. Check the code and try again.");
          return;
        }
        if (data?.full) {
          setStatus("Room is full.");
          return;
        }
        seedMpDisplayNameIfNeeded();
        window.location.href = `/multiplayer-lobby.html?code=${encodeURIComponent(code)}&role=guest`;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setStatus(`Error: ${msg}`);
      }
    });
  }
}

function initMultiplayerLobbyPage() {
  const params = new URLSearchParams(window.location.search);
  const code = (params.get("code") || "").toUpperCase();
  const role = params.get("role") || "guest";
  const playerId = getPlayerId();

  const codeEl = document.getElementById("mp-lobby-code");
  const msgEl = document.getElementById("mp-lobby-msg");
  const countEl = document.getElementById("mp-lobby-count");
  const playersEl = document.getElementById("mp-lobby-players");
  const nameInput = document.getElementById("mp-lobby-username");
  const readyBtn = document.getElementById("mp-ready");
  const startBtn = document.getElementById("mp-start");

  if (codeEl) codeEl.value = code;
  if (msgEl) msgEl.textContent = role === "host" ? "Waiting for player 2..." : "Joining room...";

  const socket = window.io ? window.io() : null;
  if (!socket) return;

  if (nameInput) {
    seedMpDisplayNameIfNeeded();
    nameInput.value = getMpDisplayName();
    nameInput.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      const name = (nameInput.value || "").trim();
      setMpDisplayName(name);
      saveUsername(name);
      nameInput.blur();
      socket.emit("mp_set_username", { code, playerId, username: name });
    });
  }

  let isReady = false;
  // Host is determined only from backend (host_player_id), not URL alone.
  let isHost = false;
  let playersCount = 0;
  let maxPlayers = 3;
  let readyCount = 0;
  let backendCanStart = null; // boolean | null

  const setReadyUI = () => {
    if (!readyBtn) return;
    readyBtn.textContent = isReady ? "READY ✓" : "READY";
  };
  setReadyUI();

  const setStartUI = () => {
    if (!startBtn) return;
    if (!isHost) {
      startBtn.hidden = true;
      startBtn.disabled = true;
      return;
    }
    startBtn.hidden = false;
    const canStart =
      typeof backendCanStart === "boolean"
        ? backendCanStart
        : playersCount >= 2 && readyCount === playersCount;
    startBtn.disabled = !canStart;
  };
  setStartUI();

  socket.on("mp_error", (d) => {
    const err = d?.error || "Multiplayer error.";
    if (msgEl) msgEl.textContent = err;
    // Avoid "Room is full" next to a stale "0/3" from the initial HTML before any snapshot.
    if (countEl && /full/i.test(String(err))) {
      countEl.textContent = "Room is full (3/3).";
    }
  });

  socket.on("mp_room_update", (snap) => {
    const players = Array.isArray(snap?.players) ? snap.players : [];
    const hostPlayerId = snap?.host_player_id || null;
    maxPlayers = Number(snap?.max_players) || 3;

    // Authoritative counts from backend (fallback to local derive)
    playersCount = Number.isFinite(snap?.connectedCount) ? Number(snap.connectedCount) : players.filter((p) => p && p.connected).length;
    readyCount = Number.isFinite(snap?.readyConnectedCount) ? Number(snap.readyConnectedCount) : players.filter((p) => p && p.connected && p.ready).length;
    backendCanStart = typeof snap?.canStart === "boolean" ? Boolean(snap.canStart) : null;
    if (countEl) countEl.textContent = `${playersCount}/${maxPlayers} players connected`;

    const selfRow = players.find((p) => p && p.player_id === playerId);
    const me = selfRow && selfRow.connected ? selfRow : null;
    isReady = Boolean(me?.ready);
    isHost = Boolean(hostPlayerId && hostPlayerId === playerId);
    const serverName = (selfRow?.username || "").trim();
    if (serverName) {
      setMpDisplayName(serverName);
      if (nameInput) nameInput.value = serverName;
    }
    setReadyUI();
    if (msgEl && typeof snap?.statusMessage === "string") msgEl.textContent = snap.statusMessage;
    setStartUI();

    if (playersEl) {
      const lines = players
        .filter((p) => p && p.player_id)
        .map((p) => {
          const conn = p.connected ? "●" : "○";
          const rd = p.ready ? "READY" : "not ready";
          const host = hostPlayerId && p.player_id === hostPlayerId ? " [HOST]" : "";
          const uname = (p.username || "").trim() || p.player_id;
          return `${conn} ${uname} — ${rd}${host}`;
        });
      playersEl.textContent = lines.length ? lines.join("\n") : "";
    }
  });

  socket.on("mp_start", (d) => {
    const room = (d?.code || code || "").toUpperCase();
    window.location.href = `/multiplayer-controls.html?code=${encodeURIComponent(room)}&role=${encodeURIComponent(role)}`;
  });

  const joinUsername = (nameInput?.value || "").trim() || getMpDisplayName() || getUsername();
  setMpDisplayName(joinUsername);
  socket.emit("mp_join", { code, role, playerId, username: joinUsername });

  if (readyBtn) {
    readyBtn.addEventListener("click", () => {
      isReady = !isReady;
      setReadyUI();
      socket.emit("mp_ready", { code, playerId, ready: isReady });
    });
  }

  if (startBtn) {
    startBtn.addEventListener("click", () => {
      socket.emit("mp_start_request", { code, playerId });
    });
  }

  // No mp_leave on navigation; rely on disconnect + grace window.
}

function initMultiplayerControlsPage() {
  const params = new URLSearchParams(window.location.search);
  const code = (params.get("code") || "").toUpperCase();
  const role = params.get("role") || "guest";
  const playerId = getPlayerId();

  const input = document.getElementById("mpc-username");
  const out = document.getElementById("mpc-output");
  const roomDisp = document.getElementById("mpc-room-display");
  if (roomDisp) roomDisp.textContent = code ? `Room: ${code}` : "";

  const syncName = () => {
    seedMpDisplayNameIfNeeded();
    const name = getMpDisplayName();
    if (input) input.value = name ? name.toUpperCase() : "";
  };
  syncName();

  const socket = window.io ? window.io() : null;
  if (socket) {
    socket.emit("mp_join", { code, role, playerId, username: getMpDisplayName() || getUsername() });

    socket.on("mp_room_update", (snap) => {
      const players = Array.isArray(snap?.players) ? snap.players : [];
      const selfRow = players.find((p) => p && p.player_id === playerId);
      const serverName = (selfRow?.username || "").trim();
      if (serverName) {
        setMpDisplayName(serverName);
        syncName();
      }
    });
  }

  if (input) {
    input.readOnly = false;
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const name = (input.value || "").trim();
        setMpDisplayName(name);
        saveUsername(name);
        syncName();
        input.blur();
        if (socket) socket.emit("mp_set_username", { code, playerId, username: name });
      }
    });
  }

  const btn = document.getElementById("mpc-finch-test");
  if (btn) {
    btn.addEventListener("click", async () => {
      if (out) out.textContent = "Running Finch test...";
      try {
        const res = await fetch("/api/finch/test", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.error || `HTTP ${res.status}`);
        if (out) out.textContent = finchTestResultText(data);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (out) out.textContent = `Finch connection failed.\n${msg}`;
      }
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  if (document.querySelector(".singleplayer-screen")) initSingleplayerPage();
  if (document.querySelector(".multiplayer-screen")) initMultiplayerEntryPage();
  if (document.querySelector(".multiplayer-lobby-screen")) initMultiplayerLobbyPage();
  if (document.querySelector(".multiplayer-controls-screen")) initMultiplayerControlsPage();
});
