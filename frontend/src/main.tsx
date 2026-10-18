import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { DownloaderApp } from "../../src/features/downloads/app";
import "../../src/styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing root");

createRoot(root).render(
  <StrictMode>
    <DownloaderApp />
  </StrictMode>,
);
