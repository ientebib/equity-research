# K+ Research Frontend - Implementation Plan

**Goal**: Build an award-winning frontend interface for the equity research pipeline with real-time agent visualization, report viewing, and full configuration control.

**Name**: K+ Research (ala CCRU)
**Aesthetic**: Legible dark terminal - clean, data-dense, Bloomberg-inspired but modern

---

## User Requirements (from interview)

1. **User Flow**: Dashboard multi-run - see multiple runs, history sidebar, switch between them
2. **Granularity**: Agent-level detail with reasoning preview - show each agent's activity, tokens, and output snippets
3. **Config Access**: Full control - edit prompts, models, temperature, add/remove agents
4. **MVP Priority**: Run & monitor first - start runs, see real-time progress, view final report
5. **Layout**: Something cool with split views
6. **Dev Mode**: Backend required from day one - no mocks, real integration

---

## Architecture

### Backend (FastAPI) - `/frontend/api/server.py` ✅ DONE
- Real-time SSE streaming of pipeline events
- Connects to actual equity research pipeline
- Endpoints:
  - `GET /` - Health check
  - `GET /runs` - List all runs (active + completed)
  - `GET /runs/{run_id}` - Get run details
  - `GET /runs/{run_id}/report` - Get markdown report
  - `GET /runs/{run_id}/stage/{stage}` - Get stage output
  - `POST /runs/start` - Start new run
  - `POST /runs/{run_id}/cancel` - Cancel active run
  - `GET /runs/{run_id}/stream` - SSE event stream
  - `GET /config/agents` - List agent configurations
  - `GET /config/prompts/{agent_file}` - Get agent source code
  - `PUT /config/prompts/{agent_file}` - Update agent source

### Frontend (Next.js 14)
- App Router with TypeScript
- Tailwind CSS with custom K+ theme
- Zustand for state management
- Framer Motion for animations
- SSE for real-time updates

---

## Implementation Tasks

### Phase 1: Core Infrastructure ✅ MOSTLY DONE
- [x] Next.js 14 setup with TypeScript and Tailwind
- [x] Custom K+ Research CSS theme (`globals.css`)
- [x] Type definitions (`types/index.ts`)
- [x] Zustand store with persistence (`store/research.ts`)
- [x] API client with SSE support (`lib/api.ts`)
- [x] Utility functions (`lib/utils.ts`)
- [x] FastAPI backend with pipeline integration

### Phase 2: Main Layout & Navigation 🔄 IN PROGRESS
- [x] Logo component (`components/Logo.tsx`)
- [x] Pipeline stages visualization (`components/PipelineStages.tsx`)
- [x] Run panel component (`components/RunPanel.tsx`)
- [ ] **Main dashboard layout** - Three-column split view:
  - Left sidebar (240px): Run history list, new run button
  - Center (flex): Active run monitoring OR report viewer
  - Right panel (400px, collapsible): Stage details, agent info, config
- [ ] **Navigation header** with:
  - K+ Research logo
  - Current run ticker badge
  - Cost/budget display
  - Settings button

### Phase 3: Run Monitoring View
- [ ] **Run history sidebar** (`components/RunHistory.tsx`)
  - List of completed runs with verdict badges
  - Active runs at top with live status
  - Click to view run details
  - Search/filter by ticker
- [ ] **Live pipeline monitor** (`components/PipelineMonitor.tsx`)
  - Visual stage progress (horizontal timeline)
  - Current agent indicator with model badge
  - Live cost tracker (bar + numbers)
  - Estimated time remaining
  - Cancel button
- [ ] **Agent activity panel** (`components/AgentActivity.tsx`)
  - List of recent agent events
  - Expandable reasoning snippets
  - Token counts per agent
  - Error display with stack trace

### Phase 4: Report Viewer
- [ ] **Report page** (`app/runs/[runId]/page.tsx`)
  - Full markdown rendering with custom styling
  - Table of contents sidebar
  - Section navigation
  - Evidence citations as tooltips
- [ ] **Report header** with:
  - Ticker and company name
  - Verdict badge (BUY/HOLD/SELL)
  - Conviction and confidence meters
  - Download as PDF button
  - Share link
- [ ] **Comparison view** (optional)
  - Side-by-side Claude vs GPT synthesis
  - Judge scores and reasoning

### Phase 5: Configuration Panel
- [ ] **Config page** (`app/config/page.tsx`)
  - Agent list with stage grouping
  - Model selector per agent
  - Click agent to edit prompt
- [ ] **Prompt editor** (`components/PromptEditor.tsx`)
  - Monaco editor with Python syntax
  - Save/revert buttons
  - Diff view against backup
  - Warning about pipeline restart
- [ ] **Pipeline settings**
  - Default budget
  - Default quarters
  - Dual discovery toggle
  - Deep research toggle

### Phase 6: Polish & UX
- [ ] **Keyboard shortcuts**
  - `Cmd+N` - New run
  - `Cmd+K` - Command palette
  - `Esc` - Close panels
  - `1-6` - Jump to stage
- [ ] **Loading states**
  - Skeleton loaders for lists
  - Pulse animations for active items
- [ ] **Error handling**
  - Toast notifications
  - Retry mechanisms
  - Graceful degradation
- [ ] **Responsive design**
  - Collapsible sidebars on mobile
  - Touch-friendly controls

---

## File Structure

```
frontend/
├── api/
│   └── server.py          # FastAPI backend ✅
├── src/
│   ├── app/
│   │   ├── globals.css    # K+ theme ✅
│   │   ├── layout.tsx     # Root layout
│   │   ├── page.tsx       # Dashboard (main)
│   │   ├── runs/
│   │   │   └── [runId]/
│   │   │       └── page.tsx  # Run detail/report
│   │   └── config/
│   │       └── page.tsx   # Configuration
│   ├── components/
│   │   ├── Logo.tsx       ✅
│   │   ├── PipelineStages.tsx ✅
│   │   ├── RunPanel.tsx   ✅
│   │   ├── RunHistory.tsx
│   │   ├── PipelineMonitor.tsx
│   │   ├── AgentActivity.tsx
│   │   ├── ReportViewer.tsx
│   │   ├── PromptEditor.tsx
│   │   └── ui/            # Shared UI components
│   ├── lib/
│   │   ├── api.ts         ✅
│   │   └── utils.ts       ✅
│   ├── store/
│   │   └── research.ts    ✅
│   ├── types/
│   │   └── index.ts       ✅
│   └── hooks/
│       ├── useRun.ts      # Hook for SSE streaming
│       └── useKeyboard.ts # Keyboard shortcuts
├── package.json
└── PLAN.md               # This file
```

---

## Running the Application

### Backend
```bash
cd frontend/api
pip install fastapi uvicorn
python server.py
# Runs on http://localhost:8000
```

### Frontend
```bash
cd frontend
npm run dev
# Runs on http://localhost:3000
```

### Environment Variables
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Design System

### Colors (CSS Variables)
- `--kp-void`: #08090a (darkest background)
- `--kp-abyss`: #0c0d0f
- `--kp-surface`: #121416
- `--kp-elevated`: #1a1c20
- `--kp-border`: #2a2d33
- `--kp-green`: #3ddc97 (primary action, success)
- `--kp-cyan`: #5bc0eb (accent)
- `--kp-amber`: #f5b942 (warning)
- `--kp-red`: #f25f5c (error, sell)
- `--kp-text`: #f0f2f5
- `--kp-text-secondary`: #b8bcc4
- `--kp-text-muted`: #6b7280

### Typography
- Display: Space Grotesk (headings)
- Body: IBM Plex Sans
- Mono: IBM Plex Mono (code, numbers)

### Components
- `.kp-panel` - Card with border
- `.kp-btn` - Button
- `.kp-btn-primary` - Green primary button
- `.kp-input` - Text input
- `.kp-verdict-buy/hold/sell` - Verdict badges
- `.kp-ticker` - Ticker symbol badge
- `.kp-label` - Small uppercase label
- `.kp-mono` - Monospace text

---

## Next Steps (for next session)

1. Build the main dashboard layout with three-column split view
2. Create the run history sidebar component
3. Implement the SSE hook for real-time updates
4. Wire up the "Start New Run" flow end-to-end
5. Test with actual pipeline execution

---

## Notes

- The backend (`server.py`) is complete and ready to use
- The CSS theme and core components are in place
- Need to complete the main page layout and wire everything together
- Focus on the "happy path" first: start run → monitor → view report
