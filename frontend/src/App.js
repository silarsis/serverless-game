import React from "react";
import SignIn from "./components/SignIn";
import Game from "./components/Game";

const getToken = () => window.localStorage.getItem("jwt");

function App() {
  const token = getToken();
  return (
    <div>
      {token ? <Game /> : <SignIn />}
    </div>
  );
}

export default App;
