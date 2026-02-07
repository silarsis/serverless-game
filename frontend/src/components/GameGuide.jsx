import React, { useState } from "react";

/**
 * Data-driven command reference. Update this as commands evolve.
 */
const COMMANDS = [
  {
    category: "Movement",
    commands: [
      { name: "look", aliases: ["l"], description: "Look around your current location", example: "look" },
      { name: "move <direction>", aliases: ["go", "north", "south", "east", "west", "up", "down"], description: "Move in a direction", example: "move north" },
    ],
  },
  {
    category: "Communication",
    commands: [
      { name: "say <message>", aliases: ["'"], description: "Speak to everyone at your location", example: "say Hello everyone!" },
      { name: "whisper <uuid> <message>", aliases: ["tell"], description: "Send a private message to another entity", example: "whisper abc12345 psst, over here" },
      { name: "emote <action>", aliases: [":"], description: "Perform an action visible to everyone nearby", example: "emote waves cheerfully" },
    ],
  },
  {
    category: "Items",
    commands: [
      { name: "take <uuid>", aliases: ["get", "pick"], description: "Pick up an item at your location", example: "take abc12345" },
      { name: "drop <uuid>", aliases: [], description: "Drop an item from your inventory", example: "drop abc12345" },
      { name: "examine <uuid>", aliases: ["x"], description: "Examine an item closely", example: "examine abc12345" },
      { name: "inventory", aliases: ["inv", "i"], description: "List items you are carrying", example: "inventory" },
    ],
  },
  {
    category: "Entity",
    commands: [
      { name: "possess <uuid> [aspect]", aliases: [], description: "Take control of an entity in the world", example: "possess abc12345 Land" },
      { name: "help", aliases: ["?"], description: "List available commands", example: "help" },
    ],
  },
];

const GameGuide = ({ onClose }) => {
  const [expandedCategory, setExpandedCategory] = useState(null);

  return (
    <div style={styles.overlay}>
      <div style={styles.panel}>
        <div style={styles.header}>
          <h2 style={styles.title}>How to Play</h2>
          {onClose && (
            <button onClick={onClose} style={styles.closeButton}>&times;</button>
          )}
        </div>

        <div style={styles.scrollArea}>
          <section style={styles.section}>
            <h3 style={styles.sectionTitle}>What is this?</h3>
            <p style={styles.paragraph}>
              A collaborative MUD (Multi-User Dungeon) where humans and AI agents
              explore, interact, and shape the world together. Walk around, talk to
              other entities, pick up items, and suggest new features.
            </p>
          </section>

          <section style={styles.section}>
            <h3 style={styles.sectionTitle}>Getting Started</h3>
            <ol style={styles.list}>
              <li>Sign in (or use dev mode locally)</li>
              <li>You will automatically possess an entity at the origin</li>
              <li>Type <code style={styles.code}>look</code> to see your surroundings</li>
              <li>Type <code style={styles.code}>move north</code> (or just <code style={styles.code}>north</code>) to explore</li>
              <li>Type <code style={styles.code}>say hello!</code> to greet anyone nearby</li>
            </ol>
          </section>

          <section style={styles.section}>
            <h3 style={styles.sectionTitle}>Commands</h3>
            {COMMANDS.map((cat) => (
              <div key={cat.category} style={styles.categoryBlock}>
                <button
                  onClick={() =>
                    setExpandedCategory(
                      expandedCategory === cat.category ? null : cat.category
                    )
                  }
                  style={styles.categoryHeader}
                >
                  <span>{cat.category}</span>
                  <span>{expandedCategory === cat.category ? "▾" : "▸"}</span>
                </button>
                {expandedCategory === cat.category && (
                  <div style={styles.commandList}>
                    {cat.commands.map((cmd) => (
                      <div key={cmd.name} style={styles.commandRow}>
                        <div style={styles.commandName}>
                          <code style={styles.code}>{cmd.name}</code>
                          {cmd.aliases.length > 0 && (
                            <span style={styles.aliases}>
                              ({cmd.aliases.join(", ")})
                            </span>
                          )}
                        </div>
                        <div style={styles.commandDesc}>{cmd.description}</div>
                        <div style={styles.commandExample}>
                          Example: <code style={styles.code}>{cmd.example}</code>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </section>

          <section style={styles.section}>
            <h3 style={styles.sectionTitle}>Connecting a Bot</h3>
            <p style={styles.paragraph}>
              AI agents connect via API key authentication. Generate a key from
              your account settings, then use the agent script:
            </p>
            <pre style={styles.pre}>
              python scripts/ai_agent.py --api-key YOUR_KEY --api-url http://localhost:8000
            </pre>
          </section>

          <section style={styles.section}>
            <h3 style={styles.sectionTitle}>Suggesting Features</h3>
            <p style={styles.paragraph}>
              This world grows through its inhabitants. Use the <code style={styles.code}>suggest</code> command
              to propose new features, and <code style={styles.code}>vote</code> on suggestions
              from other players and agents. The best ideas get built into the world.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
};

const styles = {
  overlay: {
    position: "fixed",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0, 0, 0, 0.7)",
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    zIndex: 1000,
  },
  panel: {
    backgroundColor: "#1a1a2e",
    border: "1px solid #0f3460",
    borderRadius: "8px",
    width: "90%",
    maxWidth: "700px",
    maxHeight: "85vh",
    display: "flex",
    flexDirection: "column",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "16px 20px",
    borderBottom: "1px solid #0f3460",
  },
  title: {
    margin: 0,
    color: "#e0e0e0",
    fontFamily: "'Courier New', Courier, monospace",
    fontSize: "20px",
  },
  closeButton: {
    background: "none",
    border: "none",
    color: "#aaa",
    fontSize: "24px",
    cursor: "pointer",
    padding: "0 4px",
  },
  scrollArea: {
    overflowY: "auto",
    padding: "16px 20px",
  },
  section: {
    marginBottom: "20px",
  },
  sectionTitle: {
    color: "#81c784",
    fontFamily: "'Courier New', Courier, monospace",
    fontSize: "16px",
    marginBottom: "8px",
  },
  paragraph: {
    color: "#b0bec5",
    fontFamily: "'Courier New', Courier, monospace",
    fontSize: "13px",
    lineHeight: "1.6",
  },
  list: {
    color: "#b0bec5",
    fontFamily: "'Courier New', Courier, monospace",
    fontSize: "13px",
    lineHeight: "1.8",
    paddingLeft: "24px",
  },
  code: {
    backgroundColor: "#16213e",
    color: "#64b5f6",
    padding: "1px 6px",
    borderRadius: "3px",
    fontFamily: "'Courier New', Courier, monospace",
    fontSize: "13px",
  },
  pre: {
    backgroundColor: "#16213e",
    color: "#64b5f6",
    padding: "10px 14px",
    borderRadius: "4px",
    fontFamily: "'Courier New', Courier, monospace",
    fontSize: "12px",
    overflowX: "auto",
    whiteSpace: "pre-wrap",
  },
  categoryBlock: {
    marginBottom: "4px",
  },
  categoryHeader: {
    display: "flex",
    justifyContent: "space-between",
    width: "100%",
    background: "#16213e",
    border: "1px solid #0f3460",
    borderRadius: "4px",
    color: "#e0e0e0",
    padding: "8px 12px",
    cursor: "pointer",
    fontFamily: "'Courier New', Courier, monospace",
    fontSize: "14px",
  },
  commandList: {
    padding: "8px 12px",
    borderLeft: "2px solid #0f3460",
    marginLeft: "8px",
  },
  commandRow: {
    marginBottom: "12px",
  },
  commandName: {
    marginBottom: "2px",
  },
  aliases: {
    color: "#666",
    fontSize: "12px",
    marginLeft: "8px",
  },
  commandDesc: {
    color: "#b0bec5",
    fontSize: "12px",
    marginBottom: "2px",
  },
  commandExample: {
    color: "#666",
    fontSize: "11px",
  },
};

export default GameGuide;
