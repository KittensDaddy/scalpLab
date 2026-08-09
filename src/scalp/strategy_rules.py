from __future__ import annotations

import hashlib
import json
import math
import operator
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from scalp.runtime_storage import runtime_roots


BUILT_INS = ("TC", "LC", "LSR", "RB", "VB", "TR")
OPS = {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le, "eq": operator.eq, "ne": operator.ne}
FEATURES = {
    "open": "ohlcv", "high": "ohlcv", "low": "ohlcv", "close": "ohlcv", "volume": "ohlcv",
    "atr": "ohlcv", "rsi": "ohlcv", "ema_fast": "ohlcv", "ema_slow": "ohlcv", "adx": "ohlcv",
    "cvd": "trade_flow", "spot_cvd": "trade_flow", "taker_imbalance": "trade_flow", "trade_velocity": "trade_flow",
    "spread_bps": "microstructure", "microprice": "microstructure", "depth_imbalance": "microstructure",
    "ofi": "microstructure", "replenishment": "microstructure", "cancellation": "microstructure",
    "absorption_bid": "microstructure", "absorption_ask": "microstructure", "oi_delta": "microstructure",
    "funding": "microstructure", "liquidation_buy": "microstructure", "liquidation_sell": "microstructure", "basis": "microstructure",
}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


class RuleInterpreter:
    def validate(self, definition: dict) -> dict:
        errors = []
        if not isinstance(definition, dict): return {"valid": False, "errors": ["definition must be an object"], "requirements": []}
        for direction in ("long", "short"):
            side = definition.get(direction)
            if not isinstance(side, dict): errors.append(f"{direction} definition is required"); continue
            self._validate_node(side.get("conditions"), f"{direction}.conditions", errors)
            score = side.get("score", [])
            if not isinstance(score, list): errors.append(f"{direction}.score must be a list")
            else:
                for i, item in enumerate(score):
                    if not _number(item.get("weight")) or not item.get("evidence_family"):
                        errors.append(f"{direction}.score[{i}] requires numeric weight and evidence_family")
                    self._validate_node(item.get("when"), f"{direction}.score[{i}].when", errors)
            trade = side.get("trade", {})
            if trade.get("stop_anchor") not in FEATURES: errors.append(f"{direction}.trade.stop_anchor is invalid")
            for key in ("atr_offset", "target_r", "urgency", "minimum_expected_r"):
                if not _number(trade.get(key)): errors.append(f"{direction}.trade.{key} must be numeric")
            if _number(trade.get("target_r")) and _number(trade.get("minimum_expected_r")) and trade["target_r"] < trade["minimum_expected_r"]:
                errors.append(f"{direction} target_r is below minimum_expected_r")
        used = sorted(self.fields(definition))
        return {"valid": not errors, "errors": errors, "requirements": sorted({FEATURES[x] for x in used}), "fields": used}

    def _validate_node(self, node, path, errors):
        if not isinstance(node, dict): errors.append(f"{path} must be a condition"); return
        if "all" in node or "any" in node:
            key = "all" if "all" in node else "any"; children = node[key]
            if not isinstance(children, list) or not children: errors.append(f"{path}.{key} must be a non-empty list"); return
            for i, child in enumerate(children): self._validate_node(child, f"{path}.{key}[{i}]", errors)
            return
        field = node.get("field")
        if field not in FEATURES: errors.append(f"{path}.field is invalid")
        op = node.get("op")
        if op not in (*OPS, "between", "crosses_above", "crosses_below"): errors.append(f"{path}.op is invalid")
        if "other_field" in node and node["other_field"] not in FEATURES: errors.append(f"{path}.other_field is invalid")
        if op == "between" and (not isinstance(node.get("value"), list) or len(node["value"]) != 2): errors.append(f"{path}.value must be [low, high]")

    def fields(self, value):
        found = set()
        if isinstance(value, dict):
            if value.get("field") in FEATURES: found.add(value["field"])
            if value.get("other_field") in FEATURES: found.add(value["other_field"])
            for v in value.values(): found |= self.fields(v)
        elif isinstance(value, list):
            for v in value: found |= self.fields(v)
        return found

    def evaluate(self, node: dict, row: dict, previous: dict | None = None) -> bool:
        if "all" in node: return all(self.evaluate(x, row, previous) for x in node["all"])
        if "any" in node: return any(self.evaluate(x, row, previous) for x in node["any"])
        left = row.get(node["field"]); right = row.get(node["other_field"]) if "other_field" in node else node.get("value")
        if left is None or right is None: return False
        op = node["op"]
        if op in OPS: return bool(OPS[op](left, right))
        if op == "between": return right[0] <= left <= right[1]
        if not previous: return False
        prev_left = previous.get(node["field"]); prev_right = previous.get(node["other_field"]) if "other_field" in node else right
        if prev_left is None or prev_right is None: return False
        return (prev_left <= prev_right and left > right) if op == "crosses_above" else (prev_left >= prev_right and left < right)


class StrategyVersionStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or runtime_roots.current().strategies / "definitions.db"); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS definitions (id TEXT PRIMARY KEY,name TEXT,kind TEXT,status TEXT,revision INTEGER,definition TEXT,hash TEXT,created_at TEXT,published_at TEXT,base_revision TEXT,archived INTEGER DEFAULT 0)")
        self.interpreter = RuleInterpreter()

    def list(self):
        builtins = [{"id": x, "name": x, "kind": "builtin", "status": "published", "protected": True, "revision": 1} for x in BUILT_INS]
        with sqlite3.connect(self.path) as c: rows = c.execute("SELECT id,name,kind,status,revision,hash,created_at,published_at,base_revision,archived FROM definitions ORDER BY created_at").fetchall()
        return builtins + [dict(zip(("id","name","kind","status","revision","hash","created_at","published_at","base_revision","archived"), r)) | {"protected": False} for r in rows]

    def create_draft(self, name: str, definition: dict, base_revision: str | None = None):
        if not name.strip(): raise ValueError("strategy name is required")
        sid = str(uuid.uuid4()); now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT INTO definitions VALUES (?,?,?,?,?,?,?,?,?,?,0)", (sid,name,"custom","draft",1,json.dumps(definition),None,now,None,base_revision))
        return self.get(sid)

    def get(self, sid):
        if sid in BUILT_INS: return {"id": sid, "name": sid, "kind": "builtin", "status": "published", "protected": True, "revision": 1}
        with sqlite3.connect(self.path) as c: row = c.execute("SELECT * FROM definitions WHERE id=?",(sid,)).fetchone()
        if not row: return None
        keys=("id","name","kind","status","revision","definition","hash","created_at","published_at","base_revision","archived")
        out=dict(zip(keys,row)); out["definition"]=json.loads(out["definition"]); out["protected"]=False; return out

    def update(self, sid, definition):
        current=self.get(sid)
        if not current or current.get("status") != "draft": raise ValueError("only drafts are editable")
        with sqlite3.connect(self.path) as c: c.execute("UPDATE definitions SET definition=?,revision=revision+1 WHERE id=?",(json.dumps(definition),sid))
        return self.get(sid)

    def publish(self, sid):
        current=self.get(sid)
        if not current or current.get("status") != "draft": raise ValueError("only drafts can be published")
        verdict=self.interpreter.validate(current["definition"])
        if not verdict["valid"]: raise ValueError("; ".join(verdict["errors"]))
        canonical=json.dumps(current["definition"],sort_keys=True,separators=(",",":")); digest=hashlib.sha256(canonical.encode()).hexdigest(); now=datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path) as c: c.execute("UPDATE definitions SET status='published',hash=?,published_at=? WHERE id=?",(digest,now,sid))
        return self.get(sid)

    def archive(self, sid):
        current=self.get(sid)
        if not current or current.get("protected"): raise ValueError("built-ins cannot be archived")
        with sqlite3.connect(self.path) as c: c.execute("UPDATE definitions SET archived=1 WHERE id=?",(sid,))
        return self.get(sid)
