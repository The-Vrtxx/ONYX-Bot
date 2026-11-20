(() => {
  "use strict";

  const API = "https://api.onyxdiscord.com";

  document.addEventListener("DOMContentLoaded", () => {
    const toolbar = document.querySelector(".asset-toolbar");
    if (!toolbar) return;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "button";
    button.textContent = "Import Titles";

    const status = document.createElement("div");
    status.className = "message";
    status.style.width = "100%";
    status.setAttribute("role", "status");

    const count = document.createElement("div");
    count.className = "asset-meta";
    count.style.width = "100%";
    count.textContent = "Title catalog has not been loaded.";

    toolbar.append(button, status, count);

    async function request(path, method = "GET") {
      const response = await fetch(API + path, {
        method,
        credentials: "include",
        headers: { "Accept": "application/json" }
      });

      let data = {};
      try {
        data = await response.json();
      } catch (_) {}

      if (!response.ok) {
        throw new Error(data.error || "Title catalog request failed.");
      }

      return data;
    }

    async function refresh() {
      try {
        const data = await request("/api/owner/titles");
        count.textContent = `Registered titles: ${data.count || 0}`;
      } catch (error) {
        count.textContent = error.message;
      }
    }

    button.addEventListener("click", async () => {
      if (!window.confirm(
        "Import newly registered achievement, secret, " +
        "Prestige Master, and shop titles?"
      )) return;

      button.disabled = true;
      button.textContent = "Importing...";
      status.textContent = "Checking title definitions...";

      try {
        const data = await request("/api/owner/titles/import", "POST");
        status.textContent = "✓ " + data.message;
        await refresh();
      } catch (error) {
        status.textContent = error.message;
      } finally {
        button.disabled = false;
        button.textContent = "Import Titles";
      }
    });

    refresh();
  });
})();
