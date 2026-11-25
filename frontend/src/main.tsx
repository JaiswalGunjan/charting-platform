import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import ScreenerPage from "./ScreenerPage";
import SetupPage from "./SetupPage";
import "./styles.css";

// separate pages opened in new tabs from the chart's top bar
const PAGE = new URLSearchParams(window.location.search).get("page");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {PAGE === "screener" ? <ScreenerPage /> : PAGE === "setups" ? <SetupPage /> : <App />}
  </StrictMode>,
);
