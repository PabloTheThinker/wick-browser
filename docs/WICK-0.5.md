# Wick 0.5 — agent browser command map

## Status vs standing goal

| Goal | State |
|------|--------|
| Brave **network** shields | **Done** — EasyList, EasyPrivacy, Fanboy, URL blocks, SSRF, DNT/GPC |
| Brave **fingerprint farbling** | **Not done** — needs Camoufox/Brave engine (not LP flags) |
| Browser-Use-like agent ops | **Done** — sessions, act, run, tabs, pdf, history, get, probe |
| Free / no paid SaaS required | **Yes** |

## Command map (0.5)

```
wick doctor | version | ensure | start | stop | status
wick shields [--update] | shields-bench URL
wick session list|new|use|save|path
wick open|fetch|tree|batch|links|probe|xexam
wick get URL [-o path] [--browser]
wick history [--limit N] [--clear]
wick act <goto|click|fill|select|check|press|wait|eval|content|title|
          back|forward|reload|tab_*|pdf|screenshot|download|cookies>
wick tabs list|new|switch|close
wick pdf [--url] [-o]
wick run playbook.json
wick metrics | prune | install-engine
```

## Env

| Var | Default |
|-----|---------|
| `WICK_SHIELDS` | `1` |
| `WICK_SESSION` | `default` |
| `WICK_HISTORY` | `1` |
| `WICK_PROXY` / `HTTPS_PROXY` | off |
| `WICK_PRIVACY_HEADERS` | `1` |
| `WICK_HOME` | `~/.wick` |

## Layout

```
~/.wick/
  shields/          # easylist, easyprivacy, fanboy, wick-block-urls
  sessions/<name>/  # cookies, chrome-profile, downloads
  history.jsonl
  http-cache/
  shots/
```
