import "./boot/bootlog"; // must run first to attach listeners before any other side effects
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import "./theme.css";
import bootlog, { bootlogDebugEnabled, pushBootlog } from "./boot/bootlog";

const buildMeta = {
  tag: "build-meta",
  mode: import.meta.env.MODE,
  prod: import.meta.env.PROD,
  dev: import.meta.env.DEV,
  revision: import.meta.env.VITE_GIT_SHA || import.meta.env.VITE_APP_VERSION || "dev",
};
pushBootlog(buildMeta);
pushBootlog({ tag: "entry start" });

if (bootlogDebugEnabled) {
  console.info("[BOOT MARKER] main entry start", {
    events: bootlog.events.length,
    mode: buildMeta.mode,
    revision: buildMeta.revision,
  });
}

const rootElement = document.getElementById("root");
pushBootlog({ tag: "before root", hasRoot: !!rootElement });

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

pushBootlog({ tag: "after root" });
