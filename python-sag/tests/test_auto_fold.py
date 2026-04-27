"""Tests for auto-fold context compression in the tool loop."""

import sys
import os

# Add agent dir to path for tool_client imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

from sag.fold import FoldEngine

# Import the helpers from tool_client
from tool_client import _estimate_tokens, _fold_conversation, CompletionResult


class TestEstimateTokens:
    def test_empty(self):
        assert _estimate_tokens([]) == 0

    def test_simple_message(self):
        msgs = [{"role": "user", "content": "hello world"}]
        tokens = _estimate_tokens(msgs)
        # "hello world" = 11 chars / 4 ≈ 2
        assert tokens > 0

    def test_tool_result_message(self):
        msgs = [
            {"role": "user", "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "abc",
                    "content": "x" * 400,
                }
            ]}
        ]
        tokens = _estimate_tokens(msgs)
        assert tokens == 100  # 400 chars / 4

    def test_multiple_messages(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        tokens = _estimate_tokens(msgs)
        assert tokens > 0


class TestFoldConversation:
    def test_no_fold_engine(self):
        msgs = [{"role": "user", "content": "hi"}]
        result, folds = _fold_conversation(msgs, 1000, fold_engine=None)
        assert result is msgs
        assert folds == 0

    def test_no_fold_under_budget(self):
        fold = FoldEngine()
        msgs = [{"role": "user", "content": "hi"}]
        result, folds = _fold_conversation(msgs, 1000, fold_engine=fold)
        assert folds == 0

    def test_fold_when_over_budget(self):
        fold = FoldEngine()
        # Create conversation that exceeds budget
        # Each tool result has 1000 chars = 250 tokens
        # 5 of them = 1250 tokens, budget = 500, threshold = 0.5 = 250
        msgs = [{"role": "user", "content": "start"}]
        for i in range(5):
            msgs.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"call_{i}",
                        "content": f"result data {'x' * 800} end",
                    }
                ],
            })

        result, folds = _fold_conversation(msgs, 500, fold_engine=fold)
        # Should fold some of the earlier tool results
        assert folds > 0
        assert fold.get_fold_count() > 0

    def test_keeps_last_one_tool_result(self):
        fold = FoldEngine()
        msgs = [{"role": "user", "content": "start"}]
        for i in range(4):
            msgs.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"call_{i}",
                        "content": f"long result {'x' * 500}",
                    }
                ],
            })

        result, folds = _fold_conversation(msgs, 100, fold_engine=fold)

        # Last tool result should be preserved
        last_msg = result[-1]
        content = last_msg.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    # Should NOT be folded (full content)
                    assert "folded" not in item["content"]

        # Second-to-last tool result should be folded
        second_last = result[-2]
        content = second_last.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    assert "folded" in item["content"]

    def test_zero_budget(self):
        fold = FoldEngine()
        msgs = [{"role": "user", "content": "hi"}]
        result, folds = _fold_conversation(msgs, 0, fold_engine=fold)
        assert folds == 0

    def test_no_tool_results(self):
        fold = FoldEngine()
        msgs = [
            {"role": "user", "content": "x" * 10000},
            {"role": "assistant", "content": "y" * 10000},
        ]
        result, folds = _fold_conversation(msgs, 100, fold_engine=fold)
        assert folds == 0  # Nothing to fold

    def test_short_tool_results_not_folded(self):
        fold = FoldEngine()
        msgs = [{"role": "user", "content": "start"}]
        # Add many short tool results — each < 200 chars, won't fold
        for i in range(10):
            msgs.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"call_{i}",
                        "content": f"ok",
                    }
                ],
            })

        result, folds = _fold_conversation(msgs, 10, fold_engine=fold)
        assert folds == 0  # Content too short to fold


class TestCompletionResult:
    def test_folds_performed_default(self):
        r = CompletionResult(text="hello")
        assert r.folds_performed == 0

    def test_folds_performed_set(self):
        r = CompletionResult(text="hello", folds_performed=3)
        assert r.folds_performed == 3
