# Code Review — video-editing

**Date:** 2026-08-29
**Scope:** Full repo (Python backend, TypeScript frontend, tests, config)

---

## Summary

**0 CRITICAL** | **3 HIGH** | **15 MEDIUM** | **27 LOW**

---

## HIGH — Fix These

| # | File | Issue |
|---|------|-------|
| 1 | `web/src/fonts.ts:23-31` | **Rejected font promises cached permanently.** If `FontFace.load()` fails (404, network), the rejected promise sits in the `loaded` Map forever. Font can never retry without page refresh. Fix: `.catch(() => { loaded.delete(family); throw e })` |
| 2 | `api/db.py:180-186` | **SQL injection surface.** `update_render(**fields)` interpolates field names directly into SQL via `f"{k} = ?"`. Currently safe because callers only pass hardcoded keys, but a future caller could pass arbitrary column names. Fix: whitelist allowed columns. |
| 3 | `tests/test_api.py:198` | **Flaky test masks bugs.** `assert r.status_code in (409, 200)` — accepting 200 means the test passes even when the assertion is wrong (render finished instantly). Fix: remove the 200 alternative. |

---

## MEDIUM — Should Fix

| # | File | Issue |
|---|------|-------|
| 4 | `core/run.py:52-56` | **Deadlock risk.** `proc.stderr.read()` after `proc.wait()` can block if stderr fills the pipe buffer. Fix: read stderr before `wait()`, or use `communicate()`. |
| 5 | `core/run.py:59-61` | **Temp dirs never cleaned up.** `mkdtemp` creates workdirs but nothing removes them. Disk leak over time. |
| 6 | `core/probe.py:18-22` | **No timeout on ffprobe.** A corrupted/network file can hang the subprocess indefinitely. Fix: add `timeout=30`. |
| 7 | `api/main.py:126` | **File descriptor leak on early exception.** `mkstemp` returns an fd that's never explicitly closed if an exception hits before the file handle opens. |
| 8 | `api/main.py:176-180` | **`delete_project` doesn't clean CACHE/pid workdir.** Sidecar files accumulate. |
| 9 | `api/main.py:148-150` | **Race: rename before set_src_path.** If server crashes between rename and DB update, project has a dead `src_path`. |
| 10 | `api/main.py:112` | **O(n) ffprobe per list request.** `_backfill` runs on every project on every `GET /api/projects`. |
| 11 | `api/main.py:281-301` | **`suggest_crop` blocks event loop.** Sync OpenCV/ffmpeg in async endpoint stalls all requests. Fix: `run_in_executor`. |
| 12 | `api/jobs.py:31-37` | **No render deduplication.** Two rapid "Export" clicks waste resources on duplicate renders. |
| 13 | `api/db.py:97-108` | **No SQLite connection pooling.** New connection per operation. |
| 14 | `tests/test_compile.py:14` | **Hardcoded `/tmp/work`** — test interference under parallel execution. |
| 15 | `tests/test_render.py:140` | **Quality ceiling test too loose.** 4x multiplier won't catch a real regression. |
| 16 | `tests/test_render.py:55,165,217,242` | **Flaky duration tolerance.** 200ms abs is tight for GOP-dependent trims. |
| 17 | `run.sh:11-13` | **No startup check for uvicorn.** If it fails to bind, npm silently 502s. |
| 18 | `web/tsconfig.app.json` | **`strict` mode not enabled.** Undermines TypeScript's null-check safety. |
| 19 | `web/src/Library.tsx:116` | **File input not reset after upload.** Can't re-upload same file. |
| 20 | `web/src/CropBox.tsx:99` | **Non-null assertion on nullable return.** `heightFor(w)!` suppresses type error, breaks if aspect becomes null mid-drag. |
| 21 | `web/src/store.ts:68-77` | **Stale projectId in autosave.** Navigate within 700ms of edit = save to wrong project. |

---

## LOW — Nice to Fix

- `core/doc.py:189-198` — `from_dict` raises `TypeError` not `DocError` on bad keys
- `core/compile.py:56` — `fit_inside` can return 0x0 for tiny sources
- `core/compile.py:326` — `atempo_args` infinite loop at speed=0 (guarded by validation)
- `core/encoders.py:59,65` — hardcoded VAAPI device paths
- `api/main.py:345` — user project name in Content-Disposition header
- `api/main.py:364-365` — static mount at "/" swallows future routes
- `api/main.py:57-58` — CORS hardcoded to localhost:5173
- `api/jobs.py:47-59` — `KeyboardInterrupt` kills worker silently
- `overlay.py:55-57` — empty `--name` produces invisible overlay block
- `web/src/Export.tsx:34` — `clearInterval` on `setInterval` handle
- `web/src/Viewer.tsx:140-167` — keyboard listener re-registered ~60x/sec during playback
- `web/src/store.ts:68-77` — stale `projectId` in autosave timer
- `web/src/Viewer.tsx:71-90` — intentional ref reads outside deps (fragile)
- Test coverage gaps: no tests for upload size limit, concurrent upload, render failure, encoder listing, corrupt input

---

## Recommended Priority

1. Fix **fonts.ts** cache poison — users hit this on any font 404
2. Fix **test_api.py** flaky assertion — masks real download bugs
3. Add **ffprobe timeout** — prevents infinite hangs
4. Clean up **temp dirs** in run.py and api/main.py
5. Whitelist columns in **update_render** before someone passes bad input
