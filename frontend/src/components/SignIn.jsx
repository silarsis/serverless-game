import React, { useState } from "react";
import { signInWithPopup } from "firebase/auth";
import { auth, googleProvider } from "../firebase";

const SignIn = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSignIn = async () => {
    setLoading(true);
    setError("");
    try {
      const result = await signInWithPopup(auth, googleProvider);
      const token = await result.user.getIdToken();
      // POST token to backend
      const resp = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token })
      });
      if (!resp.ok) throw new Error("Server error. Failed to login.");
      const data = await resp.json();
      if (!data.jwt) throw new Error("Missing JWT from server");
      window.localStorage.setItem("jwt", data.jwt);
      window.location.href = "/"; // Optionally use useNavigate
    } catch (e) {
      setError(e.message || "Sign in failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <button onClick={handleSignIn} disabled={loading}>
        {loading ? "Signing in..." : "Sign in with Google"}
      </button>
      {error && <div style={{color: "red"}}>{error}</div>}
    </div>
  );
};

export default SignIn;
