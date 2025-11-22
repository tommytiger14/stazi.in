## Stayzi — Copilot instructions (concise)

This is a small static marketing site (single-page) for Stayzi. Key files:
- `index.html` — main SPA-like landing page. Uses Tailwind via CDN and an inline `tailwind.config` script to extend colors and fonts.
- `style.css` — small overrides and utility classes (logo sizing, accordion transitions).
- `default.php` — Hostinger default/boilerplate; safe to ignore or remove when deploying site files.

What to know when editing
- No build system: pages are served as static files. Edit `index.html` and `style.css` directly and test by opening `index.html` in a browser.
- Tailwind usage: most styling is done with Tailwind utility classes. If you add new theme tokens, update the inline `tailwind.config` in `index.html` (see `theme.extend.colors.stayzi`).
- Small custom CSS lives in `style.css`. Prefer Tailwind for layout; reserve `style.css` for global font imports or tiny overrides (logo size, accordion transitions).

Project-specific patterns & examples
- Theme tokens: index.html defines stayzi colors (e.g., `stayzi.primary: #D4E055`). If you change colors, update both `tailwind.config` and any hard-coded hex in `style.css`.
- Image fallbacks: images use `onerror="this.onerror=null; this.src='https://placehold.co/...';"` — preserve this pattern to avoid broken visuals when external images fail.
- External integrations are placeholders:
  - Contact form action uses Formspree (`action="https://formspree.io/f/yourformid"`) — replace with the actual endpoint.
  - Calendly link in Contact uses `https://calendly.com/` — replace with your scheduling link.
  - Portfolio links marked `<!-- CHANGE HREF HERE -->` — those anchors should point to real listings or external pages.

Tiny JS conventions
- Interactions are inline in `index.html`:
  - Mobile menu toggle: `mobile-menu-btn` toggles `#mobile-menu`.
  - Accordion uses `toggleAccordion(element)` and toggles `.accordion-content.active` and `maxHeight`.
Keep edits simple: modify or extend these functions in place when adding UI behavior.

Developer checks (quick smoke)
- Open `index.html` in a browser. Verify:
  - Mobile menu button toggles menu.
  - Accordion items expand/collapse.
  - No console JS errors.
  - Form submit goes to the configured `action` URL (or shows network request).

Edge cases & constraints
- Site depends on external CDNs (Tailwind CDN, Font Awesome, Google Fonts). Work offline will fail; consider bundling assets only if you add a build step.
- There are no tests or CI present. Small, safe changes are preferred.

If you need to add features
- Keep changes minimal and self-contained. Prefer Tailwind utilities and small inline JS edits.
- For larger JS/app structure, add a README and a simple npm-based toolchain; do not assume one exists.

Examples to reference while coding: `index.html` (tailwind.config, onerror fallbacks, comments with TODOs), `style.css` (font imports, `.accordion-content`), `default.php` (hostinger boilerplate).

If anything here is unclear or you want the file tailored (longer examples, deployment steps, or local dev tips), tell me what to expand. 
