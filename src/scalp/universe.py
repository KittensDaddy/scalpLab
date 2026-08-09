from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from concurrent.futures import ThreadPoolExecutor

import httpx

from scalp.runtime_storage import runtime_roots


def normalized_base(symbol: str) -> str:
    base = symbol.upper().removesuffix("USDT")
    return re.sub(r"^(1000|10000|1000000)(?=[A-Z])", "", base)


class UniverseService:
    def __init__(self, root: Path | None = None, fetch_json: Callable | None = None):
        self.root = Path(root or runtime_roots.current().universes); self.root.mkdir(parents=True, exist_ok=True)
        self.fetch_json = fetch_json or self._fetch

    @staticmethod
    def _fetch(url):
        with httpx.Client(timeout=httpx.Timeout(8,connect=5), limits=httpx.Limits(max_connections=4, max_keepalive_connections=2)) as c:
            return c.get(url).raise_for_status().json()

    def latest(self):
        pointer = self.root / "latest.json"
        if not pointer.exists(): return {"snapshot_id": None, "assets": [], "stale": True}
        return json.loads(pointer.read_text())

    def refresh(self, enrich=True):
        with ThreadPoolExecutor(max_workers=2) as pool:
            info_future=pool.submit(self.fetch_json,"https://fapi.binance.com/fapi/v1/exchangeInfo")
            ticker_future=pool.submit(self.fetch_json,"https://fapi.binance.com/fapi/v1/ticker/24hr")
            info=info_future.result(); tickers=ticker_future.result()
        tradable = {s["symbol"] for s in info.get("symbols", []) if s.get("status") == "TRADING"
                    and s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL"}
        ranked = sorted((t for t in tickers if t.get("symbol") in tradable),
                        key=lambda x: float(x.get("quoteVolume") or 0), reverse=True)[:100]
        metadata = self._metadata() if enrich else {}
        return self._snapshot(ranked,metadata,enrichment_pending=not enrich)

    def enrich_snapshot(self,snapshot):
        ranked=[{"symbol":x["symbol"],"quoteVolume":x.get("futures_quote_volume",0)} for x in snapshot.get("assets",[])]
        return self._snapshot(ranked,self._metadata(),enrichment_pending=False)

    def _snapshot(self,ranked,metadata,enrichment_pending=False):
        overrides = self._overrides()
        assets = []
        for rank, ticker in enumerate(ranked, 1):
            sym = ticker["symbol"]; base = normalized_base(sym); match = overrides.get(sym) or metadata.get(base)
            ambiguous = isinstance(match, list)
            if ambiguous: match = None
            cap = float((match or {}).get("market_cap") or 0)
            tags = set(str(x).lower() for x in (match or {}).get("tags", []))
            cap_group = "Core" if base in {"BTC", "ETH"} else ("Unclassified" if not match else
                "Large alt" if cap >= 10_000_000_000 else "Mid alt" if cap >= 1_000_000_000 else "Low cap")
            themes = [x for x, aliases in (("RWA", {"real-world-assets", "rwa"}), ("Meme", {"memes", "meme"})) if tags & aliases]
            assets.append({"rank": rank, "symbol": sym, "futures_quote_volume": float(ticker.get("quoteVolume") or 0),
                           "market_cap": cap or None, "cap_group": cap_group, "theme_tags": themes,
                           "mapping_quality": "override" if sym in overrides else "ambiguous" if ambiguous else "matched" if match else "unresolved"})
        created = datetime.now(timezone.utc).isoformat(); digest = hashlib.sha256(json.dumps(assets, sort_keys=True).encode()).hexdigest()[:16]
        snapshot = {"snapshot_id": f"{created[:10]}-{digest}", "created_at": created, "selection_date": created[:10], "assets": assets, "stale": False,"enrichment_pending":enrichment_pending}
        immutable = self.root / f"{snapshot['snapshot_id']}.json"
        if not immutable.exists(): immutable.write_text(json.dumps(snapshot, indent=2))
        (self.root / "latest.json").write_text(json.dumps(snapshot, indent=2))
        return snapshot

    def _metadata(self):
        cache = self.root / "cmc-cache.json"
        try:
            raw = self.fetch_json("https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listing?start=1&limit=5000&sortBy=market_cap&sortType=desc&convert=USD")
            rows = raw.get("data", {}).get("cryptoCurrencyList", [])
            out = {}
            for r in rows:
                item = {"id": r.get("id"), "market_cap": (r.get("quotes") or [{}])[0].get("marketCap"), "tags": r.get("tags") or []}
                out.setdefault(str(r.get("symbol", "")).upper(), []).append(item)
            out = {k: v[0] if len(v) == 1 else v for k, v in out.items()}
            cache.write_text(json.dumps(out)); return out
        except Exception:
            return json.loads(cache.read_text()) if cache.exists() else {}

    def _overrides(self):
        p = self.root / "mapping-overrides.json"
        return json.loads(p.read_text()) if p.exists() else {}
