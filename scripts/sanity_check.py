#!/usr/bin/env python3
"""
Comprehensive sanity check for the equity research codebase.

Run with: python scripts/sanity_check.py

Checks:
1. All module imports work
2. Dataclass fields are consistent across the codebase
3. No attribute errors waiting to happen
4. CLI loads correctly
5. Type conversions in checkpoint loading work
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    """Run a check and record the result."""
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {name}")
        return True
    else:
        FAILED += 1
        print(f"  ✗ {name}")
        if detail:
            print(f"    → {detail}")
        return False


def section(name: str) -> None:
    """Print a section header."""
    print(f"\n{'='*60}")
    print(f" {name}")
    print(f"{'='*60}\n")


def test_imports():
    """Test that all modules import correctly."""
    section("Module Imports")

    modules = [
        "er.types",
        "er.budget",
        "er.exceptions",
        "er.validation",
        "er.config",
        "er.logging",
        "er.manifest",
        "er.agents.base",
        "er.agents.data_orchestrator",
        "er.agents.discovery",
        "er.agents.vertical_analyst",
        "er.agents.synthesizer",
        "er.agents.judge",
        "er.agents.fact_checker",
        "er.agents.challenge_responder",
        "er.llm.base",
        "er.llm.openai_client",
        "er.llm.gemini_client",
        "er.llm.anthropic_client",
        "er.llm.router",
        "er.coordinator.pipeline",
        "er.coordinator.event_store",
        "er.data.fmp_client",
        "er.data.price_client",
        "er.evidence.store",
        "er.cache.file_cache",
        "er.cli.main",
        "er.cli.progress",
    ]

    for module in modules:
        try:
            __import__(module)
            check(module, True)
        except Exception as e:
            check(module, False, str(e))


def test_type_consistency():
    """Test that dataclass fields are used consistently."""
    section("Type Consistency")

    from er.types import (
        CompanyContext,
        DiscoveryOutput,
        DiscoveredThread,
        ResearchGroup,
        SynthesisOutput,
        EditorialFeedback,
        VerticalAnalysis,
        GroupResearchOutput,
        RunState,
        Phase,
        ThreadType,
    )
    from er.budget import BudgetTracker

    # Check DiscoveryOutput fields
    do_fields = set(DiscoveryOutput.__dataclass_fields__.keys())
    expected_do_fields = {
        "official_segments", "research_threads", "research_groups",
        "cross_cutting_themes", "optionality_candidates", "data_gaps",
        "conflicting_signals", "evidence_ids", "discovery_timestamp"
    }
    check(
        "DiscoveryOutput has expected fields",
        do_fields == expected_do_fields,
        f"Got: {do_fields}, Expected: {expected_do_fields}"
    )

    # Check DiscoveredThread fields
    dt_fields = set(DiscoveredThread.__dataclass_fields__.keys())
    expected_dt_fields = {
        "thread_id", "name", "description", "thread_type", "priority",
        "discovery_lens", "is_official_segment", "official_segment_name",
        "value_driver_hypothesis", "research_questions", "evidence_ids"
    }
    check(
        "DiscoveredThread has expected fields",
        dt_fields == expected_dt_fields,
        f"Got: {dt_fields}, Expected: {expected_dt_fields}"
    )

    # Check ResearchGroup fields
    rg_fields = set(ResearchGroup.__dataclass_fields__.keys())
    expected_rg_fields = {
        "group_id", "name", "theme", "vertical_ids", "key_questions",
        "grouping_rationale", "shared_context", "valuation_approach", "focus"
    }
    check(
        "ResearchGroup has expected fields",
        rg_fields == expected_rg_fields,
        f"Got: {rg_fields}, Expected: {expected_rg_fields}"
    )

    # Check BudgetTracker has total_cost_usd (not total_cost)
    bt = BudgetTracker(budget_limit=100.0)
    check(
        "BudgetTracker.total_cost_usd exists",
        hasattr(bt, "total_cost_usd"),
        "BudgetTracker should have total_cost_usd attribute"
    )
    check(
        "BudgetTracker.total_cost does NOT exist",
        not hasattr(bt, "total_cost"),
        "BudgetTracker should NOT have total_cost attribute (use total_cost_usd)"
    )

    # Check RunState doesn't have completed_at
    rs = RunState.create("TEST", 100.0)
    check(
        "RunState.completed_at does NOT exist",
        not hasattr(rs, "completed_at"),
        "RunState should NOT have completed_at attribute"
    )

    # Check Phase enum values
    check("Phase.SYNTHESIZE exists", hasattr(Phase, "SYNTHESIZE"))
    check("Phase.SYNTHESIS does NOT exist", not hasattr(Phase, "SYNTHESIS"))


def test_pipeline_checkpoint_loading():
    """Test that pipeline checkpoint loading uses correct fields."""
    section("Pipeline Checkpoint Loading")

    from er.types import DiscoveredThread, DiscoveryOutput, ResearchGroup, ThreadType

    # Simulate loading from checkpoint
    test_data = {
        "official_segments": ["Segment A", "Segment B"],
        "research_threads": [{
            "thread_id": "thread_abc123",
            "name": "Test Thread",
            "description": "Test description",
            "thread_type": "segment",
            "priority": 1,
            "discovery_lens": "official_structure",
            "is_official_segment": True,
            "official_segment_name": "Segment A",
            "value_driver_hypothesis": "Test hypothesis",
            "research_questions": ["Q1", "Q2"],
            "evidence_ids": ["ev_1"],
        }],
        "research_groups": [{
            "group_id": "group_xyz789",
            "name": "Core Business",
            "theme": "Established revenue",
            "vertical_ids": ["thread_abc123"],
            "key_questions": ["How fast?"],
            "grouping_rationale": "Same model",
            "shared_context": "Context",
            "valuation_approach": "DCF",
            "focus": "Revenue",
        }],
        "cross_cutting_themes": ["Theme1"],
        "optionality_candidates": ["Option1"],
        "data_gaps": [],
        "conflicting_signals": [],
        "evidence_ids": ["ev_1"],
    }

    # Test thread conversion
    try:
        threads = []
        for t in test_data.get("research_threads", []):
            thread_type_str = t.get("thread_type", "segment")
            if isinstance(thread_type_str, str):
                t["thread_type"] = ThreadType(thread_type_str)
            if "research_questions" in t and isinstance(t["research_questions"], list):
                t["research_questions"] = tuple(t["research_questions"])
            if "evidence_ids" in t and isinstance(t["evidence_ids"], list):
                t["evidence_ids"] = tuple(t["evidence_ids"])
            threads.append(DiscoveredThread(**t))
        check("DiscoveredThread from checkpoint", len(threads) == 1)
    except Exception as e:
        check("DiscoveredThread from checkpoint", False, str(e))

    # Test group conversion
    try:
        groups = []
        for g in test_data.get("research_groups", []):
            groups.append(ResearchGroup(**g))
        check("ResearchGroup from checkpoint", len(groups) == 1)
    except Exception as e:
        check("ResearchGroup from checkpoint", False, str(e))

    # Test full DiscoveryOutput
    try:
        discovery = DiscoveryOutput(
            official_segments=test_data.get("official_segments", []),
            research_threads=threads,
            research_groups=groups,
            cross_cutting_themes=test_data.get("cross_cutting_themes", []),
            optionality_candidates=test_data.get("optionality_candidates", []),
            data_gaps=test_data.get("data_gaps", []),
            conflicting_signals=test_data.get("conflicting_signals", []),
            evidence_ids=test_data.get("evidence_ids", []),
        )
        check("DiscoveryOutput from checkpoint", True)
        check("DiscoveryOutput.research_threads accessible", len(discovery.research_threads) == 1)
    except Exception as e:
        check("DiscoveryOutput from checkpoint", False, str(e))


def test_pipeline_attributes():
    """Test that pipeline uses correct attribute names."""
    section("Pipeline Attribute Usage")

    import ast

    pipeline_path = Path(__file__).parent.parent / "src" / "er" / "coordinator" / "pipeline.py"
    source = pipeline_path.read_text()

    # Check for incorrect attribute usages
    bad_patterns = [
        ("discovery_output.verticals", "should be discovery_output.research_threads"),
        ("budget_tracker.total_cost ", "should be budget_tracker.total_cost_usd"),
        ("run_state.completed_at", "RunState doesn't have completed_at"),
        ("Phase.SYNTHESIS", "should be Phase.SYNTHESIZE"),
    ]

    for pattern, reason in bad_patterns:
        # Allow for method names (like total_cost_usd)
        if pattern == "budget_tracker.total_cost ":
            # Special case - check it's not followed by _usd
            found = "budget_tracker.total_cost" in source and "budget_tracker.total_cost_usd" not in source.replace("budget_tracker.total_cost ", "budget_tracker.total_cost_usd ")
        else:
            found = pattern in source
        check(f"No '{pattern}' in pipeline.py", not found, reason)


def test_cli_loads():
    """Test that CLI app loads correctly."""
    section("CLI Loading")

    try:
        from er.cli.main import app
        check("CLI app imports", True)

        # Check app has expected commands (Typer stores them in registered_groups and registered_commands)
        # Get command names from the Typer app
        command_names = set()
        for cmd in app.registered_commands:
            if hasattr(cmd, 'name') and cmd.name:
                command_names.add(cmd.name)
            elif hasattr(cmd, 'callback') and cmd.callback:
                command_names.add(cmd.callback.__name__)

        # Also check if functions exist as they define commands
        from er.cli import main as cli_module
        has_analyze = hasattr(cli_module, 'analyze') and callable(getattr(cli_module, 'analyze'))
        has_config = hasattr(cli_module, 'config') and callable(getattr(cli_module, 'config'))
        has_version = hasattr(cli_module, 'version') and callable(getattr(cli_module, 'version'))

        check("CLI has 'analyze' command", has_analyze or "analyze" in command_names)
        check("CLI has 'config' command", has_config or "config" in command_names)
        check("CLI has 'version' command", has_version or "version" in command_names)
    except Exception as e:
        check("CLI app imports", False, str(e))


def test_progress_display():
    """Test that progress display works."""
    section("Progress Display")

    try:
        from rich.console import Console
        from er.cli.progress import PipelineProgress

        console = Console(force_terminal=True)
        progress = PipelineProgress(console, "TEST", 100.0)
        check("PipelineProgress initializes", True)

        # Test update
        progress.update(1, "Data Collection", "running", "Testing...")
        check("PipelineProgress.update works", True)
    except Exception as e:
        check("PipelineProgress", False, str(e))


def test_agent_contexts():
    """Test that all agents can be initialized with proper context."""
    section("Agent Initialization")

    try:
        from er.agents.base import AgentContext
        from er.config import Settings
        from er.llm.router import LLMRouter
        from er.evidence.store import EvidenceStore
        from er.budget import BudgetTracker
        from pathlib import Path
        import tempfile

        # Create minimal context
        settings = Settings()
        evidence_store = EvidenceStore(cache_dir=Path(tempfile.gettempdir()) / "er_test")
        budget_tracker = BudgetTracker(budget_limit=100.0)
        llm_router = LLMRouter(settings=settings)

        context = AgentContext(
            settings=settings,
            llm_router=llm_router,
            evidence_store=evidence_store,
            budget_tracker=budget_tracker,
        )
        check("AgentContext creates", True)

        # Test each agent
        from er.agents.data_orchestrator import DataOrchestratorAgent
        from er.agents.discovery import DiscoveryAgent
        from er.agents.vertical_analyst import VerticalAnalystAgent
        from er.agents.synthesizer import SynthesizerAgent
        from er.agents.judge import JudgeAgent

        agents = [
            ("DataOrchestratorAgent", DataOrchestratorAgent),
            ("DiscoveryAgent", DiscoveryAgent),
            ("VerticalAnalystAgent", VerticalAnalystAgent),
            ("SynthesizerAgent", SynthesizerAgent),
            ("JudgeAgent", JudgeAgent),
        ]

        for name, agent_class in agents:
            try:
                agent = agent_class(context)
                check(f"{name} initializes", True)
            except Exception as e:
                check(f"{name} initializes", False, str(e))

    except Exception as e:
        check("Agent initialization setup", False, str(e))


def main():
    """Run all sanity checks."""
    global PASSED, FAILED

    print("\n" + "="*60)
    print(" EQUITY RESEARCH SANITY CHECK")
    print("="*60)

    test_imports()
    test_type_consistency()
    test_pipeline_checkpoint_loading()
    test_pipeline_attributes()
    test_cli_loads()
    test_progress_display()
    test_agent_contexts()

    # Summary
    print("\n" + "="*60)
    print(" SUMMARY")
    print("="*60)
    total = PASSED + FAILED
    print(f"\n  Total: {total} checks")
    print(f"  Passed: {PASSED} ✓")
    print(f"  Failed: {FAILED} ✗")
    print()

    if FAILED == 0:
        print("  🎉 All checks passed!")
        return 0
    else:
        print("  ⚠️  Some checks failed. Review the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
