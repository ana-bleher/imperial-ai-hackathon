import React from "react";
import ReactDOM from "react-dom/client";
import App, { NightModeToggle } from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
    <NightModeToggle />
  </React.StrictMode>,
);
