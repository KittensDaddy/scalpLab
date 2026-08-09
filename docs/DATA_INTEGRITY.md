# Data integrity

Missing market data is not neutral. ScalpLab records gaps and book-quality state explicitly.

Gap reasons include `POWER_LOSS`, `MANUAL_REBOOT`, `PROCESS_CRASH`, `NETWORK_OUTAGE`, `BINANCE_DISCONNECT`, `STREAM_SEQUENCE_GAP`, `DISK_FULL`, `RECORDER_OVERLOAD`, `CLOCK_SYNC_ERROR`, and `UNKNOWN`.

Book states: `SYNCING`, `HEALTHY`, `STALE`, `SEQUENCE_GAP`, `UNTRUSTED`, `RESYNCING`.

After any sequence gap or reconnect, the old order-book state is discarded and a fresh REST snapshot is required before microstructure features become healthy.
