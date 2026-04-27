import time

from sag.accounting import (
    AccountingCollector,
    AccountingReport,
    CallMetrics,
    MessageMetrics,
    PricingTier,
    PRICING_TIERS,
)
from sag.model import Header, KnowledgeStatement, Message
from sag.tree import TreeEngine


# ---------------------------------------------------------------------------
# PricingTier
# ---------------------------------------------------------------------------


def test_pricing_tier_compute_cost():
    tier = PricingTier("test-model", 3.0, 15.0)
    cost = tier.compute_cost(1_000_000, 0)
    assert cost == 3.0


def test_pricing_tier_output_cost():
    tier = PricingTier("test-model", 3.0, 15.0)
    cost = tier.compute_cost(0, 1_000_000)
    assert cost == 15.0


def test_pricing_tier_mixed_cost():
    tier = PricingTier("test-model", 3.0, 15.0)
    cost = tier.compute_cost(500, 200)
    expected = (500 * 3.0 + 200 * 15.0) / 1_000_000
    assert abs(cost - expected) < 1e-10


def test_pricing_tier_zero_tokens():
    tier = PricingTier("test-model", 3.0, 15.0)
    assert tier.compute_cost(0, 0) == 0.0


def test_pricing_tiers_registry():
    assert "claude-sonnet-4-20250514" in PRICING_TIERS
    assert "gpt-4o" in PRICING_TIERS
    assert "gpt-4o-mini" in PRICING_TIERS


# ---------------------------------------------------------------------------
# AccountingCollector — record_call
# ---------------------------------------------------------------------------


def _build_simple_tree() -> TreeEngine:
    tree = TreeEngine()
    tree.add_root("root", "PM", topics=["plan.summary"])
    tree.add_child("root", "a", "Agent A", topics=["a.result"])
    tree.add_child("root", "b", "Agent B", topics=["b.result"])
    return tree


def test_collector_record_call():
    pricing = PricingTier("test", 3.0, 15.0)
    collector = AccountingCollector(pricing)

    m = collector.record_call("agent-a", 100, 50, 120.5, "test")
    assert isinstance(m, CallMetrics)
    assert m.agent_id == "agent-a"
    assert m.input_tokens == 100
    assert m.output_tokens == 50
    assert m.total_tokens == 150
    assert m.latency_ms == 120.5
    expected_cost = (100 * 3.0 + 50 * 15.0) / 1_000_000
    assert abs(m.cost_usd - expected_cost) < 1e-10


def test_collector_get_calls():
    collector = AccountingCollector(PricingTier("t", 1.0, 1.0))
    collector.record_call("a", 10, 5, 10.0, "t")
    collector.record_call("b", 20, 10, 20.0, "t")
    assert len(collector.get_calls()) == 2


def test_collector_reset():
    collector = AccountingCollector(PricingTier("t", 1.0, 1.0))
    collector.set_current_agent("x")
    collector.record_call("a", 10, 5, 10.0, "t")
    collector.reset()
    assert len(collector.get_calls()) == 0
    assert collector.get_current_agent() == ""


def test_collector_current_agent():
    collector = AccountingCollector()
    assert collector.get_current_agent() == ""
    collector.set_current_agent("pm")
    assert collector.get_current_agent() == "pm"


# ---------------------------------------------------------------------------
# AccountingCollector — analyze_messages
# ---------------------------------------------------------------------------


def _make_message(src: str, dst: str) -> Message:
    header = Header(
        version=1,
        message_id=f"{src}-1",
        source=src,
        destination=dst,
        timestamp=int(time.time()),
    )
    stmt = KnowledgeStatement(topic=f"{src}.result", value="test data", version=1)
    return Message(header=header, statements=[stmt])


def test_collector_analyze_messages():
    collector = AccountingCollector()
    msgs = [_make_message("a", "root"), _make_message("b", "root")]
    metrics = collector.analyze_messages(msgs)
    assert len(metrics) == 2
    for m in metrics:
        assert isinstance(m, MessageMetrics)
        assert m.sag_tokens > 0
        assert m.json_tokens > 0
        assert m.json_tokens >= m.sag_tokens
        assert m.tokens_saved >= 0


def test_collector_analyze_empty_messages():
    collector = AccountingCollector()
    assert collector.analyze_messages([]) == []


# ---------------------------------------------------------------------------
# AccountingCollector — build_report
# ---------------------------------------------------------------------------


def test_collector_build_report():
    tree = _build_simple_tree()
    pricing = PricingTier("test", 3.0, 15.0)
    collector = AccountingCollector(pricing)

    collector.record_call("a", 100, 50, 100.0, "test")
    collector.record_call("b", 200, 80, 150.0, "test")
    collector.record_call("root", 300, 120, 200.0, "test")

    msgs = [_make_message("a", "root"), _make_message("b", "root")]
    report = collector.build_report(tree, msgs)

    assert isinstance(report, AccountingReport)
    assert len(report.agent_summaries) == 3
    assert len(report.message_metrics) == 2
    assert report.total_input_tokens == 600
    assert report.total_output_tokens == 250
    assert report.total_tokens == 850
    assert report.total_cost_usd > 0
    assert report.total_latency_ms == 450.0
    assert report.model == "test"


def test_collector_build_report_agent_roles():
    tree = _build_simple_tree()
    collector = AccountingCollector(PricingTier("t", 1.0, 1.0))
    collector.record_call("a", 10, 5, 10.0, "t")

    report = collector.build_report(tree, [])
    assert report.agent_summaries[0].role == "Agent A"


def test_collector_build_empty_report():
    tree = _build_simple_tree()
    collector = AccountingCollector()
    report = collector.build_report(tree, [])

    assert report.total_tokens == 0
    assert report.total_cost_usd == 0.0
    assert report.total_latency_ms == 0.0
    assert len(report.agent_summaries) == 0
    assert len(report.message_metrics) == 0
    assert report.wire_savings_percent == 0.0
    assert report.model == ""


def test_collector_multi_call_aggregation():
    tree = _build_simple_tree()
    pricing = PricingTier("test", 3.0, 15.0)
    collector = AccountingCollector(pricing)

    # Agent 'a' makes two calls
    collector.record_call("a", 100, 50, 100.0, "test")
    collector.record_call("a", 150, 60, 120.0, "test")

    report = collector.build_report(tree, [])

    assert len(report.agent_summaries) == 1
    summary = report.agent_summaries[0]
    assert summary.agent_id == "a"
    assert summary.calls == 2
    assert summary.input_tokens == 250
    assert summary.output_tokens == 110
    assert summary.total_tokens == 360
    assert summary.total_latency_ms == 220.0


def test_collector_wire_savings_percent():
    tree = _build_simple_tree()
    collector = AccountingCollector(PricingTier("t", 1.0, 1.0))
    collector.record_call("a", 10, 5, 10.0, "t")

    msgs = [_make_message("a", "root")]
    report = collector.build_report(tree, msgs)

    assert report.total_sag_tokens > 0
    assert report.total_json_tokens > 0
    assert report.total_wire_savings >= 0
    if report.total_json_tokens > 0:
        expected_pct = report.total_wire_savings * 100.0 / report.total_json_tokens
        assert abs(report.wire_savings_percent - expected_pct) < 0.01


def test_report_nl_multiplier_default():
    tree = _build_simple_tree()
    collector = AccountingCollector()
    report = collector.build_report(tree, [])
    assert report.nl_multiplier == 1.5


def test_collector_auto_pricing_lookup():
    """When no explicit pricing is given, collector looks up from PRICING_TIERS."""
    collector = AccountingCollector()
    m = collector.record_call("a", 1_000_000, 0, 10.0, "claude-sonnet-4-20250514")
    assert m.cost_usd == 3.0


def test_collector_unknown_model_zero_cost():
    """Unknown model with no explicit pricing yields zero cost."""
    collector = AccountingCollector()
    m = collector.record_call("a", 1000, 500, 10.0, "unknown-model")
    assert m.cost_usd == 0.0
