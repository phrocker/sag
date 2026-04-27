"""Cost accounting for SAG grove executions.

Provides pricing tiers, per-call metrics recording, message wire-format
analysis, and aggregated accounting reports.  Pure data + logic — no IO,
no UI, no API-specific code.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from sag.minifier import MessageMinifier
from sag.model import Message
from sag.tree import TreeEngine


# ---------------------------------------------------------------------------
# Pricing tiers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PricingTier:
    """USD cost per million tokens for a given model."""

    model: str
    input_cost_per_mtok: float
    output_cost_per_mtok: float

    def compute_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_cost_per_mtok
            + output_tokens * self.output_cost_per_mtok
        ) / 1_000_000


PRICING_TIERS: dict[str, PricingTier] = {
    "claude-sonnet-4-20250514": PricingTier("claude-sonnet-4-20250514", 3.0, 15.0),
    "claude-haiku-3-5": PricingTier("claude-haiku-3-5", 0.80, 4.0),
    "gpt-4o": PricingTier("gpt-4o", 2.50, 10.0),
    "gpt-4o-mini": PricingTier("gpt-4o-mini", 0.15, 0.60),
}


# ---------------------------------------------------------------------------
# Per-call metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallMetrics:
    """Metrics captured from a single LLM API call."""

    agent_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float
    model: str
    timestamp: float


# ---------------------------------------------------------------------------
# Message wire-format metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MessageMetrics:
    """SAG-vs-JSON comparison for a single inter-agent message."""

    source: str
    destination: str
    sag_tokens: int
    json_tokens: int
    tokens_saved: int
    percent_saved: float


# ---------------------------------------------------------------------------
# Agent summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentSummary:
    """Aggregated metrics for one agent across all its calls."""

    agent_id: str
    role: str
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    total_latency_ms: float


# ---------------------------------------------------------------------------
# Accounting report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccountingReport:
    """Full cost accounting report for a grove execution."""

    agent_summaries: list[AgentSummary]
    message_metrics: list[MessageMetrics]
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    total_latency_ms: float
    total_sag_tokens: int
    total_json_tokens: int
    total_wire_savings: int
    wire_savings_percent: float
    model: str
    nl_multiplier: float = 1.5


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class AccountingCollector:
    """Records LLM call metrics and builds accounting reports.

    Thread the same collector instance through instrumented clients and
    the grove runner so all calls are captured in one place.
    """

    def __init__(self, pricing: PricingTier | None = None) -> None:
        self._pricing = pricing
        self._calls: list[CallMetrics] = []
        self._current_agent: str = ""
        self._lock = threading.Lock()

    def set_current_agent(self, agent_id: str) -> None:
        self._current_agent = agent_id

    def get_current_agent(self) -> str:
        return self._current_agent

    def record_call(
        self,
        agent_id: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        model: str,
    ) -> CallMetrics:
        pricing = self._pricing or PRICING_TIERS.get(model)
        cost = pricing.compute_cost(input_tokens, output_tokens) if pricing else 0.0

        metrics = CallMetrics(
            agent_id=agent_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            model=model,
            timestamp=time.time(),
        )
        with self._lock:
            self._calls.append(metrics)
        return metrics

    def analyze_messages(self, messages: list[Message]) -> list[MessageMetrics]:
        results: list[MessageMetrics] = []
        for msg in messages:
            comparison = MessageMinifier.compare_with_json(msg)
            results.append(
                MessageMetrics(
                    source=msg.header.source,
                    destination=msg.header.destination,
                    sag_tokens=comparison.sag_tokens,
                    json_tokens=comparison.json_tokens,
                    tokens_saved=comparison.tokens_saved,
                    percent_saved=comparison.percent_saved,
                )
            )
        return results

    def build_report(
        self, tree: TreeEngine, messages: list[Message]
    ) -> AccountingReport:
        # Aggregate per-agent
        agent_data: dict[str, dict] = {}
        for call in self._calls:
            if call.agent_id not in agent_data:
                agent_data[call.agent_id] = {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "total_latency_ms": 0.0,
                }
            d = agent_data[call.agent_id]
            d["calls"] += 1
            d["input_tokens"] += call.input_tokens
            d["output_tokens"] += call.output_tokens
            d["total_tokens"] += call.total_tokens
            d["cost_usd"] += call.cost_usd
            d["total_latency_ms"] += call.latency_ms

        summaries: list[AgentSummary] = []
        for agent_id, d in agent_data.items():
            node = tree.get_node(agent_id)
            role = node.role if node else agent_id
            summaries.append(
                AgentSummary(
                    agent_id=agent_id,
                    role=role,
                    calls=d["calls"],
                    input_tokens=d["input_tokens"],
                    output_tokens=d["output_tokens"],
                    total_tokens=d["total_tokens"],
                    cost_usd=d["cost_usd"],
                    total_latency_ms=d["total_latency_ms"],
                )
            )

        msg_metrics = self.analyze_messages(messages)

        total_input = sum(c.input_tokens for c in self._calls)
        total_output = sum(c.output_tokens for c in self._calls)
        total_tokens = total_input + total_output
        total_cost = sum(c.cost_usd for c in self._calls)
        total_latency = sum(c.latency_ms for c in self._calls)

        total_sag = sum(m.sag_tokens for m in msg_metrics)
        total_json = sum(m.json_tokens for m in msg_metrics)
        total_wire_savings = total_json - total_sag
        wire_pct = (total_wire_savings * 100.0 / total_json) if total_json > 0 else 0.0

        model = self._calls[0].model if self._calls else ""

        return AccountingReport(
            agent_summaries=summaries,
            message_metrics=msg_metrics,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            total_latency_ms=total_latency,
            total_sag_tokens=total_sag,
            total_json_tokens=total_json,
            total_wire_savings=total_wire_savings,
            wire_savings_percent=wire_pct,
            model=model,
        )

    def get_calls(self) -> list[CallMetrics]:
        return list(self._calls)

    def reset(self) -> None:
        self._calls.clear()
        self._current_agent = ""
