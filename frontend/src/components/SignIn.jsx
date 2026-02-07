import React, { useState } from "react";
import { useGoogleLogin } from "@react-oauth/google";

const SignIn = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const googleLogin = useGoogleLogin({
    onSuccess: async (tokenResponse) => {
      setLoading(true);
      setError("");
      try {
        // Exchange the Google credential for our internal JWT
        const resp = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: tokenResponse.credential }),
        });
        if (!resp.ok) throw new Error("Server error. Failed to login.");
        const data = await resp.json();
        if (!data.jwt) throw new Error("Missing JWT from server");
        window.localStorage.setItem("jwt", data.jwt);
        window.location.href = "/";
      } catch (e) {
        setError(e.message || "Sign in failed");
      } finally {
        setLoading(false);
      }
    },
    onError: () => {
      setError("Google sign-in failed");
    },
    flow: "implicit",
  });

  return (
    <div>
      <button onClick={() => googleLogin()} disabled={loading}>
        {loading ? "Signing in..." : "Sign in with Google"}
      </button>
      {error && <div style={{ color: "red" }}>{error}</div>}
    </div>
  );
};

export default SignIn;
