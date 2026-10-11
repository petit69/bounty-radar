# bounty-radar

**Finds open-source bounties worth doing — and throws away the ones that aren't.**

Reads the real sources, then checks every candidate against reality before you spend a single hour on it.

## What it actually checks

| Filter | Why it exists (measured 2026-10-11) |
|---|---|
| Issue still **open** on GitHub | Of the 5 rewards listed on Opire that day, **2 pointed at closed issues** — one even returned 404 |
| Repo **alive** (not archived, recent activity) | Dead repos keep stale bounty listings for years |
| Not a **bot farm** | Searching GitHub for `/bounty` returned **~65,000 issues**, most of them automated "Bounty Alert" repos with no real work behind them |
| Repo does **not ban AI-assisted contributions** | Zig, NetBSD, GIMP, Gentoo, qemu, Ghostty, tldraw and Godot (June 2026) reject AI-generated PRs. The bounty only pays **if the maintainer merges**, so an anti-AI repo is unworkable |
| How many **PRs already claim it** | Counted from the issue timeline, not guessed |

Output: a dated Markdown report (`informe_bounties_YYYY-MM-DD.md`) plus the raw JSON, sorted so the only
thing you read is what survived.

## Usage

```bash
python3 radar_recompensas.py --top 15
```

Requires `gh` (GitHub CLI) authenticated — it reads through your own account to stay inside the API rate
limits. It is **read-only**: it never writes to GitHub, a bounty platform, or any account.

## Why this exists

Bounty hunting is an information problem before it is a coding problem. The listed amount says almost
nothing: three of the five rewards live on Opire that day were either dead or already claimed by 19–38
people. Filtering that noise by hand, issue by issue, is what actually burns the time.

## Español

**Encuentra recompensas de código abierto que valga la pena hacer — y descarta las que no.**
Lee las fuentes reales (la API pública de Opire y las búsquedas de GitHub), y después comprueba cada
candidato contra la realidad: ¿el issue sigue abierto?, ¿el repositorio está vivo?, ¿es una granja de bots?,
¿el repositorio prohíbe contribuciones con IA?, ¿cuántos PR ya lo reclaman? Devuelve un informe con fecha,
ordenado, con sólo lo que pasó el filtro. **Sólo lee: no escribe nada en ninguna cuenta.**
