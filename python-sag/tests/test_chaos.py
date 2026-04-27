"""Tests for chaos engineering features: template matching, snapshot/restore, test parsing, hybrid SAG proposals."""

import os
import sys
from unittest.mock import MagicMock

import pytest

# Add agent dir to path for analyzer/codegen imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

from sag.file_state import FileStateTracker
from sag.knowledge import KnowledgeEngine


# ---------------------------------------------------------------------------
# Chaos template matching
# ---------------------------------------------------------------------------


class TestChaosTemplateMatching:
    def test_chaos_keywords(self):
        from analyzer import match_template

        assert match_template("run chaos engineering on the codebase") == "chaos"

    def test_fault_injection(self):
        from analyzer import match_template

        assert match_template("inject faults and test resilience") == "chaos"

    def test_reliability(self):
        from analyzer import match_template

        assert match_template("test failure recovery and graceful degradation") == "chaos"

    def test_software_still_works(self):
        from analyzer import match_template

        assert match_template("build a REST API") == "software"

    def test_generic_still_works(self):
        from analyzer import match_template

        assert match_template("help me plan my day") == "generic"

    def test_chaos_template_exists(self):
        from analyzer import TEMPLATES

        assert "chaos" in TEMPLATES
        agents, rationale = TEMPLATES["chaos"]
        assert len(agents) == 5
        roles = {a.role for a in agents}
        assert "Chaos Lead" in roles
        assert "Fault Injector" in roles
        assert "Resilience Observer" in roles
        assert "Blast Radius Analyst" in roles
        assert "Recovery Validator" in roles

    def test_chaos_agents_have_topics(self):
        from analyzer import TEMPLATES

        agents, _ = TEMPLATES["chaos"]
        for agent in agents:
            assert len(agent.topics) > 0, f"{agent.role} has no topics"

    def test_chaos_agents_have_prompts(self):
        from analyzer import TEMPLATES

        agents, _ = TEMPLATES["chaos"]
        for agent in agents:
            assert len(agent.prompt) > 20, f"{agent.role} prompt too short"
            # Chaos agents should reference tools
            if agent.role != "Chaos Lead":
                assert "read_file" in agent.prompt or "search_files" in agent.prompt, \
                    f"{agent.role} prompt doesn't reference tools"


# ---------------------------------------------------------------------------
# Snapshot / Restore
# ---------------------------------------------------------------------------


class TestSnapshotRestore:
    def test_snapshot_creates_temp_dir(self, tmp_path):
        (tmp_path / "main.py").write_text("x = 1")
        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke, str(tmp_path))
        tracker.scan()

        snap_id = tracker.snapshot()
        assert os.path.isdir(snap_id)
        # Clean up
        import shutil
        shutil.rmtree(snap_id)

    def test_snapshot_preserves_files(self, tmp_path):
        (tmp_path / "main.py").write_text("original content")
        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke, str(tmp_path))
        tracker.scan()

        snap_id = tracker.snapshot()

        # Verify snapshot has the file
        assert (os.path.join(snap_id, "main.py"))
        with open(os.path.join(snap_id, "main.py")) as f:
            assert f.read() == "original content"

        import shutil
        shutil.rmtree(snap_id)

    def test_restore_reverts_modifications(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("original")
        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke, str(tmp_path))
        tracker.scan()

        snap_id = tracker.snapshot()

        # Modify the file
        f.write_text("modified!")
        assert f.read_text() == "modified!"

        # Restore
        restored = tracker.restore(snap_id)
        assert f.read_text() == "original"
        assert len(restored) > 0

    def test_restore_removes_new_files(self, tmp_path):
        (tmp_path / "original.py").write_text("keep me")
        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke, str(tmp_path))
        tracker.scan()

        snap_id = tracker.snapshot()

        # Create a new file
        (tmp_path / "injected.py").write_text("fault")
        tracker.scan()

        # Restore should remove the new file
        tracker.restore(snap_id)
        assert not (tmp_path / "injected.py").exists()
        assert (tmp_path / "original.py").exists()

    def test_restore_nonexistent_snapshot(self):
        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke, ".")
        with pytest.raises(FileNotFoundError):
            tracker.restore("/nonexistent/snapshot/path")

    def test_snapshot_no_root_dir(self):
        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke, root_dir="/nonexistent/dir/that/does/not/exist")
        with pytest.raises(FileNotFoundError):
            tracker.snapshot()

    def test_snapshot_preserves_subdirs(self, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "app.py").write_text("app code")
        (tmp_path / "config.yaml").write_text("key: val")

        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke, str(tmp_path))
        tracker.scan()

        snap_id = tracker.snapshot()

        # Modify both
        (sub / "app.py").write_text("corrupted!")
        (tmp_path / "config.yaml").write_text("corrupted!")

        tracker.restore(snap_id)
        assert (sub / "app.py").read_text() == "app code"
        assert (tmp_path / "config.yaml").read_text() == "key: val"

    def test_snapshot_cleans_up(self, tmp_path):
        (tmp_path / "main.py").write_text("test")
        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke, str(tmp_path))
        tracker.scan()

        snap_id = tracker.snapshot()
        assert os.path.isdir(snap_id)

        tracker.restore(snap_id)
        # Snapshot dir should be cleaned up after restore
        assert not os.path.isdir(snap_id)


# ---------------------------------------------------------------------------
# Test result parsing
# ---------------------------------------------------------------------------


class TestTestResultParser:
    def test_parse_pytest_output(self):
        from codegen import TestResultParser

        output = """
============================= test session starts ==============================
collected 5 items

tests/test_app.py::test_create PASSED
tests/test_app.py::test_read PASSED
tests/test_app.py::test_update FAILED
tests/test_app.py::test_delete PASSED
tests/test_app.py::test_list SKIPPED

========================= 3 passed, 1 failed, 1 skipped in 0.42s ==========================
"""
        result = TestResultParser.parse(output, exit_code=1)
        assert result.framework == "pytest"
        assert result.passed == 3
        assert result.failed == 1
        assert result.skipped == 1
        assert result.total == 5
        assert not result.success
        assert len(result.cases) == 5

    def test_parse_pytest_all_pass(self):
        from codegen import TestResultParser

        output = """
tests/test_foo.py::test_one PASSED
tests/test_foo.py::test_two PASSED

============================== 2 passed in 0.01s ===============================
"""
        result = TestResultParser.parse(output, exit_code=0)
        assert result.passed == 2
        assert result.failed == 0
        assert result.success

    def test_parse_go_output(self):
        from codegen import TestResultParser

        output = """
=== RUN   TestAdd
--- PASS: TestAdd (0.00s)
=== RUN   TestSubtract
--- PASS: TestSubtract (0.00s)
=== RUN   TestDivide
--- FAIL: TestDivide (0.00s)
    math_test.go:15: expected 2, got 0
FAIL
"""
        result = TestResultParser.parse(output, exit_code=1)
        assert result.framework == "go"
        assert result.passed == 2
        assert result.failed == 1
        assert result.total == 3
        assert not result.success

    def test_parse_jest_output(self):
        from codegen import TestResultParser

        output = """
 PASS  src/App.test.js
  ✓ renders without crashing (15ms)
  ✓ displays title (8ms)

 FAIL  src/utils.test.js
  ✕ handles edge case

Test Suites: 1 failed, 1 passed, 2 total
Tests:  1 failed, 2 passed, 3 total
"""
        result = TestResultParser.parse(output, exit_code=1)
        assert result.framework == "jest"
        assert result.passed == 2
        assert result.failed == 1
        assert result.total == 3

    def test_parse_generic_tap(self):
        from codegen import TestResultParser

        output = """
ok 1 - test addition
ok 2 - test subtraction
not ok 3 - test division by zero
ok 4 - test multiplication
"""
        result = TestResultParser.parse(output, exit_code=1)
        assert result.framework == "generic"
        assert result.passed == 3
        assert result.failed == 1
        assert result.total == 4

    def test_parse_empty_output(self):
        from codegen import TestResultParser

        result = TestResultParser.parse("", exit_code=0)
        assert result.success
        assert result.total == 1

    def test_parse_exit_code_only(self):
        from codegen import TestResultParser

        result = TestResultParser.parse("some random output", exit_code=1)
        assert not result.success
        assert result.failed == 1

    def test_result_summary(self):
        from codegen import TestResult

        r = TestResult(passed=5, failed=2, errors=1, skipped=3, total=11)
        s = r.summary
        assert "5 passed" in s
        assert "2 failed" in s
        assert "1 errors" in s
        assert "3 skipped" in s

    def test_result_summary_empty(self):
        from codegen import TestResult

        r = TestResult()
        assert r.summary == "no tests"

    def test_test_case_dataclass(self):
        from codegen import TestCase

        tc = TestCase(name="test_foo", status="failed", message="assert 1 == 2")
        assert tc.name == "test_foo"
        assert tc.status == "failed"
        assert tc.message == "assert 1 == 2"


# ---------------------------------------------------------------------------
# SAG proposal parsing
# ---------------------------------------------------------------------------


_VALID_SAG_PROPOSAL = (
    'H v 1 id=proposal src=designer dst=planner ts=0\n'
    'KNOW team.proposal = {"rationale": "Tailored chaos team", '
    '"agents": [{"id": "chaos-lead", "role": "Chaos Lead", "parent": null, '
    '"topics": ["chaos.summary"], "prompt": "You are the Chaos Lead."}, '
    '{"id": "fault-spec", "role": "Fault Specialist", "parent": "chaos-lead", '
    '"topics": ["fault.targets"], "prompt": "You are a Fault Specialist."}]} v 1'
)


class TestSAGProposalParsing:
    def test_valid_sag_proposal(self):
        from analyzer import _parse_proposal_sag

        proposal = _parse_proposal_sag(_VALID_SAG_PROPOSAL)
        assert proposal is not None
        assert len(proposal.agents) == 2
        assert proposal.agents[0].agent_id == "chaos-lead"
        assert proposal.agents[0].parent_id is None
        assert proposal.agents[1].agent_id == "fault-spec"
        assert proposal.agents[1].parent_id == "chaos-lead"
        assert proposal.rationale == "Tailored chaos team"

    def test_fallback_to_json_on_sag_failure(self):
        from analyzer import _parse_proposal_sag

        json_str = '{"rationale": "JSON fallback", "agents": [{"id": "lead", "role": "Lead", "parent": null}]}'
        proposal = _parse_proposal_sag(json_str)
        assert proposal is not None
        assert proposal.agents[0].agent_id == "lead"
        assert proposal.rationale == "JSON fallback"

    def test_returns_none_for_garbage(self):
        from analyzer import _parse_proposal_sag

        assert _parse_proposal_sag("not a SAG message and not JSON either") is None

    def test_sag_with_no_proposal_topic(self):
        from analyzer import _parse_proposal_sag

        sag = (
            'H v 1 id=msg1 src=a dst=b ts=0\n'
            'KNOW other.topic = {"key": "val"} v 1'
        )
        assert _parse_proposal_sag(sag) is None

    def test_build_proposal_from_dict_skips_invalid(self):
        from analyzer import _build_proposal_from_dict

        data = {"agents": [{"id": "a", "role": "A"}, {"bad": True}, {"id": "b", "role": "B"}]}
        proposal = _build_proposal_from_dict(data)
        assert proposal is not None
        assert len(proposal.agents) == 2

    def test_build_proposal_from_dict_empty_agents(self):
        from analyzer import _build_proposal_from_dict

        assert _build_proposal_from_dict({"agents": []}) is None
        assert _build_proposal_from_dict({}) is None


# ---------------------------------------------------------------------------
# Hybrid chaos team generation
# ---------------------------------------------------------------------------


class TestChaosHybridProposal:
    def test_no_client_uses_static_template(self):
        from analyzer import TaskAnalyzer, TEMPLATES

        analyzer = TaskAnalyzer(client=None)
        proposal = analyzer.propose("run chaos on the project")
        static_agents, _ = TEMPLATES["chaos"]
        assert len(proposal.agents) == len(static_agents)
        assert proposal.agents[0].role == "Chaos Lead"

    def test_client_without_context_uses_static_template(self):
        from analyzer import TaskAnalyzer, TEMPLATES

        client = MagicMock()
        analyzer = TaskAnalyzer(client=client)
        # No context → static fallback
        proposal = analyzer.propose("run chaos on the project", context="")
        static_agents, _ = TEMPLATES["chaos"]
        assert len(proposal.agents) == len(static_agents)
        client.complete.assert_not_called()

    def test_client_with_context_calls_llm(self):
        from analyzer import TaskAnalyzer

        client = MagicMock()
        client.complete.return_value = _VALID_SAG_PROPOSAL
        analyzer = TaskAnalyzer(client=client)

        proposal = analyzer.propose("chaos on my project", context="Flask app with src/routes/")
        client.complete.assert_called_once()
        assert proposal is not None
        assert proposal.agents[0].agent_id == "chaos-lead"

    def test_exploration_footer_appended_to_specialists(self):
        from analyzer import TaskAnalyzer, _EXPLORATION_FOOTER

        client = MagicMock()
        client.complete.return_value = _VALID_SAG_PROPOSAL
        analyzer = TaskAnalyzer(client=client)

        proposal = analyzer.propose("chaos on my project", context="Flask app")
        # Root (chaos-lead) should NOT have footer
        assert _EXPLORATION_FOOTER not in proposal.agents[0].prompt
        # Specialist (fault-spec) should have footer
        assert _EXPLORATION_FOOTER in proposal.agents[1].prompt

    def test_llm_failure_falls_back_to_static(self):
        from analyzer import TaskAnalyzer, TEMPLATES

        client = MagicMock()
        client.complete.side_effect = RuntimeError("LLM down")
        analyzer = TaskAnalyzer(client=client)

        proposal = analyzer.propose("chaos on my project", context="some context")
        static_agents, _ = TEMPLATES["chaos"]
        assert len(proposal.agents) == len(static_agents)

    def test_llm_garbage_falls_back_to_static(self):
        from analyzer import TaskAnalyzer, TEMPLATES

        client = MagicMock()
        client.complete.return_value = "I don't know how to respond"
        analyzer = TaskAnalyzer(client=client)

        proposal = analyzer.propose("chaos on my project", context="some context")
        static_agents, _ = TEMPLATES["chaos"]
        assert len(proposal.agents) == len(static_agents)

    def test_footer_content_validation(self):
        from analyzer import _EXPLORATION_FOOTER

        assert "list_directory" in _EXPLORATION_FOOTER
        assert "read_file" in _EXPLORATION_FOOTER
        assert "search_files" in _EXPLORATION_FOOTER
        assert "HARD CONSTRAINTS" in _EXPLORATION_FOOTER
        assert "Never read more than 8 files" in _EXPLORATION_FOOTER

    def test_software_template_not_affected(self):
        """Software template should still use LLM path, not hybrid."""
        from analyzer import TaskAnalyzer

        client = MagicMock()
        client.complete.return_value = _VALID_SAG_PROPOSAL
        analyzer = TaskAnalyzer(client=client)

        # This should go through _propose_llm, not _propose_hybrid
        proposal = analyzer.propose("build a REST API", context="some context")
        # The LLM returned a chaos team, but software path parsed it via SAG too
        client.complete.assert_called_once()
        call_args = client.complete.call_args
        # First arg is system prompt — should be the general analyzer, not chaos
        assert "chaos" not in call_args[0][0].lower()
