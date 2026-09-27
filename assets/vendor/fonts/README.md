# Local UI fonts

Noto Sans SC (normal, variable weight 100–900) and JetBrains Mono (normal, variable weight 100–800) are served from this directory. `fonts.css` retains the upstream Unicode subsets so browsers only request the characters used on the page. It has no remote URLs and no `local()` override, ensuring the bundled versions are used across platforms.

Downloaded from Google Fonts on 2026-09-20. `SOURCES.json` records the stylesheet request, each upstream font URL, byte size and SHA-256. Both families are distributed under the SIL Open Font License; see `notosanssc-OFL.txt` and `jetbrainsmono-OFL.txt`.

To update, obtain the variable-font CSS from the recorded request using a modern browser user agent, download every referenced WOFF2 without modifying the font binaries, replace each CSS URL with its local filename, and update the source manifest and licenses. Keep all Unicode ranges; do not subset to today's UI text, since question content can contain additional characters.
