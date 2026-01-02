"""
K+ Research Backend API
Real-time streaming of equity research pipeline with agent-level visibility.
"""

import asyncio
import json
import os
import sys
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Optional
import traceback

from dotenv import load_dotenv

# Load environment variables from .env file
ROOT = Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Add parent src to path for pipeline imports
sys.path.insert(0, str(ROOT / "src"))

app = FastAPI(title="K+ Research API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== Types ==============

class RunConfig(BaseModel):
    ticker: str
    budget: float = 50.0
    quarters: int = 4
    include_transcripts: bool = True
    use_dual_discovery: bool = True
    use_deep_research: bool = True
    transcripts_dir: Optional[str] = None


@dataclass
class AgentEvent:
    """Event from an agent during pipeline execution."""
    timestamp: str
    event_type: str  # agent_start, agent_progress, agent_complete, agent_error
    agent_name: str
    stage: int
    data: dict = field(default_factory=dict)


@dataclass
class RunSession:
    """Active pipeline run session."""
    run_id: str
    ticker: str
    config: RunConfig
    status: str = "pending"  # pending, running, complete, error, cancelled
    current_stage: int = 0
    current_agent: Optional[str] = None
    cost: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    events: deque = field(default_factory=lambda: deque(maxlen=500))
    task: Optional[asyncio.Task] = None
    error: Optional[str] = None
    result: Optional[dict] = None

    def emit(self, event_type: str, agent_name: str, stage: int, **data):
        """Emit an event to the stream."""
        event = AgentEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            agent_name=agent_name,
            stage=stage,
            data=data,
        )
        self.events.append(event)
        return event


# Global state
active_runs: dict[str, RunSession] = {}
OUTPUT_DIR = ROOT / "output"


# ============== Helpers ==============

def get_output_dir() -> Path:
    return OUTPUT_DIR


def list_completed_runs(limit: int = 50) -> list[dict]:
    """List completed runs from output directory."""
    runs = []
    output_dir = get_output_dir()

    if not output_dir.exists():
        return runs

    for run_dir in sorted(output_dir.iterdir(), reverse=True):
        if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
            continue

        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            continue

        try:
            manifest = json.loads(manifest_path.read_text())
            runs.append({
                "run_id": manifest.get("run_id", run_dir.name),
                "ticker": manifest.get("ticker", "???"),
                "started_at": manifest.get("started_at"),
                "completed_at": manifest.get("completed_at"),
                "duration": manifest.get("duration_seconds", 0),
                "total_cost": manifest.get("total_cost_usd", 0),
                "verdict": manifest.get("final_verdict", {}),
                "status": "complete" if manifest.get("phase") == "complete" else manifest.get("phase", "unknown"),
            })

            if len(runs) >= limit:
                break
        except Exception:
            continue

    return runs


def load_run_data(run_id: str) -> dict:
    """Load all data for a completed run."""
    run_dir = get_output_dir() / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    data = {"run_id": run_id, "stages": {}}

    # Load manifest
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        data["manifest"] = json.loads(manifest_path.read_text())

    # Load costs
    costs_path = run_dir / "costs.json"
    if costs_path.exists():
        data["costs"] = json.loads(costs_path.read_text())

    # Load report
    report_path = run_dir / "report.md"
    if report_path.exists():
        data["report"] = report_path.read_text()

    # Load stage outputs
    stage_files = [
        ("stage1", "stage1_company_context.json"),
        ("stage2_internal", "stage2_internal_discovery.json"),
        ("stage2_external", "stage2_external_discovery.json"),
        ("stage2", "stage2_discovery.json"),
        ("stage3_groups", "stage3_group_research.json"),
        ("stage3_verticals", "stage3_verticals.json"),
        ("stage4_claude", "stage4_claude_synthesis.json"),
        ("stage4_gpt", "stage4_gpt_synthesis.json"),
        ("stage5", "stage5_editorial_feedback.json"),
        ("stage6", "stage6_final_report.json"),
    ]

    for key, filename in stage_files:
        file_path = run_dir / filename
        if file_path.exists():
            try:
                data["stages"][key] = json.loads(file_path.read_text())
            except Exception:
                pass

    # Extract structured report data for frontend
    if "stage6" in data["stages"]:
        s6 = data["stages"]["stage6"]
        data["structured_report"] = {
            "investment_view": s6.get("investment_view"),
            "conviction": s6.get("conviction"),
            "confidence": s6.get("overall_confidence"),
            "thesis_summary": s6.get("thesis_summary"),
            "full_report": s6.get("full_report"),
        }

        # Parse scenarios from the full_report JSON block if present
        full_report = s6.get("full_report", "")
        if "```json" in full_report:
            try:
                json_start = full_report.rfind("```json") + 7
                json_end = full_report.rfind("```")
                if json_start < json_end:
                    report_json = json.loads(full_report[json_start:json_end])
                    data["structured_report"]["scenarios"] = report_json.get("scenarios")
                    data["structured_report"]["top_risks"] = report_json.get("top_risks")
                    data["structured_report"]["key_debates"] = report_json.get("key_debates")
                    data["structured_report"]["evidence_gaps"] = report_json.get("evidence_gaps")
                    data["structured_report"]["downgrade_triggers"] = report_json.get("downgrade_triggers")
            except:
                pass

    # Extract editorial feedback
    if "stage5" in data["stages"]:
        s5 = data["stages"]["stage5"]
        data["editorial_feedback"] = {
            "preferred_synthesis": s5.get("preferred_synthesis"),
            "preference_reasoning": s5.get("preference_reasoning"),
            "claude_score": s5.get("claude_score"),
            "gpt_score": s5.get("gpt_score"),
            "key_differentiators": s5.get("key_differentiators"),
            "key_strengths": s5.get("key_strengths"),
            "key_weaknesses": s5.get("key_weaknesses"),
        }

    # Extract discovery threads for traceability
    if "stage2" in data["stages"]:
        s2 = data["stages"]["stage2"]
        data["discovery"] = {
            "official_segments": s2.get("official_segments", []),
            "research_threads": s2.get("research_threads", []),
        }

    # Extract vertical analyses for traceability
    if "stage3_verticals" in data["stages"]:
        data["verticals"] = data["stages"]["stage3_verticals"]

    # Extract both syntheses for comparison
    if "stage4_claude" in data["stages"]:
        s4c = data["stages"]["stage4_claude"]
        data["claude_synthesis"] = {
            "investment_view": s4c.get("investment_view"),
            "conviction": s4c.get("conviction"),
            "confidence": s4c.get("overall_confidence"),
            "thesis_summary": s4c.get("thesis_summary"),
            "full_report": s4c.get("full_report"),
        }

    if "stage4_gpt" in data["stages"]:
        s4g = data["stages"]["stage4_gpt"]
        data["gpt_synthesis"] = {
            "investment_view": s4g.get("investment_view"),
            "conviction": s4g.get("conviction"),
            "confidence": s4g.get("overall_confidence"),
            "thesis_summary": s4g.get("thesis_summary"),
            "full_report": s4g.get("full_report"),
        }

    return data


# ============== Pipeline Runner with Event Streaming ==============

async def run_pipeline_with_events(session: RunSession):
    """Run the equity research pipeline with real-time event streaming."""
    try:
        from er.coordinator.pipeline import ResearchPipeline, PipelineConfig
        from er.config import Settings

        session.status = "running"
        session.started_at = datetime.now(timezone.utc)

        session.emit("run_start", "Pipeline", 0,
            ticker=session.ticker,
            budget=session.config.budget
        )

        # Create output directory for this run
        run_output_dir = OUTPUT_DIR / session.run_id
        run_output_dir.mkdir(parents=True, exist_ok=True)

        # Load transcripts if directory provided
        manual_transcripts = None
        if session.config.transcripts_dir:
            transcripts_path = Path(session.config.transcripts_dir)
            if transcripts_path.exists():
                transcripts_file = transcripts_path / "transcripts.json"
                if transcripts_file.exists():
                    manual_transcripts = json.loads(transcripts_file.read_text())

        # Create pipeline config
        pipeline_config = PipelineConfig(
            output_dir=run_output_dir,
            include_transcripts=session.config.include_transcripts,
            num_transcript_quarters=session.config.quarters,
            manual_transcripts=manual_transcripts,
            use_dual_discovery=session.config.use_dual_discovery,
            use_deep_research_verticals=session.config.use_deep_research,
            max_budget_usd=session.config.budget,
        )

        # Progress callback that emits events
        def progress_callback(
            stage: int,
            stage_name: str,
            status: str,
            detail: str = "",
            cost_usd: float = 0.0,
        ):
            session.current_stage = stage
            session.cost = cost_usd

            # Determine agent name from stage and detail
            agent_name = stage_name
            if "Claude" in detail:
                agent_name = "Claude Opus"
            elif "GPT" in detail:
                agent_name = "GPT-5.2"
            elif "Gemini" in detail:
                agent_name = "Gemini Deep Research"

            session.current_agent = agent_name

            event_type = "stage_start" if status == "starting" else f"stage_{status}"
            session.emit(event_type, agent_name, stage,
                stage_name=stage_name,
                status=status,
                detail=detail,
                cost=cost_usd,
            )

        # Initialize and run pipeline
        settings = Settings()
        pipeline = ResearchPipeline(
            settings=settings,
            config=pipeline_config,
            progress_callback=progress_callback,
        )

        result = await pipeline.run(session.ticker)

        # Pipeline complete
        session.status = "complete"
        session.completed_at = datetime.now(timezone.utc)
        session.result = {
            "investment_view": result.final_report.investment_view,
            "conviction": result.final_report.conviction,
            "confidence": result.final_report.overall_confidence,
            "thesis_summary": result.final_report.thesis_summary,
            "preferred_synthesis": result.editorial_feedback.preferred_synthesis,
            "total_cost": result.total_cost_usd,
            "duration": result.duration_seconds,
        }

        # Write manifest
        manifest = {
            "run_id": session.run_id,
            "ticker": session.ticker,
            "started_at": session.started_at.isoformat(),
            "completed_at": session.completed_at.isoformat(),
            "duration_seconds": result.duration_seconds,
            "total_cost_usd": result.total_cost_usd,
            "phase": "complete",
            "final_verdict": {
                "investment_view": result.final_report.investment_view,
                "conviction": result.final_report.conviction,
                "confidence": result.final_report.overall_confidence,
            },
        }
        (run_output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        # Write report
        (run_output_dir / "report.md").write_text(result.to_report_markdown())

        session.emit("run_complete", "Pipeline", 6,
            verdict=session.result,
            total_cost=result.total_cost_usd,
            duration=result.duration_seconds,
        )

    except asyncio.CancelledError:
        session.status = "cancelled"
        session.error = "Run cancelled by user"
        session.emit("run_cancelled", "Pipeline", session.current_stage)
        raise

    except Exception as e:
        session.status = "error"
        session.error = str(e)
        session.emit("run_error", "Pipeline", session.current_stage,
            error=str(e),
            traceback=traceback.format_exc(),
        )
        raise

    finally:
        # Keep session for 5 minutes after completion for clients to catch up
        await asyncio.sleep(300)
        if session.run_id in active_runs:
            del active_runs[session.run_id]


# ============== API Routes ==============

@app.get("/")
async def root():
    return {
        "name": "K+ Research API",
        "version": "1.0.0",
        "status": "operational",
        "active_runs": len(active_runs),
    }


@app.get("/runs")
async def get_runs(limit: int = Query(50, ge=1, le=100)):
    """List all runs (active and completed)."""
    completed = list_completed_runs(limit)

    active = []
    for session in active_runs.values():
        active.append({
            "run_id": session.run_id,
            "ticker": session.ticker,
            "status": session.status,
            "current_stage": session.current_stage,
            "current_agent": session.current_agent,
            "cost": session.cost,
            "started_at": session.started_at.isoformat() if session.started_at else None,
        })

    return {"completed": completed, "active": active}


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get details of a specific run."""
    # Check active runs first
    if run_id in active_runs:
        session = active_runs[run_id]
        return {
            "run_id": session.run_id,
            "ticker": session.ticker,
            "status": session.status,
            "current_stage": session.current_stage,
            "current_agent": session.current_agent,
            "cost": session.cost,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "error": session.error,
            "result": session.result,
            "events": [asdict(e) for e in list(session.events)[-100:]],  # Last 100 events
        }

    # Load from disk
    return load_run_data(run_id)


@app.get("/runs/{run_id}/report")
async def get_report(run_id: str):
    """Get the markdown report for a completed run."""
    run_dir = get_output_dir() / run_id
    report_path = run_dir / "report.md"

    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    return {"report": report_path.read_text()}


@app.get("/runs/{run_id}/stage/{stage}")
async def get_stage_output(run_id: str, stage: str):
    """Get output from a specific stage."""
    data = load_run_data(run_id)

    if stage not in data.get("stages", {}):
        raise HTTPException(status_code=404, detail=f"Stage '{stage}' not found")

    return data["stages"][stage]


@app.post("/runs/start")
async def start_run(config: RunConfig, background_tasks: BackgroundTasks):
    """Start a new research pipeline run."""
    ticker = config.ticker.upper().strip()
    if not ticker or len(ticker) > 5:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    run_id = f"run_{uuid.uuid4().hex[:16]}"

    session = RunSession(
        run_id=run_id,
        ticker=ticker,
        config=config,
    )
    active_runs[run_id] = session

    # Start pipeline in background
    task = asyncio.create_task(run_pipeline_with_events(session))
    session.task = task

    return {
        "run_id": run_id,
        "ticker": ticker,
        "status": "starting",
        "message": f"Started equity research for {ticker}",
        "stream_url": f"/runs/{run_id}/stream",
    }


@app.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel an active run."""
    if run_id not in active_runs:
        raise HTTPException(status_code=404, detail="Run not found or already completed")

    session = active_runs[run_id]
    if session.task and not session.task.done():
        session.task.cancel()

    return {"message": "Run cancelled", "run_id": run_id}


@app.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    """Delete a run and its data. Only works for completed/failed runs, not active ones."""
    import shutil
    
    # Don't allow deleting active runs
    if run_id in active_runs:
        raise HTTPException(status_code=400, detail="Cannot delete an active run. Cancel it first.")
    
    run_dir = get_output_dir() / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    
    try:
        shutil.rmtree(run_dir)
        return {"message": "Run deleted", "run_id": run_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete run: {str(e)}")


@app.get("/runs/{run_id}/stream")
async def stream_run(run_id: str):
    """Stream real-time events from a run via SSE."""
    if run_id not in active_runs:
        # Check if it's a completed run
        run_dir = get_output_dir() / run_id
        if run_dir.exists():
            raise HTTPException(status_code=400, detail="Run already completed - use GET /runs/{run_id} instead")
        raise HTTPException(status_code=404, detail="Run not found")

    return StreamingResponse(
        event_generator(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


async def event_generator(run_id: str) -> AsyncGenerator[str, None]:
    """Generate SSE events for a pipeline run."""
    session = active_runs.get(run_id)
    if not session:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Run not found'})}\n\n"
        return

    last_idx = 0

    # Send initial state
    yield f"data: {json.dumps({'type': 'connected', 'run_id': run_id, 'status': session.status})}\n\n"

    while run_id in active_runs:
        session = active_runs[run_id]
        events = list(session.events)

        # Send new events
        while last_idx < len(events):
            event = events[last_idx]
            yield f"data: {json.dumps(asdict(event))}\n\n"
            last_idx += 1

        # Check if done
        if session.status in ("complete", "error", "cancelled"):
            yield f"data: {json.dumps({'type': 'stream_end', 'status': session.status, 'result': session.result, 'error': session.error})}\n\n"
            break

        await asyncio.sleep(0.3)

    yield f"data: {json.dumps({'type': 'disconnected'})}\n\n"


# ============== Config/Prompt Endpoints ==============

STAGE_AGENTS = [
    {"stage": 1, "name": "DataOrchestrator", "model": "gpt-5.2", "file": "data_orchestrator.py",
     "description": "Fetches SEC filings, financials, news, and analyst data from FMP API"},
    {"stage": 2, "name": "DiscoveryAgent", "model": "gpt-5.2", "file": "discovery.py",
     "description": "Internal discovery using 7 analytical lenses to identify value drivers"},
    {"stage": 2, "name": "ExternalDiscoveryAgent", "model": "claude-sonnet-4", "file": "external_discovery.py",
     "description": "External competitive intelligence with web search"},
    {"stage": 3, "name": "VerticalAnalystAgent", "model": "gemini-2.0-flash-thinking-exp", "file": "vertical_analyst.py",
     "description": "Deep research with Gemini's Deep Research capability"},
    {"stage": 4, "name": "SynthesizerAgent (Claude)", "model": "claude-opus-4-5-20251101", "file": "synthesizer.py",
     "description": "Synthesizes all research into investment thesis with extended thinking"},
    {"stage": 4, "name": "SynthesizerAgent (GPT)", "model": "gpt-5.2", "file": "synthesizer.py",
     "description": "Parallel synthesis for comparison"},
    {"stage": 5, "name": "JudgeAgent", "model": "claude-opus-4-5-20251101", "file": "judge.py",
     "description": "Compares both syntheses and produces editorial feedback"},
    {"stage": 6, "name": "Revision", "model": "varies", "file": "synthesizer.py",
     "description": "Winner revises based on judge feedback"},
]


@app.get("/config/agents")
async def get_agents():
    """Get all agent configurations."""
    return {"agents": STAGE_AGENTS}


@app.get("/config/prompts/{agent_file}")
async def get_agent_prompt(agent_file: str):
    """Get the source code for an agent (contains prompts)."""
    agents_dir = ROOT / "src" / "er" / "agents"

    # Validate filename
    if not agent_file.endswith(".py"):
        agent_file = f"{agent_file}.py"

    file_path = agents_dir / agent_file
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Agent file not found: {agent_file}")

    return {
        "file": agent_file,
        "path": str(file_path),
        "content": file_path.read_text(),
    }


@app.put("/config/prompts/{agent_file}")
async def update_agent_prompt(agent_file: str, body: dict):
    """Update an agent's source file (prompts)."""
    agents_dir = ROOT / "src" / "er" / "agents"

    if not agent_file.endswith(".py"):
        agent_file = f"{agent_file}.py"

    file_path = agents_dir / agent_file
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Agent file not found: {agent_file}")

    content = body.get("content")
    if not content:
        raise HTTPException(status_code=400, detail="Missing 'content' in request body")

    # Backup original
    backup_path = file_path.with_suffix(".py.bak")
    backup_path.write_text(file_path.read_text())

    # Write new content
    file_path.write_text(content)

    return {
        "message": f"Updated {agent_file}",
        "backup": str(backup_path),
    }


# ============== Financials Endpoint ==============

@app.get("/financials/{ticker}")
async def get_financials(ticker: str):
    """Fetch live financial data from FMP API for a ticker."""
    from er.data.fmp_client import FMPClient
    from er.evidence.store import EvidenceStore

    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 5:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    # Create a temporary evidence store (we don't persist for this endpoint)
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        evidence_store = EvidenceStore(Path(tmpdir))
        await evidence_store.init()  # Initialize the store before using
        client = FMPClient(evidence_store)

        try:
            # Fetch all financial data
            context = await client.get_full_context(ticker, include_transcripts=False)
            await client.close()
            await evidence_store.close()

            # Structure the response for frontend consumption
            return {
                "ticker": ticker,
                "profile": context.get("profile", {}),
                "income_statement": {
                    "annual": context.get("income_statement_annual", []),
                    "quarterly": context.get("income_statement_quarterly", []),
                },
                "balance_sheet": {
                    "annual": context.get("balance_sheet_annual", []),
                },
                "cash_flow": {
                    "annual": context.get("cash_flow_annual", []),
                },
                "segmentation": {
                    "product": context.get("revenue_product_segmentation", []),
                    "geographic": context.get("revenue_geographic_segmentation", []),
                },
                "news": context.get("news", []),
                "analyst": {
                    "estimates": context.get("analyst_estimates", []),
                    "price_target_summary": context.get("price_target_summary", {}),
                    "price_target_consensus": context.get("price_target_consensus", {}),
                    "grades": context.get("analyst_grades", []),
                },
            }
        except Exception as e:
            await client.close()
            await evidence_store.close()
            raise HTTPException(status_code=500, detail=f"Failed to fetch financials: {str(e)}")


# ============== Main ==============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
