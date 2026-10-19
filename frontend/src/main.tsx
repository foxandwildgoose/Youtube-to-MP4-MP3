import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { setNonce } from "get-nonce";
import { DownloaderApp } from "../../src/features/downloads/app";
import "../../src/styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing root");
const styleNonce = document.querySelector<HTMLMetaElement>('meta[name="csp-style-nonce"]')?.content;
if (styleNonce) setNonce(styleNonce);

createRoot(root).render(
  <StrictMode>
    <DownloaderApp />
  </StrictMode>,
);
