(() => {
  "use strict";
  const API = "https://api.onyxdiscord.com";
  const nav = document.querySelector(".topbar nav");

  document.querySelectorAll("[data-year]").forEach(el => {
    el.textContent = new Date().getFullYear();
  });

  const menuButton = document.querySelector(".menu-toggle");
  if (menuButton && nav) {
    menuButton.addEventListener("click", () => {
      const isOpen = nav.classList.toggle("open");
      menuButton.setAttribute("aria-expanded", String(isOpen));
    });
  }
  if (!nav) return;

  const findLink = path => Array.from(nav.querySelectorAll("a"))
    .find(link => link.getAttribute("href") === path);

  function addLink(path, label, attributes = {}) {
    let link = findLink(path);
    if (!link) {
      link = document.createElement("a");
      link.href = path;
      link.textContent = label;
      nav.append(link);
    }
    Object.entries(attributes).forEach(([key, value]) => {
      if (key === "hidden") link.hidden = Boolean(value);
      else link.setAttribute(key, value);
    });
    return link;
  }

  addLink("/dashboard/", "DASHBOARD", {"data-onyx-dashboard": ""});

  const teamLink = addLink("/owner/", "CONTROL CENTER", {
    "data-onyx-team": "",
    "aria-label": "ONYX owner and developer control center"
  });
  teamLink.hidden = true;

  let authLink = nav.querySelector("[data-onyx-auth]");
  if (!authLink) {
    authLink = document.createElement("a");
    authLink.className = "nav-cta";
    authLink.setAttribute("data-onyx-auth", "");
    nav.append(authLink);
  }

  let signOutLink = nav.querySelector("[data-onyx-signout]");
  if (!signOutLink) {
    signOutLink = document.createElement("a");
    signOutLink.className = "nav-cta";
    signOutLink.href = "#";
    signOutLink.textContent = "SIGN OUT";
    signOutLink.setAttribute("data-onyx-signout", "");
    signOutLink.hidden = true;
    nav.append(signOutLink);
  }

  const currentPath = window.location.pathname || "/";
  authLink.href = API + "/auth/discord?next=" + encodeURIComponent(currentPath);
  authLink.textContent = "SIGN IN";

  signOutLink.addEventListener("click", async event => {
    event.preventDefault();
    signOutLink.textContent = "SIGNING OUT…";
    try {
      await fetch(API + "/auth/logout", {
        method: "POST",
        credentials: "include",
        headers: {"Accept": "application/json"}
      });
    } catch (error) {
      console.error("ONYX sign-out request failed:", error);
    }
    window.location.reload();
  });

  async function loadAccountNavigation() {
    try {
      const response = await fetch(API + "/api/me", {
        method: "GET",
        credentials: "include",
        headers: {"Accept": "application/json"},
        cache: "no-store"
      });

      if (!response.ok) {
        teamLink.hidden = true;
        authLink.hidden = false;
        signOutLink.hidden = true;
        return;
      }

      const user = await response.json();
      authLink.href = "/dashboard/";
      authLink.textContent = (user.username || "MY ACCOUNT").toUpperCase();
      authLink.setAttribute(
        "aria-label",
        "Signed in as " + (user.username || "Discord user")
      );
      signOutLink.hidden = false;

      try {
        const accessResponse = await fetch(API + "/api/developer/access", {
          method: "GET",
          credentials: "include",
          headers: {"Accept": "application/json"},
          cache: "no-store"
        });

        if (accessResponse.ok) {
          const access = await accessResponse.json();
          teamLink.hidden = !access.authorized;
          if (access.authorized) {
            teamLink.textContent = access.role === "owner"
              ? "OWNER CONTROL CENTER"
              : "DEVELOPER WORKSPACE";
          }
        } else {
          teamLink.hidden = true;
        }
      } catch (error) {
        teamLink.hidden = true;
        console.error("ONYX access check failed:", error);
      }
    } catch (error) {
      teamLink.hidden = true;
      authLink.hidden = false;
      signOutLink.hidden = true;
      console.error("ONYX account check failed:", error);
    }
  }

  loadAccountNavigation();
})();
