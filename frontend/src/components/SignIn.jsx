import React, { useState } from "react";
import { useGoogleLogin } from "@react-oauth/google";

const API_URL = import.meta.env.VITE_API_URL || "";

// Separate component that uses the Google hook — only rendered when
// GoogleOAuthProvider is mounted (i.e. a client ID is configured).
const GoogleLoginButton = ({ loading, onSuccess, onError }) => {
  const googleLogin = useGoogleLogin({
    onSuccess,
    onError: () => onError("Google sign-in failed"),
    flow: "implicit",
  });

  return (
    <button onClick={() => googleLogin()} disabled={loading} style={styles.googleButton}>
      {loading ? "Signing in..." : "Sign in with Google"}
    </button>
  );
};

const SignIn = ({ onShowGuide, googleEnabled = false }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleGoogleSuccess = async (tokenResponse) => {
    setLoading(true);
    setError("");
    try {
      const resp = await fetch(`${API_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: tokenResponse.credential }),
      });
      if (!resp.ok) throw new Error("Server error. Failed to login.");
      const data = await resp.json();
      if (!data.jwt) throw new Error("Missing JWT from server");
      window.localStorage.setItem("jwt", data.jwt);
      if (data.entity) {
        window.localStorage.setItem("entity", JSON.stringify(data.entity));
      }
      window.location.href = "/";
    } catch (e) {
      setError(e.message || "Sign in failed");
    } finally {
      setLoading(false);
    }
  };

  const devLogin = async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await fetch(`${API_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: "dev" }),
      });
      if (!resp.ok) throw new Error("Server error. Failed to login.");
      const data = await resp.json();
      if (!data.jwt) throw new Error("Missing JWT from server");
      window.localStorage.setItem("jwt", data.jwt);
      if (data.entity) {
        window.localStorage.setItem("entity", JSON.stringify(data.entity));
      }
      window.location.href = "/";
    } catch (e) {
      setError(e.message || "Dev sign in failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <h1 style={styles.title}>Serverless Game</h1>
        <p style={styles.subtitle}>
          A collaborative world where humans and AI agents explore together.
        </p>
        <div style={styles.buttons}>
          {googleEnabled && (
            <GoogleLoginButton loading={loading} onSuccess={handleGoogleSuccess} onError={setError} />
          )}
          <button onClick={devLogin} disabled={loading} style={styles.devButton}>
            Dev Mode (Local)
          </button>
        </div>
        {error && <div style={styles.error}>{error}</div>}
        {onShowGuide && (
          <button onClick={onShowGuide} style={styles.guideLink}>
            How to Play
          </button>
        )}
      </div>
    </div>
  );
};

const styles = {
  container: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    height: "100vh",
    backgroundColor: "#1a1a2e",
    fontFamily: "'Courier New', Courier, monospace",
  },
  card: {
    backgroundColor: "#16213e",
    border: "1px solid #0f3460",
    borderRadius: "8px",
    padding: "40px",
    textAlign: "center",
    maxWidth: "400px",
    width: "90%",
  },
  title: {
    color: "#e0e0e0",
    fontSize: "24px",
    marginBottom: "8px",
  },
  subtitle: {
    color: "#888",
    fontSize: "13px",
    marginBottom: "24px",
  },
  buttons: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
  },
  googleButton: {
    padding: "12px 24px",
    backgroundColor: "#4285f4",
    color: "white",
    border: "none",
    borderRadius: "4px",
    fontSize: "14px",
    cursor: "pointer",
    fontFamily: "inherit",
  },
  devButton: {
    padding: "12px 24px",
    backgroundColor: "transparent",
    color: "#81c784",
    border: "1px solid #81c784",
    borderRadius: "4px",
    fontSize: "14px",
    cursor: "pointer",
    fontFamily: "inherit",
  },
  error: {
    color: "#ef5350",
    marginTop: "12px",
    fontSize: "13px",
  },
  guideLink: {
    marginTop: "16px",
    background: "none",
    border: "none",
    color: "#64b5f6",
    cursor: "pointer",
    fontSize: "13px",
    textDecoration: "underline",
    fontFamily: "inherit",
  },
};

export default SignIn;
