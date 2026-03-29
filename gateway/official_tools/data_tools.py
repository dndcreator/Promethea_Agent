from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional

from gateway.tool_service import ToolInvocationContext


class DataCsvToJsonTool:
    tool_id = "data.csv_to_json"
    name = "data.csv_to_json"
    description = "Convert CSV text to JSON array."
    official = True
    official_domain = "data"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        text = str((args or {}).get("text") or "")
        if not text.strip():
            raise ValueError("text is required")
        max_rows = int((args or {}).get("max_rows") or 2000)
        max_rows = max(1, min(max_rows, 20000))
        reader = csv.DictReader(io.StringIO(text))
        rows: List[Dict[str, Any]] = []
        for idx, row in enumerate(reader):
            if idx >= max_rows:
                break
            rows.append(dict(row))
        return {"count": len(rows), "rows": rows}


class DataJsonToCsvTool:
    tool_id = "data.json_to_csv"
    name = "data.json_to_csv"
    description = "Convert JSON array to CSV text."
    official = True
    official_domain = "data"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        raw = (args or {}).get("rows")
        if raw is None:
            text = str((args or {}).get("text") or "")
            if not text.strip():
                raise ValueError("rows or text is required")
            raw = json.loads(text)
        if not isinstance(raw, list):
            raise ValueError("rows must be a list")
        rows = [item for item in raw if isinstance(item, dict)]
        if not rows:
            return {"count": 0, "csv": ""}
        fieldnames: List[str] = []
        for row in rows:
            for key in row.keys():
                if key not in fieldnames:
                    fieldnames.append(str(key))

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return {"count": len(rows), "csv": buf.getvalue(), "columns": fieldnames}

