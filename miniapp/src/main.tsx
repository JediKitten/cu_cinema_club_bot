import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { watchForUpdates } from "./freshness";
import "./index.css";

watchForUpdates();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
