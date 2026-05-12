"""Tool dispatch — load contracts, validate params, call the right tool.

Extracted from the Bridge so that contract loading and validation is a
separate concern from language server lifecycle.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from tools import TOOL_REGISTRY
from tool_context import ToolContext

# Package root for resolving tool-contracts.json.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


class ToolDispatcher:
    """Validates tool parameters against tool-contracts.json and dispatches.

    Contracts are loaded once and cached.
    """

    def __init__(self) -> None:
        self._contracts: dict[str, dict[str, object]] | None = None

    def call_tool(
        self,
        tool_name: str,
        params: dict[str, object],
        ctx: ToolContext,
    ) -> object:
        """Validate *params* against the contract and dispatch to the tool."""
        contracts = self._load_contracts()
        contract = contracts.get(tool_name)
        if contract is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        self._validate_params(tool_name, params, contract)

        tool_fn = TOOL_REGISTRY.get(tool_name)
        if tool_fn is None:
            raise ValueError(f"Tool not implemented: {tool_name}")
        return tool_fn(params, ctx)

    def _load_contracts(self) -> dict[str, dict[str, object]]:
        """Load tool-contracts.json (lazy, cached)."""
        if self._contracts is not None:
            return self._contracts

        contract_path = _PACKAGE_ROOT / "src" / "tool-contracts.json"
        if not contract_path.is_file():
            raise FileNotFoundError(f"Tool contracts not found: {contract_path}")
        with open(contract_path, encoding="utf-8") as f:
            data = json.load(f)
        self._contracts = data.get("tools", {})
        return self._contracts

    @staticmethod
    def _validate_params(
        tool_name: str,
        params: dict[str, object],
        contract: dict[str, object],
    ) -> None:
        """Validate required params are present and types match the schema."""
        schema = contract.get("params")
        if not isinstance(schema, dict):
            return
        required: list[str] = schema.get("required", []) or []  # type: ignore[assignment]
        for key in required:
            if key not in params:
                raise ValueError(
                    f"Tool '{tool_name}' requires parameter '{key}'"
                )
        try:
            jsonschema.validate(instance=params, schema=schema)
        except jsonschema.ValidationError as exc:
            raise ValueError(
                f"Invalid parameter for tool '{tool_name}': {exc.message}"
            ) from exc
