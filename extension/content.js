"use strict";
(function () {
  if (document.getElementById("runmap-extension-launcher")) return;
  const host = document.createElement("div");
  host.id = "runmap-extension-launcher";
  const root = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = `
    :host { all: initial; position: fixed; right: 24px; bottom: 94px; z-index: 1000; }
    button { display: flex; align-items: center; gap: 10px; font: 600 14px/1.3 system-ui, sans-serif;
      color: #173c31; background: #d5f77f; border: 1px solid #aecf65; border-radius: 100px;
      padding: 13px 19px; box-shadow: 0 4px 20px #173c3126; cursor: pointer; }
    button:hover { background: #e3ffa1; transform: translateY(-1px); }
    button:focus-visible { outline: 3px solid #173c31; outline-offset: 3px; }
    button:disabled { opacity: .65; cursor: wait; }
    span.icon { font-size: 20px; font-weight: 800; }
    p { max-width: 240px; margin: 8px 0 0; padding: 10px; border-radius: 8px; background: #fff;
      color: #173c31; font: 12px/1.5 system-ui, sans-serif; box-shadow: 0 4px 16px #0002; }
    p:empty { display: none; }
    @media (max-width: 640px) { :host { right: 12px; bottom: 108px; } button { padding: 10px 15px; } }
  `;
  const button = document.createElement("button");
  button.type = "button";
  button.title = "Open this journey in RunMap with running connections";
  const icon = document.createElement("span");
  icon.className = "icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "↗";
  button.append(icon, document.createTextNode("Try running connections"));
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  root.append(style, button, status);
  document.documentElement.append(host);

  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "";
    try {
      const response = await chrome.runtime.sendMessage({ type: "RUNMAP_OPEN" });
      if (!response?.ok) throw new Error(response?.error || "Could not open RunMap.");
    } catch (error) {
      status.textContent = /context invalidated/i.test(error.message)
        ? "Extension updated. Reload Google Maps and try again."
        : error.message;
    } finally {
      button.disabled = false;
    }
  });
})();
