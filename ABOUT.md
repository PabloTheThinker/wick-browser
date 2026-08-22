# About Wick

## What it is

Wick is built for **agents** the way a professional kit is built for specialists: observe, decide, act — no clutter. The “Wick brothers” idea is simple: two engines that work together (light recon + heavy contact), not one bloated browser pretending to be everything.


**Wick** is a free, open-source **agent browser**: a command-line tool that helps AI agents and automation scripts read the web, block common trackers, keep sessions isolated, and — when needed — drive a real Chromium for clicks, tabs, PDFs, and downloads.

The name is intentional: a **wick** is a thin flame. Agents rarely need a full desktop browser burning all the time. Wick keeps a light engine for reading and only lights Chromium when interaction or pixels matter.

## What it is not

- Not a consumer GUI browser (Chrome/Firefox/Brave replacement for humans)
- Not a guarantee of bypassing Cloudflare, CAPTCHAs, or bank anti-bot
- Not Brave-identical fingerprint protection (no canvas/WebGL farbling in the Lightpanda path)
- Not a hosted/cloud browser SaaS — everything runs on **your** machine

## Design principles

1. **Agent-first outputs** — markdown and semantic trees beat raw HTML dumps for LLMs  
2. **Honest security** — network shields and isolation, labeled clearly; no marketing cosplay  
3. **Two engines** — fast specialized headless (Lightpanda) + optional Chromium  
4. **Free core** — MIT CLI; optional engines keep their own licenses  
5. **Loopback by default** — CDP bound to `127.0.0.1` only  
6. **No secrets in the repo** — portable for anyone to clone and run  

## Who it’s for

- People building local AI agents that need to **read** and occasionally **act** on the web  
- Operators who want EasyList-style blocking without wiring a full browser stack by hand  
- Developers who want a small CLI instead of embedding Playwright in every project  

## Relationship to other tools

| Tool | Relationship |
|------|----------------|
| **Lightpanda** | Optional external engine (AGPL). Wick invokes the binary; does not vendor its source. |
| **Playwright / Chromium** | Optional path for UI automation and PDF |
| **Browser-Use** | Inspiration for act/session/playbook shape; Wick is a standalone CLI, not a fork |
| **Brave** | Inspiration for list-based shields and privacy headers; not a reimplementation of farbling |

## Version

Public package tracks the **0.6** command surface (`snap` / `elements`, history, tabs, PDF, shields, sessions, playbooks). See [docs/AGENT-BROWSER.md](docs/AGENT-BROWSER.md) and `docs/WICK-0.5.md`.

## Credits

Built as open infrastructure for agent operators. Contributions welcome under MIT.
