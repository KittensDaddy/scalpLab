# ScalpLab 0.2.2 — File Descriptor Hotfix

This release addresses `OSError: [Errno 24] Too many open files` in the Web UI process.

Changes:

- Web job polling is single-flight; no overlapping `setInterval` request storms.
- Every browser API request has a 10-second timeout.
- Recorder-page refreshes are also single-flight.
- `scalp serve` raises its soft `RLIMIT_NOFILE` toward 8192 when the OS hard limit permits.
- Uvicorn Web concurrency defaults to 64 and backlog to 128.
- HTTP keep-alive timeout is reduced to 2 seconds.
- `/api/health` and `/api/runtime` expose current process file-descriptor usage.
- `scalp doctor` reports descriptor health.
- systemd example sets `LimitNOFILE=16384` and port 1120.

Recommended start command:

```bash
scalp serve --host 0.0.0.0 --port 1120
```

Expected startup diagnostic resembles:

```text
ScalpLab server FD limit: 8192 soft / 1048576 hard · max HTTP concurrency 64
```

Check while running:

```bash
curl -s http://127.0.0.1:1120/api/runtime
```
