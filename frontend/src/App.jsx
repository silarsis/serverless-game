import React, { useState } from "react";
import { GoogleOAuthProvider } from "@react-oauth/google";
import SignIn from "./components/SignIn";
import Game from "./components/Game";
import GameGuide from "./components/GameGuide";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";

const getToken = () => window.localStorage.getItem("jwt");

function App() {
  const token = getToken();
  const [showGuide, setShowGuide] = useState(false);

  const content = (
    <div>
      {token ? (
        <Game onShowGuide={() => setShowGuide(true)} />
      ) : (
        <SignIn onShowGuide={() => setShowGuide(true)} googleEnabled={!!GOOGLE_CLIENT_ID} />
      )}
      {showGuide && <GameGuide onClose={() => setShowGuide(false)} />}
    </div>
  );

  // Only wrap in GoogleOAuthProvider when a client ID is configured.
  // Without a valid client ID the Google SDK throws on initialization.
  if (GOOGLE_CLIENT_ID) {
    return <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>{content}</GoogleOAuthProvider>;
  }

  return content;
}

export default App;
