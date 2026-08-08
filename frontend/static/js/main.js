(() => {
  const THEME_KEY = "techfrontier_theme";

  function currentTheme() {
    return document.documentElement.classList.contains("dark") ? "dark" : "light";
  }

  function applyTheme(theme) {
    const next = theme === "dark" ? "dark" : "light";
    document.documentElement.classList.toggle("dark", next === "dark");
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* ignore */
    }

    const meta = document.querySelector("[data-theme-color]");
    if (meta) {
      const value = getComputedStyle(document.documentElement)
        .getPropertyValue("--theme-meta")
        .trim();
      if (value) meta.setAttribute("content", value);
    }

    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.setAttribute(
        "aria-label",
        next === "dark" ? "Switch to light theme" : "Switch to dark theme",
      );
    });
  }

  function initThemeToggle() {
    applyTheme(currentTheme());
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        applyTheme(currentTheme() === "dark" ? "light" : "dark");
      });
    });
  }

  initThemeToggle();

  const yearEl = document.getElementById("year");
  if (yearEl) {
    yearEl.textContent = String(new Date().getFullYear());
  }

  const toggle = document.querySelector("[data-nav-toggle]");
  const mobileNav = document.getElementById("mobile-nav");
  if (toggle && mobileNav) {
    toggle.addEventListener("click", () => {
      const open = !mobileNav.classList.contains("hidden");
      mobileNav.classList.toggle("hidden", open);
      toggle.setAttribute("aria-expanded", open ? "false" : "true");
    });
  }

  function initNewsletterForms() {
    document.querySelectorAll("[data-newsletter-form]").forEach((form) => {
      const message = form.querySelector(".newsletter-message");
      const submit = form.querySelector('button[type="submit"]');

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const emailInput = form.querySelector('input[name="email"]');
        const email = emailInput?.value.trim();
        if (!email) return;

        if (message) {
          message.classList.add("hidden");
          message.textContent = "";
        }
        if (submit) submit.disabled = true;

        try {
          await api("/api/newsletter/subscribe", {
            method: "POST",
            body: JSON.stringify({ email }),
          });
          form.reset();
          if (message) {
            const inFooter = Boolean(form.closest(".site-footer"));
            message.textContent = "Du är prenumerant. Välkommen!";
            message.className = inFooter
              ? "newsletter-message mt-2 text-sm text-[var(--footer-link)]"
              : "newsletter-message text-sm text-accent-deep";
            message.classList.remove("hidden");
          }
        } catch (err) {
          if (message) {
            const inFooter = Boolean(form.closest(".site-footer"));
            message.textContent = err.message || "Något gick fel. Försök igen.";
            message.className = inFooter
              ? "newsletter-message mt-2 text-sm text-[#f0a090]"
              : "newsletter-message text-sm text-danger";
            message.classList.remove("hidden");
          }
        } finally {
          if (submit) submit.disabled = false;
        }
      });
    });
  }

  initNewsletterForms();

  // Prefer HttpOnly session cookies; drop any legacy JS-readable tokens.
  try {
    localStorage.removeItem("techfrontier_token");
    localStorage.removeItem("meridian_token");
    // Migrate legacy theme key if present.
    if (!localStorage.getItem(THEME_KEY)) {
      const legacy = localStorage.getItem("meridian_theme");
      if (legacy) {
        localStorage.setItem(THEME_KEY, legacy);
        localStorage.removeItem("meridian_theme");
      }
    }
  } catch {
    /* ignore */
  }

  async function api(path, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    };
    const response = await fetch(path, {
      ...options,
      headers,
      credentials: "same-origin",
    });
    let data = null;
    const text = await response.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { detail: text };
      }
    }
    if (!response.ok) {
      const detail = data?.detail;
      const message = Array.isArray(detail)
        ? detail.map((d) => d.msg || JSON.stringify(d)).join(", ")
        : detail || "Request failed";
      throw new Error(message);
    }
    return data;
  }
})();
