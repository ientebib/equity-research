#!/usr/bin/env python3
"""
Architecture Audit Script.

Detects whether required Evidence-First Research Workspace components exist.
Generates docs/ARCHITECTURE_STATUS.md with component locations.
Exits non-zero if any required components are missing.
"""

import importlib
import inspect
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ComponentCheck:
    """Result of checking a component."""
    name: str
    module_path: str
    exists: bool
    location: str | None = None
    notes: str = ""


def check_import(module_path: str, class_name: str) -> tuple[bool, str | None]:
    """Check if a class can be imported and return its file location."""
    try:
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name, None)
        if cls is None:
            return False, None
        # Get file location
        try:
            file_path = inspect.getfile(cls)
            return True, file_path
        except TypeError:
            return True, module_path
    except ImportError as e:
        return False, str(e)


def check_pipeline_wiring() -> tuple[bool, str]:
    """Check if pipeline has verification and integration stages wired."""
    try:
        from er.coordinator.pipeline import ResearchPipeline
        source = inspect.getsource(ResearchPipeline.run)

        checks = [
            "Stage 3.5: Verification" in source,
            "Stage 3.75: Integration" in source,
            "_run_verification" in source,
            "_run_integration" in source,
            "verified_package=verified_package" in source,
            "cross_vertical_map=cross_vertical_map" in source,
        ]

        if all(checks):
            return True, "All pipeline stages wired correctly"
        else:
            missing = []
            if not checks[0]: missing.append("Stage 3.5 not found")
            if not checks[1]: missing.append("Stage 3.75 not found")
            if not checks[2]: missing.append("_run_verification not called")
            if not checks[3]: missing.append("_run_integration not called")
            if not checks[4]: missing.append("verified_package not passed to synthesis")
            if not checks[5]: missing.append("cross_vertical_map not passed to synthesis")
            return False, f"Missing: {', '.join(missing)}"
    except Exception as e:
        return False, str(e)


def check_citation_support() -> tuple[bool, str]:
    """Check if synthesizer and judge support citations."""
    try:
        from er.agents.synthesizer import SynthesizerAgent
        from er.agents.judge import JudgeAgent

        synth_sig = inspect.signature(SynthesizerAgent.run)
        judge_sig = inspect.signature(JudgeAgent.run)

        synth_ok = "verified_package" in synth_sig.parameters
        judge_ok = "verified_package" in judge_sig.parameters

        if synth_ok and judge_ok:
            return True, "Both synthesizer and judge accept verified_package"
        else:
            issues = []
            if not synth_ok: issues.append("Synthesizer missing verified_package param")
            if not judge_ok: issues.append("Judge missing verified_package param")
            return False, "; ".join(issues)
    except Exception as e:
        return False, str(e)


REQUIRED_COMPONENTS = [
    ("WorkspaceStore", "er.workspace.store", "WorkspaceStore"),
    ("WebResearchService", "er.retrieval.service", "WebResearchService"),
    ("EvidenceCard", "er.retrieval.evidence_cards", "EvidenceCard"),
    ("ThreadBrief", "er.types", "ThreadBrief"),
    ("VerticalDossier", "er.types", "VerticalDossier"),
    ("Fact", "er.types", "Fact"),
    ("VerificationAgent", "er.agents.verifier", "VerificationAgent"),
    ("IntegratorAgent", "er.agents.integrator", "IntegratorAgent"),
    ("VerifiedResearchPackage", "er.types", "VerifiedResearchPackage"),
    ("CrossVerticalMap", "er.types", "CrossVerticalMap"),
]


def run_audit() -> tuple[list[ComponentCheck], bool]:
    """Run the full architecture audit."""
    results = []
    all_pass = True

    # Check each required component
    for name, module_path, class_name in REQUIRED_COMPONENTS:
        exists, location = check_import(module_path, class_name)
        results.append(ComponentCheck(
            name=name,
            module_path=f"{module_path}.{class_name}",
            exists=exists,
            location=location if exists else None,
            notes="" if exists else f"Import failed: {location}"
        ))
        if not exists:
            all_pass = False

    # Check pipeline wiring
    pipeline_ok, pipeline_notes = check_pipeline_wiring()
    results.append(ComponentCheck(
        name="Pipeline Wiring",
        module_path="er.coordinator.pipeline",
        exists=pipeline_ok,
        location="src/er/coordinator/pipeline.py" if pipeline_ok else None,
        notes=pipeline_notes
    ))
    if not pipeline_ok:
        all_pass = False

    # Check citation support
    citation_ok, citation_notes = check_citation_support()
    results.append(ComponentCheck(
        name="Citation Support",
        module_path="er.agents.synthesizer + er.agents.judge",
        exists=citation_ok,
        location="synthesizer.py, judge.py" if citation_ok else None,
        notes=citation_notes
    ))
    if not citation_ok:
        all_pass = False

    return results, all_pass


def generate_status_markdown(results: list[ComponentCheck], all_pass: bool) -> str:
    """Generate ARCHITECTURE_STATUS.md content."""
    lines = [
        "# Architecture Status",
        "",
        f"**Generated:** {datetime.now().isoformat()}",
        f"**Status:** {'✅ ALL COMPONENTS PRESENT' if all_pass else '❌ MISSING COMPONENTS'}",
        "",
        "## Component Checklist",
        "",
        "| Component | Status | Location | Notes |",
        "|-----------|--------|----------|-------|",
    ]

    for r in results:
        status = "✅" if r.exists else "❌"
        location = r.location or "N/A"
        # Truncate long paths
        if len(location) > 50:
            location = "..." + location[-47:]
        notes = r.notes[:50] + "..." if len(r.notes) > 50 else r.notes
        lines.append(f"| {r.name} | {status} | `{location}` | {notes} |")

    lines.extend([
        "",
        "## Architecture Overview",
        "",
        "```",
        "Stage 1: Data Collection",
        "    ↓",
        "Stage 2: Discovery (ThreadBriefs)",
        "    ↓",
        "Stage 3: Deep Research (VerticalDossiers + Facts[])",
        "    ↓",
        "Stage 3.5: Verification (VerifiedResearchPackage)",
        "    ↓",
        "Stage 3.75: Integration (CrossVerticalMap)",
        "    ↓",
        "Stage 4: Synthesis (with citations)",
        "    ↓",
        "Stage 5: Judge (checks citations)",
        "    ↓",
        "Stage 6: Revision",
        "```",
        "",
    ])

    return "\n".join(lines)


def main():
    """Main entry point."""
    print("=" * 60)
    print("ARCHITECTURE AUDIT")
    print("=" * 60)
    print()

    results, all_pass = run_audit()

    # Print results
    for r in results:
        status = "✓" if r.exists else "✗"
        print(f"[{status}] {r.name}")
        if r.exists and r.location:
            print(f"    Location: {r.location}")
        if r.notes:
            print(f"    Notes: {r.notes}")

    print()
    print("=" * 60)

    # Generate and write status markdown
    docs_dir = Path(__file__).parent.parent / "docs"
    docs_dir.mkdir(exist_ok=True)

    status_md = generate_status_markdown(results, all_pass)
    status_path = docs_dir / "ARCHITECTURE_STATUS.md"
    status_path.write_text(status_md)
    print(f"Generated: {status_path}")

    if all_pass:
        print("ALL COMPONENTS PRESENT ✓")
        print("=" * 60)
        return 0
    else:
        print("MISSING COMPONENTS ✗")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
