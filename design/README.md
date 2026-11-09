# Design reference (12 desktop web screens)

UI design for the web app (desktop first, stacks cleanly at tablet/phone width). Uzbek copy.

| Folder | What |
|---|---|
| `previews/*.png` | Rendered screens, 1280 px wide. **Look at these first.** |
| `artboards/*.dc.html` | Source of each screen (HTML + inline styles). Open in a browser for a static view. |
| `canvas.json` | Screen titles and their positions on the design canvas. |
| `tokens.md` | Colors, type, radii, component specs: build the React theme from this. |

Original canvas (private to the owner, Claude Code cannot open it): https://claude.ai/artifact/27vLHb6QtbSK3ZqF7pNLKc

## Screens
1. Kirish  2. Bosh sahifa  3. Tana tanlash  4. Oʻz rasmini yuklash  5. Belgilash sahifasi (landmark editor)
6. Model tanlash  7. Kiyimlar  8. Kiyim yuklash va tozalash  9. Kiyimni belgilash va koʻrinish  10. Kiyib koʻrish
11. Mening obrazlarim  12. Profil va maxfiylik

## How to use it
- Match layout, hierarchy, copy, states and tokens. Rebuild everything in React + TypeScript. Do NOT copy the
  `.dc.html` files into the app: they are a design-tool format (custom `<x-dc>` / `<helmet>` tags, no logic).
- **All pictures of people and clothes in these files are inline SVG PLACEHOLDERS** (grey-blue silhouettes, flat T-shirt
  and pants shapes, a drawn hanger). In the real app every body, avatar, garment, result and outfit image comes from
  the backend API. See `docs/10-frontend-and-design.md`. Only the logo and UI icons are static.
- Sample names ("Koʻk futbolka", "Kundalik", the email) are placeholder copy. Real values come from the API.
- The screens show happy-path states plus a few examples (rejection banner, amber stretch warning, status chips).
  Loading, empty, error and session states are NOT drawn: see docs/10.
- Not designed yet: admin moderation queue, realistic before/after compare, list of upload rejection reasons.
- Fonts: Space Grotesk (headings), Inter (body), via Google Fonts.
