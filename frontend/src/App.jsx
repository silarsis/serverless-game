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

  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <div>
        {token ? <Game onShowGuide={() => setShowGuide(true)} /> : <SignIn onShowGuide={() => setShowGuide(true)} />}
        {showGuide && <GameGuide onClose={() => setShowGuide(false)} />}
      </div>
    </GoogleOAuthProvider>
  );
}

export default App;
