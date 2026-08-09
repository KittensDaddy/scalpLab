# Operations

## Suggested disks

Mount the 500 GB HDD at `/data` and keep application/state on the 128 GB NVMe. Ensure the service user can write `/data/scalp`.

## Before leaving the recorder unattended

```bash
scalp selftest
scalp doctor
scalp storage-status
```

Run the recorder for several days and use the Storage page to measure real GB/day before purchasing additional storage.

## Retention

`storage.raw_l2_retention_days` defaults to 30. `scalp storage-prune` previews deletions; add `--apply` to execute the configured policy. The Web UI only previews cleanup by default.
