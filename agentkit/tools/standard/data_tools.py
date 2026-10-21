from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional

from gateway.capability_service import ToolInvocationContext
from gateway.tools.schema import array, input_object, integer, object_value, text


class DataCsvToJsonTool:
    concurrency_safe = True
    input_schema = input_object({"text": text(), "max_rows": integer(minimum=1)}, required=("text",))
    tool_id = "data.csv_to_json"
    side_effect_level = "read_only"
    name = "data.csv_to_json"
    description = "Convert CSV text to JSON array."
    domain = "data"

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
    concurrency_safe = True
    input_schema = input_object({"rows": array(object_value()), "text": text()})
    tool_id = "data.json_to_csv"
    side_effect_level = "read_only"
    name = "data.json_to_csv"
    description = "Convert JSON array to CSV text."
    domain = "data"

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
