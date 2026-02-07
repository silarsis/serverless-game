import React, { useCallback, useEffect, useRef, useState } from "react";

const WS_URL = process.env.REACT_APP_WS_URL || "ws://localhost:4566";

const Game = () => {
  const [events, setEvents] = useState([]);
  const [command, setCommand] = useState("");
  const [connected, setConnected] = useState(false);
  const [commandHistory, setCommandHistory] = useState([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const wsRef = useRef(null);
  const eventsEndRef = useRef(null);

  const addEvent = useCallback((event) => {
    setEvents((prev) => [...prev.slice(-200), event]);
  }, []);

  const connect = useCallback(() => {
    const token = window.localStorage.getItem("jwt");
    if (!token) return;

    const ws = new WebSocket(`${WS_URL}?token=${token}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      addEvent({ type: "system", message: "Connected to server." });
    };

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        addEvent(data);
      } catch {
        addEvent({ type: "raw", message: e.data });
      }
    };

    ws.onclose = () => {
      setConnected(false);
      addEvent({ type: "system", message: "Disconnected from server." });
      // Auto-reconnect after 3 seconds
      setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      addEvent({ type: "system", message: "Connection error." });
    };
  }, [addEvent]);

  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const sendCommand = (cmd) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    const parts = cmd.trim().split(/\s+/);
    const action = parts[0];
    const args = parts.slice(1);

    let message;
    if (action === "possess") {
      message = {
        command: "possess",
        data: { entity_uuid: args[0], entity_aspect: args[1] || "Land" },
      };
    } else if (action === "move" || action === "go") {
      message = { command: "move", data: { direction: args[0] } };
    } else if (["north", "south", "east", "west", "up", "down"].includes(action)) {
      message = { command: "move", data: { direction: action } };
    } else if (action === "look" || action === "l") {
      message = { command: "look", data: {} };
    } else {
      message = { command: action, data: args.length ? { text: args.join(" ") } : {} };
    }

    wsRef.current.send(JSON.stringify(message));
    addEvent({ type: "command", message: `> ${cmd}` });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!command.trim()) return;
    setCommandHistory((prev) => [...prev, command]);
    setHistoryIndex(-1);
    sendCommand(command);
    setCommand("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "ArrowUp") {
      e.preventDefault();
      const newIndex = historyIndex === -1 ? commandHistory.length - 1 : Math.max(0, historyIndex - 1);
      if (commandHistory[newIndex]) {
        setHistoryIndex(newIndex);
        setCommand(commandHistory[newIndex]);
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (historyIndex === -1) return;
      const newIndex = historyIndex + 1;
      if (newIndex >= commandHistory.length) {
        setHistoryIndex(-1);
        setCommand("");
      } else {
        setHistoryIndex(newIndex);
        setCommand(commandHistory[newIndex]);
      }
    }
  };

  const renderEvent = (event, index) => {
    switch (event.type) {
      case "system":
        return <div key={index} style={styles.system}>{event.message}</div>;
      case "command":
        return <div key={index} style={styles.command}>{event.message}</div>;
      case "error":
        return <div key={index} style={styles.error}>{event.message}</div>;
      case "look":
        return (
          <div key={index} style={styles.look}>
            <div style={styles.description}>{event.description}</div>
            {event.exits?.length > 0 && (
              <div style={styles.exits}>Exits: {event.exits.join(", ")}</div>
            )}
            {event.coordinates && (
              <div style={styles.coords}>[{event.coordinates.join(", ")}]</div>
            )}
          </div>
        );
      case "move":
        return (
          <div key={index} style={styles.move}>
            <div>You move {event.direction}.</div>
            <div style={styles.description}>{event.description}</div>
            {event.exits?.length > 0 && (
              <div style={styles.exits}>Exits: {event.exits.join(", ")}</div>
            )}
          </div>
        );
      default:
        return (
          <div key={index} style={styles.raw}>
            {event.message || JSON.stringify(event)}
          </div>
        );
    }
  };

  const handleLogout = () => {
    window.localStorage.removeItem("jwt");
    window.location.href = "/";
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span>Serverless Game</span>
        <span style={styles.status}>
          {connected ? "Connected" : "Disconnected"}
        </span>
        <button onClick={handleLogout} style={styles.logout}>Logout</button>
      </div>
      <div style={styles.events}>
        {events.map(renderEvent)}
        <div ref={eventsEndRef} />
      </div>
      <form onSubmit={handleSubmit} style={styles.inputRow}>
        <span style={styles.prompt}>&gt; </span>
        <input
          type="text"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={handleKeyDown}
          style={styles.input}
          placeholder={connected ? "Enter command..." : "Connecting..."}
          disabled={!connected}
          autoFocus
        />
      </form>
    </div>
  );
};

const styles = {
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    backgroundColor: "#1a1a2e",
    color: "#e0e0e0",
    fontFamily: "'Courier New', Courier, monospace",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "8px 16px",
    backgroundColor: "#16213e",
    borderBottom: "1px solid #0f3460",
    fontSize: "14px",
  },
  status: {
    color: "#53d769",
    fontSize: "12px",
  },
  logout: {
    background: "none",
    border: "1px solid #555",
    color: "#aaa",
    padding: "4px 8px",
    cursor: "pointer",
    fontFamily: "inherit",
    fontSize: "12px",
  },
  events: {
    flex: 1,
    overflowY: "auto",
    padding: "12px 16px",
  },
  system: { color: "#888", marginBottom: "4px", fontStyle: "italic" },
  command: { color: "#64b5f6", marginBottom: "4px" },
  error: { color: "#ef5350", marginBottom: "4px" },
  look: { marginBottom: "8px" },
  description: { color: "#e0e0e0", marginBottom: "4px" },
  exits: { color: "#81c784", fontSize: "13px" },
  coords: { color: "#666", fontSize: "11px" },
  move: { marginBottom: "8px", color: "#b0bec5" },
  raw: { color: "#ccc", marginBottom: "4px" },
  inputRow: {
    display: "flex",
    alignItems: "center",
    padding: "8px 16px",
    borderTop: "1px solid #0f3460",
    backgroundColor: "#16213e",
  },
  prompt: { color: "#64b5f6", marginRight: "4px", fontSize: "16px" },
  input: {
    flex: 1,
    background: "none",
    border: "none",
    color: "#e0e0e0",
    fontSize: "16px",
    fontFamily: "'Courier New', Courier, monospace",
    outline: "none",
  },
};

export default Game;
