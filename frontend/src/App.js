import React from "react";
import { GoogleOAuthProvider } from "@react-oauth/google";
import SignIn from "./components/SignIn";
import Game from "./components/Game";

const GOOGLE_CLIENT_ID = process.env.REACT_APP_GOOGLE_CLIENT_ID || "";

const getToken = () => window.localStorage.getItem("jwt");

function App() {
  const token = getToken();
  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <div>
        {token ? <Game /> : <SignIn />}
      </div>
    </GoogleOAuthProvider>
  );
}

export default App;
