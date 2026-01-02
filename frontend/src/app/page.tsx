'use client';

import { useEffect, useRef, useState } from 'react';
import { api, Run, StructuredReport, EditorialFeedback, CostBreakdown, Discovery, VerticalAnalysis, Synthesis, FinancialsData, IncomeStatement, NewsItem } from '@/lib/api';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type View = 'home' | 'archive' | 'running' | 'report';
type ReportTab = 'report' | 'discovery' | 'verticals' | 'synthesis' | 'financials' | 'costs';

interface DisplayRun {
  id: string;
  ticker: string;
  status: string;
  createdAt: string;
  totalCost?: number;
  currentStage?: number;
  isActive: boolean;
  verdict?: {
    investmentView: string;
    conviction: string;
    confidence: number;
  };
}

interface FullRunData {
  run_id: string;
  ticker: string;
  report?: string;
  structured_report?: StructuredReport;
  editorial_feedback?: EditorialFeedback;
  costs?: CostBreakdown;
  discovery?: Discovery;
  verticals?: VerticalAnalysis[];
  claude_synthesis?: Synthesis;
  gpt_synthesis?: Synthesis;
  manifest?: {
    started_at?: string;
    completed_at?: string;
    duration_seconds?: number;
    total_cost_usd?: number;
  };
}

function mapRun(run: Run, isActive: boolean): DisplayRun {
  return {
    id: run.run_id,
    ticker: run.ticker,
    status: run.status || 'unknown',
    createdAt: run.started_at || new Date().toISOString(),
    totalCost: run.total_cost || run.manifest?.total_cost_usd,
    currentStage: run.current_stage,
    isActive,
    verdict: run.verdict ? {
      investmentView: run.verdict.investment_view,
      conviction: run.verdict.conviction,
      confidence: run.verdict.confidence
    } : run.manifest?.final_verdict ? {
      investmentView: run.manifest.final_verdict.investment_view,
      conviction: run.manifest.final_verdict.conviction,
      confidence: run.manifest.final_verdict.confidence
    } : undefined
  };
}

// ===================== COMPONENTS =====================

function VerdictHero({ verdict, confidence, conviction }: { verdict: string; confidence: number; conviction?: string }) {
  const isNegative = verdict.toUpperCase() === 'SELL';

  return (
    <div className="mb-8 pb-8 border-b border-[var(--paper-darker)]">
      <div className="flex items-end gap-8">
        <div className={`text-7xl font-display font-black tracking-tight ${
          isNegative ? 'text-[var(--signal)]' : 'text-[var(--ink)]'
        }`}>
          {verdict.toUpperCase()}
        </div>
        <div className="pb-2 space-y-3">
          {conviction && (
            <div className={`inline-block px-3 py-1 text-xs font-mono uppercase tracking-wider ${
              conviction.toLowerCase().includes('high')
                ? 'bg-[var(--ink)] text-[var(--paper)]'
                : 'border border-[var(--paper-darker)]'
            }`}>
              {conviction}
            </div>
          )}
          <div>
            <div className="text-label mb-1">CONFIDENCE</div>
            <div className="flex items-center gap-3">
              <div className="w-40 h-2 bg-[var(--paper-darker)]">
                <div
                  className="h-full bg-[var(--ink)] transition-all duration-1000"
                  style={{ width: `${confidence * 100}%` }}
                />
              </div>
              <span className="text-data font-medium">{Math.round(confidence * 100)}%</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function TabButton({ active, onClick, children, count }: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  count?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2.5 text-xs font-mono uppercase tracking-wider transition-all flex items-center gap-2 border-b-2 ${
        active
          ? 'border-[var(--ink)] text-[var(--ink)]'
          : 'border-transparent text-[var(--ink-faded)] hover:text-[var(--ink)] hover:border-[var(--paper-darker)]'
      }`}
    >
      {children}
      {count !== undefined && count > 0 && (
        <span className={`text-[10px] px-1.5 py-0.5 rounded-sm ${
          active ? 'bg-[var(--ink)] text-[var(--paper)]' : 'bg-[var(--paper-dark)]'
        }`}>
          {count}
        </span>
      )}
    </button>
  );
}


// Thread type labels with descriptions
const THREAD_TYPE_INFO: Record<string, { label: string; description: string }> = {
  segment: { label: 'Segment Analysis', description: 'Official business segments' },
  cross_cutting: { label: 'Cross-Cutting Themes', description: 'Themes that span multiple segments' },
  optionality: { label: 'Hidden Optionality', description: 'Underappreciated value drivers' },
};

function ThreadTypeSection({ type, threads }: { type: string; threads: any[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const info = THREAD_TYPE_INFO[type] || { label: type, description: '' };

  return (
    <div className="mb-8">
      <div className="flex items-baseline gap-3 mb-4 pb-2 border-b border-[var(--paper-darker)]">
        <h3 className="text-sm font-mono uppercase tracking-wider">{info.label}</h3>
        <span className="text-xs text-[var(--ink-ghost)]">{threads.length} threads</span>
      </div>

      <div className="space-y-1">
        {threads.map((thread, i) => (
          <div key={thread.thread_id || i}>
            <button
              onClick={() => setExpanded(expanded === thread.thread_id ? null : thread.thread_id)}
              className={`w-full text-left px-4 py-3 flex items-start gap-3 transition-colors ${
                expanded === thread.thread_id
                  ? 'bg-[var(--paper-dark)]'
                  : 'hover:bg-[var(--paper-dark)]'
              }`}
            >
              <span className="text-xs font-mono text-[var(--signal)] mt-0.5 shrink-0">
                {String(i + 1).padStart(2, '0')}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{thread.name}</div>
                <div className="text-xs text-[var(--ink-faded)] mt-0.5">
                  {thread.research_questions?.length || 0} questions · Priority {thread.priority}
                </div>
              </div>
              <span className="text-[var(--ink-ghost)] text-sm shrink-0">
                {expanded === thread.thread_id ? '−' : '+'}
              </span>
            </button>

            {expanded === thread.thread_id && (
              <div className="px-4 pb-4 bg-[var(--paper-dark)] border-t border-[var(--paper-darker)]">
                <div className="pt-4 pl-7 space-y-4">
                  {thread.value_driver_hypothesis && (
                    <div>
                      <div className="text-label mb-1">HYPOTHESIS</div>
                      <p className="text-sm text-[var(--ink-light)]">{thread.value_driver_hypothesis}</p>
                    </div>
                  )}

                  {thread.research_questions && thread.research_questions.length > 0 && (
                    <div>
                      <div className="text-label mb-2">QUESTIONS ASKED</div>
                      <div className="space-y-2">
                        {thread.research_questions.map((q: string, qi: number) => (
                          <div key={qi} className="flex gap-2 text-sm">
                            <span className="text-[var(--signal)] shrink-0">→</span>
                            <span className="text-[var(--ink-light)]">{q}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function DiscoveryView({ discovery }: { discovery: Discovery }) {
  // Group threads by type
  const grouped = discovery.research_threads?.reduce((acc, thread) => {
    const type = thread.thread_type || 'other';
    if (!acc[type]) acc[type] = [];
    acc[type].push(thread);
    return acc;
  }, {} as Record<string, any[]>) || {};

  // Order: segment first, then cross_cutting, then optionality, then others
  const typeOrder = ['segment', 'cross_cutting', 'optionality'];
  const sortedTypes = [
    ...typeOrder.filter(t => grouped[t]),
    ...Object.keys(grouped).filter(t => !typeOrder.includes(t))
  ];

  const totalQuestions = discovery.research_threads?.reduce(
    (sum, t) => sum + (t.research_questions?.length || 0), 0
  ) || 0;

  return (
    <div>
      {/* Summary stats */}
      <div className="flex gap-6 mb-8 pb-6 border-b border-[var(--paper-darker)]">
        <div>
          <div className="text-2xl font-display font-bold">{discovery.research_threads?.length || 0}</div>
          <div className="text-xs text-[var(--ink-faded)] uppercase tracking-wider">Research Threads</div>
        </div>
        <div>
          <div className="text-2xl font-display font-bold">{totalQuestions}</div>
          <div className="text-xs text-[var(--ink-faded)] uppercase tracking-wider">Questions Asked</div>
        </div>
        {discovery.official_segments && (
          <div>
            <div className="text-2xl font-display font-bold">{discovery.official_segments.length}</div>
            <div className="text-xs text-[var(--ink-faded)] uppercase tracking-wider">Official Segments</div>
          </div>
        )}
      </div>

      {/* Official segments pills */}
      {discovery.official_segments && discovery.official_segments.length > 0 && (
        <div className="mb-8">
          <div className="text-label mb-3">OFFICIAL SEGMENTS</div>
          <div className="flex flex-wrap gap-2">
            {discovery.official_segments.map((seg, i) => (
              <span key={i} className="px-3 py-1.5 text-xs font-mono bg-[var(--paper-dark)] border border-[var(--paper-darker)]">
                {seg}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Grouped threads */}
      {sortedTypes.map(type => (
        <ThreadTypeSection key={type} type={type} threads={grouped[type]} />
      ))}
    </div>
  );
}

// Parse markdown headings for TOC
interface TocItem {
  id: string;
  text: string;
  level: number;
}

function parseTableOfContents(markdown: string): TocItem[] {
  const lines = markdown.split('\n');
  const toc: TocItem[] = [];

  lines.forEach((line, i) => {
    const h1Match = line.match(/^# (.+)$/);
    const h2Match = line.match(/^## (.+)$/);
    const h3Match = line.match(/^### (.+)$/);

    if (h2Match) {
      const text = h2Match[1].trim();
      const id = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
      toc.push({ id, text, level: 2 });
    } else if (h3Match) {
      const text = h3Match[1].trim();
      const id = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
      toc.push({ id, text, level: 3 });
    }
  });

  return toc;
}

function ReportViewer({ report, thesis }: { report: string; thesis?: string }) {
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const toc = parseTableOfContents(report);

  // Group TOC into main sections (h2) with subsections (h3)
  const groupedToc: { main: TocItem; subs: TocItem[] }[] = [];
  toc.forEach(item => {
    if (item.level === 2) {
      groupedToc.push({ main: item, subs: [] });
    } else if (item.level === 3 && groupedToc.length > 0) {
      groupedToc[groupedToc.length - 1].subs.push(item);
    }
  });

  const scrollToSection = (id: string) => {
    const element = document.getElementById(id);
    if (element) {
      const offset = 120; // Account for sticky header
      const top = element.getBoundingClientRect().top + window.scrollY - offset;
      window.scrollTo({ top, behavior: 'smooth' });
      setActiveSection(id);
    }
  };

  // Check if table has chartable revenue/growth data
  const isChartableTable = (rows: any[]): { chartable: boolean; type: string } => {
    if (rows.length < 2) return { chartable: false, type: '' };
    const headers = rows[0]?.map((c: any) => String(c?.props?.children || c).toLowerCase()) || [];

    // Check for quarterly revenue table
    if (headers.some((h: string) => h.includes('quarter')) &&
        headers.some((h: string) => h.includes('revenue') || h.includes('growth'))) {
      return { chartable: true, type: 'revenue' };
    }
    // Check for scenario table
    if (headers.some((h: string) => h.includes('scenario'))) {
      return { chartable: true, type: 'scenario' };
    }
    return { chartable: false, type: '' };
  };

  // Extract cell text
  const getCellText = (cell: any): string => {
    if (typeof cell === 'string') return cell;
    if (cell?.props?.children) {
      if (Array.isArray(cell.props.children)) {
        return cell.props.children.map(getCellText).join('');
      }
      return getCellText(cell.props.children);
    }
    return String(cell || '');
  };

  // Parse revenue value like "$56.6B" to number
  const parseRevenue = (str: string): number => {
    const match = str.match(/\$?([\d.]+)\s*(B|M|K)?/i);
    if (!match) return 0;
    const num = parseFloat(match[1]);
    const mult = match[2]?.toUpperCase();
    if (mult === 'B') return num * 1000;
    if (mult === 'M') return num;
    if (mult === 'K') return num / 1000;
    return num;
  };

  // Parse percentage like "+15%" to number
  const parseGrowth = (str: string): number => {
    const match = str.match(/([+-]?\d+(?:\.\d+)?)\s*%/);
    return match ? parseFloat(match[1]) : 0;
  };

  // Custom renderer to add IDs to headings and charts to tables
  const components = {
    h2: ({ children, ...props }: any) => {
      const text = String(children);
      const id = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
      return (
        <h2 id={id} className="scroll-mt-32" {...props}>
          {children}
        </h2>
      );
    },
    h3: ({ children, ...props }: any) => {
      const text = String(children);
      const id = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
      return (
        <h3 id={id} className="scroll-mt-32" {...props}>
          {children}
        </h3>
      );
    },
    table: ({ children, ...props }: any) => {
      // Extract rows from table
      const rows: any[] = [];
      const processChildren = (node: any) => {
        if (!node) return;
        if (Array.isArray(node)) {
          node.forEach(processChildren);
        } else if (node?.type === 'thead' || node?.type === 'tbody') {
          processChildren(node.props?.children);
        } else if (node?.type === 'tr') {
          const cells = Array.isArray(node.props?.children)
            ? node.props.children
            : [node.props?.children];
          rows.push(cells.filter(Boolean));
        }
      };
      processChildren(children);

      const { chartable, type } = isChartableTable(rows);

      if (chartable && type === 'revenue' && rows.length > 1) {
        // Parse the data
        const headers = rows[0].map(getCellText);
        const revenueIdx = headers.findIndex((h: string) => h.toLowerCase().includes('revenue'));
        const growthIdx = headers.findIndex((h: string) => h.toLowerCase().includes('growth'));
        const labelIdx = 0;

        const data = rows.slice(1).map(row => ({
          label: getCellText(row[labelIdx]),
          revenue: revenueIdx >= 0 ? parseRevenue(getCellText(row[revenueIdx])) : 0,
          growth: growthIdx >= 0 ? parseGrowth(getCellText(row[growthIdx])) : 0,
          revenueStr: revenueIdx >= 0 ? getCellText(row[revenueIdx]) : '',
          growthStr: growthIdx >= 0 ? getCellText(row[growthIdx]) : '',
        }));

        const maxRevenue = Math.max(...data.map(d => d.revenue));

        return (
          <div className="my-6 p-4 bg-[var(--paper-dark)] border border-[var(--paper-darker)]">
            <div className="space-y-3">
              {data.map((d, i) => (
                <div key={i} className="flex items-center gap-4">
                  <div className="w-20 text-xs font-mono text-[var(--ink-faded)] shrink-0">{d.label}</div>
                  <div className="flex-1 flex items-center gap-2">
                    <div className="flex-1 h-6 bg-[var(--paper-darker)] relative overflow-hidden">
                      <div
                        className="h-full bg-[var(--ink)] transition-all duration-500"
                        style={{ width: `${(d.revenue / maxRevenue) * 100}%` }}
                      />
                    </div>
                    <span className="text-sm font-mono w-16 text-right">{d.revenueStr}</span>
                    {d.growthStr && (
                      <span className={`text-xs font-mono w-12 text-right ${
                        d.growth > 0 ? 'text-[#2d5a27]' : d.growth < 0 ? 'text-[var(--signal)]' : ''
                      }`}>
                        {d.growthStr}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      }

      // Default table rendering with better styling
      return (
        <div className="my-6 overflow-x-auto">
          <table className="w-full" {...props}>{children}</table>
        </div>
      );
    },
  };

  return (
    <div className="flex gap-8">
      {/* Sticky TOC Sidebar */}
      <nav className="hidden lg:block w-64 shrink-0">
        <div className="sticky top-32 max-h-[calc(100vh-160px)] overflow-y-auto pr-4">
          <div className="text-label mb-4">CONTENTS</div>
          <div className="space-y-1">
            {groupedToc.map(({ main, subs }) => (
              <div key={main.id}>
                <button
                  onClick={() => scrollToSection(main.id)}
                  className={`w-full text-left py-1.5 text-sm transition-colors ${
                    activeSection === main.id
                      ? 'text-[var(--ink)] font-medium'
                      : 'text-[var(--ink-faded)] hover:text-[var(--ink)]'
                  }`}
                >
                  {main.text}
                </button>
                {subs.length > 0 && (
                  <div className="ml-3 border-l border-[var(--paper-darker)] pl-3 space-y-0.5">
                    {subs.slice(0, 5).map(sub => (
                      <button
                        key={sub.id}
                        onClick={() => scrollToSection(sub.id)}
                        className={`w-full text-left py-1 text-xs transition-colors truncate ${
                          activeSection === sub.id
                            ? 'text-[var(--ink)]'
                            : 'text-[var(--ink-ghost)] hover:text-[var(--ink-faded)]'
                        }`}
                      >
                        {sub.text}
                      </button>
                    ))}
                    {subs.length > 5 && (
                      <span className="text-xs text-[var(--ink-ghost)]">+{subs.length - 5} more</span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </nav>

      {/* Main content */}
      <div className="flex-1 min-w-0">
        {/* Thesis callout */}
        {thesis && (
          <div className="mb-8 p-6 bg-[var(--paper-dark)] border-l-4 border-[var(--signal)]">
            <div className="text-label mb-2">INVESTMENT THESIS</div>
            <p className="text-lg text-[var(--ink-light)] leading-relaxed">{thesis}</p>
          </div>
        )}

        {/* Mobile TOC dropdown */}
        <div className="lg:hidden mb-6">
          <details className="border border-[var(--paper-darker)]">
            <summary className="px-4 py-3 cursor-pointer text-sm font-mono uppercase tracking-wider">
              Jump to section
            </summary>
            <div className="px-4 pb-4 max-h-64 overflow-y-auto">
              {groupedToc.map(({ main }) => (
                <button
                  key={main.id}
                  onClick={() => {
                    scrollToSection(main.id);
                    (document.activeElement as HTMLElement)?.blur();
                  }}
                  className="block w-full text-left py-2 text-sm text-[var(--ink-faded)] hover:text-[var(--ink)]"
                >
                  {main.text}
                </button>
              ))}
            </div>
          </details>
        </div>

        {/* Report content */}
        <article className="prose">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {report}
          </ReactMarkdown>
        </article>
      </div>
    </div>
  );
}

function VerticalsView({ verticals }: { verticals: VerticalAnalysis[] }) {
  const [expandedThread, setExpandedThread] = useState<string | null>(null);
  const [expandedVertical, setExpandedVertical] = useState<string | null>(null);

  // Group verticals by thread_id
  const grouped = verticals.reduce((acc, v, i) => {
    const tid = v.thread_id || `orphan-${i}`;
    if (!acc[tid]) acc[tid] = [];
    acc[tid].push({ ...v, index: i });
    return acc;
  }, {} as Record<string, (VerticalAnalysis & { index: number })[]>);

  const threadIds = Object.keys(grouped);

  // Calculate average confidence per thread
  const threadStats = threadIds.map(tid => {
    const items = grouped[tid];
    const avgConf = items.reduce((sum, v) => sum + (v.overall_confidence || 0), 0) / items.length;
    return { tid, count: items.length, avgConfidence: avgConf };
  });

  return (
    <div>
      {/* Summary */}
      <div className="flex gap-6 mb-8 pb-6 border-b border-[var(--paper-darker)]">
        <div>
          <div className="text-2xl font-display font-bold">{verticals.length}</div>
          <div className="text-xs text-[var(--ink-faded)] uppercase tracking-wider">Vertical Analyses</div>
        </div>
        <div>
          <div className="text-2xl font-display font-bold">{threadIds.length}</div>
          <div className="text-xs text-[var(--ink-faded)] uppercase tracking-wider">Research Threads</div>
        </div>
        <div>
          <div className="text-2xl font-display font-bold">
            {Math.round(verticals.reduce((s, v) => s + (v.overall_confidence || 0), 0) / verticals.length * 100)}%
          </div>
          <div className="text-xs text-[var(--ink-faded)] uppercase tracking-wider">Avg Confidence</div>
        </div>
      </div>

      {/* Thread groups */}
      {threadIds.map((tid, tIdx) => {
        const items = grouped[tid];
        const isThreadExpanded = expandedThread === tid;
        const firstItem = items[0];

        return (
          <div key={tid} className="mb-4">
            {/* Thread header */}
            <button
              onClick={() => setExpandedThread(isThreadExpanded ? null : tid)}
              className={`w-full text-left p-4 border transition-colors ${
                isThreadExpanded
                  ? 'border-[var(--ink)] bg-[var(--paper-dark)]'
                  : 'border-[var(--paper-darker)] hover:border-[var(--ink-faded)]'
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-mono text-[var(--signal)]">
                      Thread {String(tIdx + 1).padStart(2, '0')}
                    </span>
                    <span className="text-xs text-[var(--ink-ghost)]">·</span>
                    <span className="text-xs text-[var(--ink-faded)]">{items.length} analyses</span>
                  </div>
                  <div className="text-sm font-medium">{firstItem.vertical_name?.split(':')[0] || `Thread ${tIdx + 1}`}</div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <div className="text-xs text-[var(--ink-ghost)]">Confidence</div>
                    <div className="text-sm font-mono font-medium">
                      {Math.round(items.reduce((s, v) => s + (v.overall_confidence || 0), 0) / items.length * 100)}%
                    </div>
                  </div>
                  <span className="text-[var(--ink-ghost)]">{isThreadExpanded ? '−' : '+'}</span>
                </div>
              </div>
            </button>

            {/* Expanded content */}
            {isThreadExpanded && (
              <div className="border-x border-b border-[var(--paper-darker)] bg-[var(--paper)]">
                {items.map((v, vIdx) => {
                  const vertKey = `${tid}-${vIdx}`;
                  const isVertExpanded = expandedVertical === vertKey;

                  return (
                    <div key={vIdx} className="border-b border-[var(--paper-darker)] last:border-b-0">
                      <button
                        onClick={() => setExpandedVertical(isVertExpanded ? null : vertKey)}
                        className={`w-full text-left px-4 py-3 flex items-center gap-3 ${
                          isVertExpanded ? 'bg-[var(--paper-dark)]' : 'hover:bg-[var(--paper-dark)]'
                        }`}
                      >
                        <span className="text-xs font-mono text-[var(--ink-ghost)]">{vIdx + 1}</span>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm truncate">{v.vertical_name}</div>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <div className="w-16 h-1.5 bg-[var(--paper-darker)]">
                            <div
                              className="h-full bg-[var(--ink)]"
                              style={{ width: `${(v.overall_confidence || 0) * 100}%` }}
                            />
                          </div>
                          <span className="text-xs font-mono w-8">{Math.round((v.overall_confidence || 0) * 100)}%</span>
                          <span className="text-[var(--ink-ghost)] text-sm">{isVertExpanded ? '−' : '+'}</span>
                        </div>
                      </button>

                      {isVertExpanded && v.business_understanding && (
                        <div className="px-4 pb-4 bg-[var(--paper-dark)]">
                          <div className="pl-6 pt-2 prose prose-sm max-w-none">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {v.business_understanding}
                            </ReactMarkdown>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function SynthesisCompare({ claude, gpt, winner }: {
  claude?: Synthesis;
  gpt?: Synthesis;
  winner?: string;
}) {
  const [selected, setSelected] = useState<'claude' | 'gpt'>(winner === 'gpt' ? 'gpt' : 'claude');

  if (!claude && !gpt) return null;

  const current = selected === 'claude' ? claude : gpt;

  return (
    <div className="space-y-4">
      {/* Selector */}
      <div className="flex gap-2">
        {claude && (
          <button
            onClick={() => setSelected('claude')}
            className={`flex-1 p-3 border transition-colors ${
              selected === 'claude'
                ? 'border-[var(--ink)] bg-[var(--ink)] text-[var(--paper)]'
                : 'border-[var(--paper-darker)] hover:border-[var(--ink-faded)]'
            }`}
          >
            <div className="text-xs font-mono uppercase tracking-wider mb-1">
              Claude {winner === 'claude' && '★'}
            </div>
            <div className="text-lg font-display font-bold">{claude.investment_view}</div>
            <div className="text-xs mt-1 opacity-70">{Math.round(claude.confidence * 100)}% confidence</div>
          </button>
        )}
        {gpt && (
          <button
            onClick={() => setSelected('gpt')}
            className={`flex-1 p-3 border transition-colors ${
              selected === 'gpt'
                ? 'border-[var(--ink)] bg-[var(--ink)] text-[var(--paper)]'
                : 'border-[var(--paper-darker)] hover:border-[var(--ink-faded)]'
            }`}
          >
            <div className="text-xs font-mono uppercase tracking-wider mb-1">
              GPT {winner === 'gpt' && '★'}
            </div>
            <div className="text-lg font-display font-bold">{gpt.investment_view}</div>
            <div className="text-xs mt-1 opacity-70">{Math.round(gpt.confidence * 100)}% confidence</div>
          </button>
        )}
      </div>

      {/* Thesis */}
      {current?.thesis_summary && (
        <div className="p-4 bg-[var(--paper-dark)]">
          <div className="text-label mb-2">THESIS</div>
          <p className="text-body">{current.thesis_summary}</p>
        </div>
      )}

      {/* Full Report */}
      {current?.full_report && (
        <div className="prose max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {current.full_report}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}

function CostBar({ label, value, total }: { label: string; value: number; total: number }) {
  const percentage = (value / total) * 100;

  return (
    <div className="flex items-center gap-4">
      <span className="w-28 text-xs font-mono text-[var(--ink-faded)] truncate">{label}</span>
      <div className="flex-1 h-3 bg-[var(--paper-dark)]">
        <div
          className="h-full bg-[var(--ink)] transition-all duration-700"
          style={{ width: `${Math.min(percentage, 100)}%` }}
        />
      </div>
      <span className="w-16 text-right text-xs font-mono">${value.toFixed(2)}</span>
    </div>
  );
}

function Collapsible({ title, children, defaultOpen = false }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="border border-[var(--paper-darker)] mb-4">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-4 py-3 flex items-center justify-between text-sm font-mono uppercase tracking-wider hover:bg-[var(--paper-dark)] transition-colors"
      >
        {title}
        <span className="text-[var(--ink-ghost)]">{isOpen ? '−' : '+'}</span>
      </button>
      {isOpen && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

// ===================== FINANCIALS VIEW =====================

function formatCurrency(value: number): string {
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(0)}M`;
  if (Math.abs(value) >= 1e3) return `$${(value / 1e3).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}

function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
}

function MetricBar({ label, value, maxValue, subtext, growth }: {
  label: string;
  value: number;
  maxValue: number;
  subtext?: string;
  growth?: number;
}) {
  const width = maxValue > 0 ? (value / maxValue) * 100 : 0;

  return (
    <div className="group">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-mono text-[var(--ink-faded)] uppercase tracking-wider">{label}</span>
        <div className="flex items-center gap-2">
          <span className="text-sm font-mono">{formatCurrency(value)}</span>
          {growth !== undefined && (
            <span className={`text-xs font-mono ${growth >= 0 ? 'text-[#2d5a27]' : 'text-[var(--signal)]'}`}>
              {formatPercent(growth)}
            </span>
          )}
        </div>
      </div>
      <div className="h-6 bg-[var(--paper-dark)] relative overflow-hidden">
        <div
          className="h-full bg-[var(--ink)] transition-all duration-700 ease-out"
          style={{ width: `${width}%` }}
        />
        {subtext && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-mono text-[var(--ink-ghost)] opacity-0 group-hover:opacity-100 transition-opacity">
            {subtext}
          </span>
        )}
      </div>
    </div>
  );
}

function QuarterlyChart({ data, metric, title }: {
  data: IncomeStatement[];
  metric: keyof IncomeStatement;
  title: string;
}) {
  if (!data || data.length === 0) return null;

  // Get last 8 quarters, reverse for chronological order
  const quarters = [...data].slice(0, 8).reverse();
  const values = quarters.map(q => Number(q[metric]) || 0);
  const maxValue = Math.max(...values.filter(v => v > 0));

  return (
    <div className="mb-8">
      <div className="text-label mb-4">{title}</div>
      <div className="flex items-end gap-1 h-32">
        {quarters.map((q, i) => {
          const value = Number(q[metric]) || 0;
          const height = maxValue > 0 ? (value / maxValue) * 100 : 0;
          const prevValue = i > 0 ? (Number(quarters[i-1][metric]) || 0) : value;
          const growth = prevValue > 0 ? (value - prevValue) / prevValue : 0;

          return (
            <div key={q.date} className="flex-1 flex flex-col items-center group">
              <div className="w-full flex flex-col items-center justify-end h-24">
                <div
                  className={`w-full transition-all duration-500 ${
                    growth >= 0 ? 'bg-[var(--ink)]' : 'bg-[var(--ink-faded)]'
                  } group-hover:bg-[var(--signal)]`}
                  style={{ height: `${height}%`, minHeight: value > 0 ? '4px' : '0' }}
                />
              </div>
              <div className="mt-2 text-center">
                <div className="text-[9px] font-mono text-[var(--ink-ghost)] uppercase">
                  {q.period || q.date?.slice(5, 7)}
                </div>
                <div className="text-[10px] font-mono text-[var(--ink-faded)] hidden group-hover:block">
                  {formatCurrency(value)}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AnnualTrend({ data, metrics }: {
  data: IncomeStatement[];
  metrics: { key: keyof IncomeStatement; label: string; color?: string }[];
}) {
  if (!data || data.length === 0) return null;

  // Get last 5 years, reverse for chronological order
  const years = [...data].slice(0, 5).reverse();

  // Calculate max across all metrics
  const allValues = metrics.flatMap(m => years.map(y => Number(y[m.key]) || 0));
  const maxValue = Math.max(...allValues.filter(v => v > 0));

  return (
    <div className="mb-8">
      <div className="text-label mb-4">ANNUAL PERFORMANCE</div>

      {/* Legend */}
      <div className="flex gap-4 mb-4">
        {metrics.map(m => (
          <div key={m.key as string} className="flex items-center gap-2">
            <div className={`w-3 h-3 ${m.color || 'bg-[var(--ink)]'}`} />
            <span className="text-xs font-mono text-[var(--ink-faded)]">{m.label}</span>
          </div>
        ))}
      </div>

      <div className="space-y-4">
        {years.map((year, yi) => (
          <div key={year.date} className="space-y-2">
            <div className="text-xs font-mono text-[var(--ink-ghost)]">
              {year.date?.slice(0, 4)}
            </div>
            {metrics.map((m, mi) => {
              const value = Number(year[m.key]) || 0;
              const prevValue = yi > 0 ? (Number(years[yi-1][m.key]) || 0) : value;
              const growth = prevValue > 0 ? (value - prevValue) / prevValue : 0;

              return (
                <div key={m.key as string} className="flex items-center gap-3">
                  <div className="w-16 text-[10px] font-mono text-[var(--ink-faded)]">{m.label}</div>
                  <div className="flex-1 h-4 bg-[var(--paper-dark)]">
                    <div
                      className={`h-full transition-all duration-700 ${m.color || 'bg-[var(--ink)]'}`}
                      style={{ width: `${(value / maxValue) * 100}%` }}
                    />
                  </div>
                  <div className="w-20 text-right text-xs font-mono">{formatCurrency(value)}</div>
                  {yi > 0 && (
                    <div className={`w-14 text-right text-[10px] font-mono ${growth >= 0 ? 'text-[#2d5a27]' : 'text-[var(--signal)]'}`}>
                      {formatPercent(growth)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function NewsTimeline({ news }: { news: NewsItem[] }) {
  if (!news || news.length === 0) return null;

  return (
    <div>
      <div className="text-label mb-4">RECENT NEWS</div>
      <div className="space-y-0">
        {news.slice(0, 10).map((item, i) => (
          <div
            key={i}
            className="py-3 border-b border-[var(--paper-darker)] last:border-b-0 group hover:bg-[var(--paper-dark)] px-3 -mx-3 transition-colors"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <h4 className="text-sm font-medium text-[var(--ink)] leading-snug mb-1 group-hover:text-[var(--signal)] transition-colors">
                  {item.title}
                </h4>
                {item.summary && (
                  <p className="text-xs text-[var(--ink-faded)] line-clamp-2">{item.summary}</p>
                )}
              </div>
              <div className="shrink-0 text-right">
                <div className="text-[10px] font-mono text-[var(--ink-ghost)]">
                  {new Date(item.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                </div>
                <div className="text-[9px] font-mono text-[var(--ink-ghost)] uppercase">{item.source}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FinancialsView({ ticker }: { ticker: string }) {
  const [data, setData] = useState<FinancialsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<'overview' | 'quarterly' | 'annual' | 'news'>('overview');

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        setError(null);
        const financials = await api.getFinancials(ticker);
        setData(financials);
      } catch (e: any) {
        setError(e.message || 'Failed to load financials');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [ticker]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-[var(--ink)] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-sm text-[var(--ink-faded)] font-mono">Loading financials...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-20">
        <p className="text-[var(--signal)] text-sm">{error}</p>
      </div>
    );
  }

  if (!data) return null;

  const profile = data.profile || {};
  const quarterly = data.income_statement?.quarterly || [];
  const annual = data.income_statement?.annual || [];
  const latestQ = quarterly[0];
  const latestA = annual[0];

  // Calculate key metrics
  const latestRevenue = latestQ?.revenue || latestA?.revenue || 0;
  const latestGrossProfit = latestQ?.grossProfit || latestA?.grossProfit || 0;
  const latestNetIncome = latestQ?.netIncome || latestA?.netIncome || 0;
  const grossMargin = latestRevenue > 0 ? latestGrossProfit / latestRevenue : 0;
  const netMargin = latestRevenue > 0 ? latestNetIncome / latestRevenue : 0;

  return (
    <div>
      {/* Company Header */}
      <div className="mb-8 pb-6 border-b border-[var(--paper-darker)]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-2xl font-display font-bold">{profile.companyName || ticker}</h2>
            <div className="text-sm text-[var(--ink-faded)] mt-1">
              {profile.sector && <span>{profile.sector}</span>}
              {profile.industry && <span> · {profile.industry}</span>}
            </div>
          </div>
          <div className="text-right">
            {profile.price && (
              <div className="text-2xl font-mono font-bold">${profile.price.toFixed(2)}</div>
            )}
            {profile.marketCap && (
              <div className="text-xs text-[var(--ink-faded)] font-mono">
                {formatCurrency(profile.marketCap)} market cap
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Sub-navigation */}
      <div className="flex gap-1 mb-8 border-b border-[var(--paper-darker)]">
        {(['overview', 'quarterly', 'annual', 'news'] as const).map(view => (
          <button
            key={view}
            onClick={() => setActiveView(view)}
            className={`px-4 py-2 text-xs font-mono uppercase tracking-wider border-b-2 transition-colors ${
              activeView === view
                ? 'border-[var(--ink)] text-[var(--ink)]'
                : 'border-transparent text-[var(--ink-faded)] hover:text-[var(--ink)]'
            }`}
          >
            {view}
          </button>
        ))}
      </div>

      {/* Overview */}
      {activeView === 'overview' && (
        <div className="animate-fade-in">
          {/* Key Metrics Grid */}
          <div className="grid grid-cols-4 gap-4 mb-8">
            <div className="p-4 border border-[var(--paper-darker)]">
              <div className="text-label mb-1">REVENUE (TTM)</div>
              <div className="text-xl font-mono font-bold">{formatCurrency(latestRevenue)}</div>
            </div>
            <div className="p-4 border border-[var(--paper-darker)]">
              <div className="text-label mb-1">NET INCOME</div>
              <div className="text-xl font-mono font-bold">{formatCurrency(latestNetIncome)}</div>
            </div>
            <div className="p-4 border border-[var(--paper-darker)]">
              <div className="text-label mb-1">GROSS MARGIN</div>
              <div className="text-xl font-mono font-bold">{(grossMargin * 100).toFixed(1)}%</div>
            </div>
            <div className="p-4 border border-[var(--paper-darker)]">
              <div className="text-label mb-1">NET MARGIN</div>
              <div className="text-xl font-mono font-bold">{(netMargin * 100).toFixed(1)}%</div>
            </div>
          </div>

          {/* Quarterly Revenue Chart */}
          {quarterly.length > 0 && (
            <QuarterlyChart data={quarterly} metric="revenue" title="QUARTERLY REVENUE" />
          )}

          {/* Profitability Bars */}
          {latestRevenue > 0 && (
            <div className="mb-8">
              <div className="text-label mb-4">PROFITABILITY WATERFALL</div>
              <div className="space-y-3">
                <MetricBar label="Revenue" value={latestRevenue} maxValue={latestRevenue} />
                <MetricBar
                  label="Gross Profit"
                  value={latestGrossProfit}
                  maxValue={latestRevenue}
                  subtext={`${(grossMargin * 100).toFixed(0)}% margin`}
                />
                <MetricBar
                  label="Op. Income"
                  value={latestQ?.operatingIncome || latestA?.operatingIncome || 0}
                  maxValue={latestRevenue}
                />
                <MetricBar
                  label="Net Income"
                  value={latestNetIncome}
                  maxValue={latestRevenue}
                  subtext={`${(netMargin * 100).toFixed(0)}% margin`}
                />
              </div>
            </div>
          )}

          {/* Quick News */}
          {data.news && data.news.length > 0 && (
            <div className="border-t border-[var(--paper-darker)] pt-6">
              <NewsTimeline news={data.news.slice(0, 3)} />
            </div>
          )}
        </div>
      )}

      {/* Quarterly Detail */}
      {activeView === 'quarterly' && quarterly.length > 0 && (
        <div className="animate-fade-in">
          <QuarterlyChart data={quarterly} metric="revenue" title="REVENUE BY QUARTER" />
          <QuarterlyChart data={quarterly} metric="netIncome" title="NET INCOME BY QUARTER" />

          <div className="text-label mb-4">QUARTERLY BREAKDOWN</div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b-2 border-[var(--ink)]">
                  <th className="text-left py-2 pr-4">Period</th>
                  <th className="text-right py-2 px-2">Revenue</th>
                  <th className="text-right py-2 px-2">Gross</th>
                  <th className="text-right py-2 px-2">Op Inc</th>
                  <th className="text-right py-2 px-2">Net Inc</th>
                  <th className="text-right py-2 pl-2">EPS</th>
                </tr>
              </thead>
              <tbody>
                {quarterly.slice(0, 8).map((q, i) => {
                  const prevQ = quarterly[i + 1];
                  const revGrowth = prevQ?.revenue ? (q.revenue - prevQ.revenue) / prevQ.revenue : 0;

                  return (
                    <tr key={q.date} className="border-b border-[var(--paper-darker)] hover:bg-[var(--paper-dark)]">
                      <td className="py-2 pr-4 text-[var(--ink-faded)]">
                        {q.date?.slice(0, 7)}
                      </td>
                      <td className="py-2 px-2 text-right">
                        {formatCurrency(q.revenue)}
                        {prevQ && (
                          <span className={`ml-2 ${revGrowth >= 0 ? 'text-[#2d5a27]' : 'text-[var(--signal)]'}`}>
                            {formatPercent(revGrowth)}
                          </span>
                        )}
                      </td>
                      <td className="py-2 px-2 text-right">{formatCurrency(q.grossProfit)}</td>
                      <td className="py-2 px-2 text-right">{formatCurrency(q.operatingIncome)}</td>
                      <td className={`py-2 px-2 text-right ${q.netIncome < 0 ? 'text-[var(--signal)]' : ''}`}>
                        {formatCurrency(q.netIncome)}
                      </td>
                      <td className="py-2 pl-2 text-right">${q.epsDiluted?.toFixed(2) || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Annual Detail */}
      {activeView === 'annual' && annual.length > 0 && (
        <div className="animate-fade-in">
          <AnnualTrend
            data={annual}
            metrics={[
              { key: 'revenue', label: 'Rev', color: 'bg-[var(--ink)]' },
              { key: 'grossProfit', label: 'Gross', color: 'bg-[var(--ink-light)]' },
              { key: 'netIncome', label: 'Net', color: 'bg-[var(--ink-faded)]' },
            ]}
          />

          <div className="text-label mb-4">ANNUAL STATEMENTS</div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b-2 border-[var(--ink)]">
                  <th className="text-left py-2 pr-4">Year</th>
                  <th className="text-right py-2 px-2">Revenue</th>
                  <th className="text-right py-2 px-2">YoY</th>
                  <th className="text-right py-2 px-2">Gross Profit</th>
                  <th className="text-right py-2 px-2">Net Income</th>
                  <th className="text-right py-2 pl-2">EPS</th>
                </tr>
              </thead>
              <tbody>
                {annual.slice(0, 5).map((a, i) => {
                  const prevA = annual[i + 1];
                  const revGrowth = prevA?.revenue ? (a.revenue - prevA.revenue) / prevA.revenue : 0;

                  return (
                    <tr key={a.date} className="border-b border-[var(--paper-darker)] hover:bg-[var(--paper-dark)]">
                      <td className="py-2 pr-4 font-medium">{a.date?.slice(0, 4)}</td>
                      <td className="py-2 px-2 text-right">{formatCurrency(a.revenue)}</td>
                      <td className={`py-2 px-2 text-right ${revGrowth >= 0 ? 'text-[#2d5a27]' : 'text-[var(--signal)]'}`}>
                        {prevA ? formatPercent(revGrowth) : '—'}
                      </td>
                      <td className="py-2 px-2 text-right">{formatCurrency(a.grossProfit)}</td>
                      <td className={`py-2 px-2 text-right ${a.netIncome < 0 ? 'text-[var(--signal)]' : ''}`}>
                        {formatCurrency(a.netIncome)}
                      </td>
                      <td className="py-2 pl-2 text-right">${a.epsDiluted?.toFixed(2) || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* News */}
      {activeView === 'news' && (
        <div className="animate-fade-in">
          {data.news && data.news.length > 0 ? (
            <NewsTimeline news={data.news} />
          ) : (
            <p className="text-[var(--ink-ghost)] text-center py-10">No recent news available</p>
          )}
        </div>
      )}
    </div>
  );
}

// ===================== MAIN COMPONENT =====================

export default function Home() {
  const [view, setView] = useState<View>('home');
  const [activeRuns, setActiveRuns] = useState<DisplayRun[]>([]);
  const [completedRuns, setCompletedRuns] = useState<DisplayRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<DisplayRun | null>(null);
  const [fullRunData, setFullRunData] = useState<FullRunData | null>(null);
  const [ticker, setTicker] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [currentStage, setCurrentStage] = useState(0);
  const [events, setEvents] = useState<any[]>([]);
  const [runningRunId, setRunningRunId] = useState<string | null>(null);
  const [runningTicker, setRunningTicker] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [reportTab, setReportTab] = useState<ReportTab>('report');

  const streamCleanupRef = useRef<(() => void) | null>(null);

  const stopStream = () => {
    streamCleanupRef.current?.();
    streamCleanupRef.current = null;
  };

  const loadRuns = async () => {
    try {
      const data = await api.listRuns();
      const active = (data.active || []).map(r => mapRun(r, true));
      const completed = (data.completed || []).map(r => mapRun(r, false));
      setActiveRuns(active);
      setCompletedRuns(completed);
    } catch (e) {
      console.error('Failed to load runs:', e);
    }
  };

  const connectStream = (runId: string) => {
    stopStream();
    streamCleanupRef.current = api.streamRun(
      runId,
      (event) => {
        setEvents(prev => [...prev, event]);
        if (event.type === 'stage_start' && event.data?.stage) {
          setCurrentStage(event.data.stage);
        }
        if (event.type === 'complete' || event.type === 'error') {
          setIsRunning(false);
          if (event.type === 'complete') setCurrentStage(5);
          loadRuns();
        }
      },
      () => setIsRunning(false)
    );
  };

  const goToRun = async (run: DisplayRun) => {
    if (run.isActive) {
      setRunningTicker(run.ticker);
      setRunningRunId(run.id);
      setEvents([]);
      setCurrentStage(run.currentStage || 0);
      setIsRunning(true);
      setView('running');

      try {
        const data = await api.getRun(run.id);
        setCurrentStage(data.current_stage || 0);
        connectStream(run.id);
      } catch (e) {
        console.error('Failed to get run:', e);
      }
    } else {
      setSelectedRun(run);
      setFullRunData(null);
      setReportTab('report');
      setView('report');

      try {
        const data = await api.getRun(run.id) as FullRunData;
        setFullRunData(data);
      } catch (e) {
        console.error('Failed to fetch report:', e);
      }
    }
  };

  const startAnalysis = async () => {
    if (!ticker.trim()) return;

    const t = ticker.toUpperCase();
    setError(null);
    setIsRunning(true);
    setView('running');
    setRunningTicker(t);
    setCurrentStage(0);
    setEvents([]);

    try {
      const result = await api.startRun({
        ticker: t,
        budget: 5.0,
        quarters: 4,
        use_dual_discovery: true,
        use_deep_research: true
      });

      setRunningRunId(result.run_id);
      connectStream(result.run_id);
      loadRuns();
    } catch (e: any) {
      console.error('Failed to start:', e);
      setError(e.message || 'Failed to start analysis');
      setIsRunning(false);
    }
  };

  const cancelRun = async (runId: string) => {
    try {
      await api.cancelRun(runId);
      setIsRunning(false);
      stopStream();
      loadRuns();
    } catch (e) {
      console.error('Failed to cancel:', e);
    }
  };

  const deleteRun = async (runId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this run?')) return;

    try {
      await api.deleteRun(runId);
      loadRuns();
    } catch (err: any) {
      alert(err.message || 'Failed to delete');
    }
  };

  useEffect(() => {
    loadRuns();
    return () => stopStream();
  }, []);

  const stages = [
    { num: 1, name: 'Discovery' },
    { num: 2, name: 'Vertical Analysis' },
    { num: 3, name: 'Synthesis' },
    { num: 4, name: 'Judgment' },
    { num: 5, name: 'Report' }
  ];

  const allRuns = [...activeRuns, ...completedRuns].sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );

  // ==================== HOME ====================
  if (view === 'home') {
    return (
      <div className="min-h-screen flex flex-col bg-[var(--paper)]">
        <header className="px-6 py-4 flex items-center justify-between border-b border-[var(--paper-darker)]">
          <span className="font-mono text-sm uppercase tracking-wider text-[var(--ink-faded)]">K+ Research</span>
          <nav className="flex items-center gap-4">
            {activeRuns.length > 0 && (
              <button
                onClick={() => goToRun(activeRuns[0])}
                className="flex items-center gap-2 px-3 py-1.5 bg-[var(--signal-light)] border border-[var(--signal)] text-[var(--signal)] text-xs font-mono uppercase"
              >
                <span className="w-2 h-2 bg-[var(--signal)] rounded-full animate-pulse" />
                {activeRuns.length} Active
              </button>
            )}
            <button
              onClick={() => { loadRuns(); setView('archive'); }}
              className="text-sm font-mono uppercase tracking-wider text-[var(--ink-faded)] hover:text-[var(--ink)]"
            >
              Archive ({allRuns.length})
            </button>
          </nav>
        </header>

        <main className="flex-1 flex flex-col items-center justify-center px-8">
          <h1 className="text-massive">
            K<span className="text-signal">+</span>
          </h1>

          <div className="mt-12">
            <div className="flex items-center gap-4">
              <input
                type="text"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase().slice(0, 5))}
                onKeyDown={(e) => e.key === 'Enter' && startAnalysis()}
                placeholder="AAPL"
                className="ticker-input"
                maxLength={5}
                autoFocus
              />
              <button
                onClick={startAnalysis}
                disabled={!ticker.trim()}
                className="btn"
              >
                Analyze
              </button>
            </div>
            {error && (
              <p className="mt-4 text-sm text-[var(--signal)]">{error}</p>
            )}
          </div>
        </main>
      </div>
    );
  }

  // ==================== ARCHIVE ====================
  if (view === 'archive') {
    return (
      <div className="min-h-screen flex flex-col bg-[var(--paper)]">
        <header className="px-6 py-4 flex items-center justify-between border-b border-[var(--paper-darker)]">
          <button
            onClick={() => setView('home')}
            className="font-mono text-sm uppercase tracking-wider text-[var(--ink-faded)] hover:text-[var(--ink)]"
          >
            &larr; Home
          </button>
          <span className="font-mono text-sm text-[var(--ink-faded)]">
            {activeRuns.length} active · {completedRuns.length} completed
          </span>
        </header>

        <main className="flex-1 px-6 py-6 overflow-auto">
          {allRuns.length === 0 ? (
            <p className="text-center text-[var(--ink-ghost)] py-20">No runs yet.</p>
          ) : (
            <div className="max-w-2xl mx-auto space-y-1">
              {allRuns.map((run) => (
                <div
                  key={run.id}
                  className="flex items-center gap-4 hover:bg-[var(--paper-dark)] transition-colors border-b border-[var(--paper-darker)]"
                >
                  <button
                    onClick={() => goToRun(run)}
                    className="flex-1 text-left px-4 py-3 flex items-center gap-4"
                  >
                    <span className="font-mono font-medium w-16">{run.ticker}</span>
                    <span className="text-xs text-[var(--ink-ghost)] w-24">
                      {new Date(run.createdAt).toLocaleDateString()}
                    </span>
                    {run.isActive ? (
                      <span className="ml-auto flex items-center gap-2 text-xs font-mono text-[var(--signal)]">
                        <span className="w-2 h-2 bg-[var(--signal)] rounded-full animate-pulse" />
                        Stage {run.currentStage || '?'}/5
                      </span>
                    ) : run.verdict ? (
                      <span className="ml-auto text-xs font-mono font-medium">
                        {run.verdict.investmentView}
                      </span>
                    ) : (
                      <span className="ml-auto text-xs text-[var(--ink-ghost)]">—</span>
                    )}
                  </button>
                  {!run.isActive && (
                    <button
                      onClick={(e) => deleteRun(run.id, e)}
                      className="px-3 py-3 text-xs text-[var(--ink-ghost)] hover:text-[var(--signal)]"
                    >
                      ×
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </main>
      </div>
    );
  }

  // ==================== RUNNING ====================
  if (view === 'running') {
    const progress = (currentStage / 5) * 100;

    return (
      <div className="min-h-screen flex flex-col bg-[var(--paper)]">
        <header className="px-6 py-4 flex items-center justify-between border-b border-[var(--paper-darker)]">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setView('home')}
              className="font-mono text-sm uppercase tracking-wider text-[var(--ink-faded)] hover:text-[var(--ink)]"
            >
              &larr; Home
            </button>
            <span className="text-[var(--ink-ghost)]">·</span>
            <span className="font-mono font-bold">{runningTicker}</span>
          </div>
          <div className="flex items-center gap-4">
            {isRunning ? (
              <>
                <span className="flex items-center gap-2 text-xs font-mono text-[var(--signal)]">
                  <span className="w-2 h-2 bg-[var(--signal)] rounded-full animate-pulse" />
                  Processing
                </span>
                {runningRunId && (
                  <button
                    onClick={() => cancelRun(runningRunId)}
                    className="text-xs font-mono uppercase text-[var(--ink-faded)] hover:text-[var(--signal)]"
                  >
                    Cancel
                  </button>
                )}
              </>
            ) : (
              <span className="text-xs font-mono text-[var(--ink-faded)]">Complete</span>
            )}
          </div>
        </header>

        <main className="flex-1 px-6 py-6 overflow-auto">
          <div className="max-w-4xl mx-auto grid grid-cols-2 gap-8">
            <div>
              <h1 className="text-xl font-display font-bold mb-4">
                {isRunning ? 'Processing...' : 'Analysis Complete'}
              </h1>
              <div className="h-1 bg-[var(--paper-darker)] mb-6">
                <div
                  className="h-full bg-[var(--signal)] transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <div className="space-y-1">
                {stages.map((stage, i) => {
                  const isComplete = i < currentStage;
                  const isCurrent = i === currentStage - 1 && isRunning;

                  return (
                    <div
                      key={stage.num}
                      className={`flex items-center gap-3 py-2 text-sm ${
                        isCurrent ? 'text-[var(--signal)]' :
                        isComplete ? 'text-[var(--ink)]' :
                        'text-[var(--ink-ghost)]'
                      }`}
                    >
                      <span className="font-mono w-6">{String(stage.num).padStart(2, '0')}</span>
                      <span className="uppercase tracking-wider text-xs">{stage.name}</span>
                      <span className="ml-auto">
                        {isComplete && '✓'}
                        {isCurrent && <span className="animate-pulse">•</span>}
                      </span>
                    </div>
                  );
                })}
              </div>
              {!isRunning && (
                <div className="mt-6 flex gap-3">
                  {runningRunId && (
                    <button
                      onClick={() => goToRun({
                        id: runningRunId,
                        ticker: runningTicker,
                        status: 'complete',
                        createdAt: new Date().toISOString(),
                        isActive: false
                      })}
                      className="btn btn-signal"
                    >
                      View Report
                    </button>
                  )}
                  <button onClick={() => setView('home')} className="btn">
                    New Analysis
                  </button>
                </div>
              )}
            </div>
            <div className="bg-[var(--paper-dark)] p-4 h-[400px] overflow-auto">
              <div className="text-xs font-mono text-[var(--ink-ghost)] mb-3">
                {events.length} events
              </div>
              {events.length === 0 ? (
                <p className="text-[var(--ink-ghost)] text-sm">Waiting for events...</p>
              ) : (
                <div className="space-y-1 text-xs font-mono">
                  {events.slice(-50).map((event, i) => (
                    <div key={i} className="text-[var(--ink-light)]">
                      {event.type === 'stage_start' && <span className="text-[var(--ink)]">→ {event.data?.stage_name}</span>}
                      {event.type === 'stage_complete' && <span className="text-[var(--signal)]">✓ {event.data?.stage_name}</span>}
                      {event.type === 'agent_event' && <span>{event.data?.message || '...'}</span>}
                      {event.type === 'complete' && <span className="text-[var(--ink)] font-bold">• Complete</span>}
                      {event.type === 'error' && <span className="text-[var(--signal)]">× {event.data?.detail}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </main>
      </div>
    );
  }

  // ==================== REPORT ====================
  if (view === 'report' && selectedRun) {
    const sr = fullRunData?.structured_report;
    const ef = fullRunData?.editorial_feedback;
    const costs = fullRunData?.costs;
    const discovery = fullRunData?.discovery;
    const verticals = fullRunData?.verticals;

    return (
      <div className="min-h-screen bg-[var(--paper)]">
        {/* Header */}
        <header className="px-6 py-4 flex items-center justify-between border-b border-[var(--paper-darker)] sticky top-0 bg-paper-glass z-50">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setView('home')}
              className="font-mono text-sm uppercase tracking-wider text-[var(--ink-faded)] hover:text-[var(--ink)]"
            >
              &larr;
            </button>
            <span className="font-mono font-bold text-xl">{selectedRun.ticker}</span>
            {sr?.conviction && (
              <span className={`px-2 py-1 text-xs font-mono uppercase ${
                sr.conviction.toLowerCase().includes('high')
                  ? 'bg-[var(--ink)] text-[var(--paper)]'
                  : 'border border-[var(--paper-darker)]'
              }`}>
                {sr.conviction}
              </span>
            )}
          </div>
          <div className="flex items-center gap-4 text-xs text-[var(--ink-ghost)]">
            <span>{new Date(selectedRun.createdAt).toLocaleDateString()}</span>
            {costs && <span className="font-mono">${costs.total_cost_usd.toFixed(2)}</span>}
          </div>
        </header>

        {/* Tabs */}
        <div className="px-6 border-b border-[var(--paper-darker)] flex gap-1 sticky top-[57px] bg-[var(--paper)] z-40">
          <TabButton active={reportTab === 'report'} onClick={() => setReportTab('report')}>
            Report
          </TabButton>
          <TabButton
            active={reportTab === 'discovery'}
            onClick={() => setReportTab('discovery')}
            count={discovery?.research_threads?.length}
          >
            Discovery
          </TabButton>
          <TabButton
            active={reportTab === 'verticals'}
            onClick={() => setReportTab('verticals')}
            count={verticals?.length}
          >
            Verticals
          </TabButton>
          <TabButton active={reportTab === 'synthesis'} onClick={() => setReportTab('synthesis')}>
            Synthesis
          </TabButton>
          <TabButton active={reportTab === 'financials'} onClick={() => setReportTab('financials')}>
            Financials
          </TabButton>
          <TabButton active={reportTab === 'costs'} onClick={() => setReportTab('costs')}>
            Costs
          </TabButton>
        </div>

        {/* Content */}
        <main className="px-6 py-8">
          <div className={reportTab === 'report' ? 'max-w-6xl mx-auto' : 'max-w-4xl mx-auto'}>

            {/* REPORT TAB */}
            {reportTab === 'report' && (
              <div className="animate-fade-in">
                {sr && (
                  <VerdictHero
                    verdict={sr.investment_view}
                    confidence={sr.confidence}
                    conviction={sr.conviction}
                  />
                )}

                {/* Scenarios Chart */}
                {sr?.scenarios && (
                  <div className="mb-8 p-6 border border-[var(--paper-darker)]">
                    <div className="text-label mb-4">SCENARIO ANALYSIS</div>
                    <div className="flex gap-4 mb-6">
                      {/* Visual probability bar */}
                      <div className="flex-1 h-8 flex overflow-hidden border border-[var(--paper-darker)]">
                        <div
                          className="bg-[#2d5a27] flex items-center justify-center text-xs text-white font-mono"
                          style={{ width: `${sr.scenarios.bull.probability * 100}%` }}
                        >
                          {Math.round(sr.scenarios.bull.probability * 100)}%
                        </div>
                        <div
                          className="bg-[var(--ink-faded)] flex items-center justify-center text-xs text-white font-mono"
                          style={{ width: `${sr.scenarios.base.probability * 100}%` }}
                        >
                          {Math.round(sr.scenarios.base.probability * 100)}%
                        </div>
                        <div
                          className="bg-[var(--signal)] flex items-center justify-center text-xs text-white font-mono"
                          style={{ width: `${sr.scenarios.bear.probability * 100}%` }}
                        >
                          {Math.round(sr.scenarios.bear.probability * 100)}%
                        </div>
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-4">
                      <div className="p-4 bg-[#2d5a27]/10 border-l-4 border-[#2d5a27]">
                        <div className="text-xs font-mono text-[#2d5a27] mb-1">BULL</div>
                        <p className="text-sm text-[var(--ink-light)]">{sr.scenarios.bull.headline}</p>
                      </div>
                      <div className="p-4 bg-[var(--paper-dark)] border-l-4 border-[var(--ink-faded)]">
                        <div className="text-xs font-mono text-[var(--ink-faded)] mb-1">BASE</div>
                        <p className="text-sm text-[var(--ink-light)]">{sr.scenarios.base.headline}</p>
                      </div>
                      <div className="p-4 bg-[var(--signal)]/10 border-l-4 border-[var(--signal)]">
                        <div className="text-xs font-mono text-[var(--signal)] mb-1">BEAR</div>
                        <p className="text-sm text-[var(--ink-light)]">{sr.scenarios.bear.headline}</p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Key Risks & Debates */}
                {(sr?.top_risks || sr?.key_debates) && (
                  <div className="mb-8 grid grid-cols-2 gap-4">
                    {sr?.top_risks && sr.top_risks.length > 0 && (
                      <div className="p-4 border border-[var(--paper-darker)]">
                        <div className="text-label mb-3">TOP RISKS</div>
                        <div className="space-y-2">
                          {sr.top_risks.slice(0, 4).map((risk, i) => (
                            <div key={i} className="flex gap-2 text-sm">
                              <span className="text-[var(--signal)] shrink-0">!</span>
                              <span className="text-[var(--ink-light)]">{risk}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {sr?.key_debates && sr.key_debates.length > 0 && (
                      <div className="p-4 border border-[var(--paper-darker)]">
                        <div className="text-label mb-3">KEY DEBATES</div>
                        <div className="space-y-2">
                          {sr.key_debates.slice(0, 4).map((debate, i) => (
                            <div key={i} className="flex gap-2 text-sm">
                              <span className="text-[var(--ink-ghost)] shrink-0">?</span>
                              <span className="text-[var(--ink-light)]">{debate}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {fullRunData?.report ? (
                  <ReportViewer
                    report={fullRunData.report}
                    thesis={sr?.thesis_summary}
                  />
                ) : (
                  <p className="text-[var(--ink-ghost)]">Loading report...</p>
                )}
              </div>
            )}

            {/* DISCOVERY TAB */}
            {reportTab === 'discovery' && (
              <div className="animate-fade-in">
                {discovery ? (
                  <DiscoveryView discovery={discovery} />
                ) : (
                  <p className="text-[var(--ink-ghost)]">No discovery data available</p>
                )}
              </div>
            )}

            {/* VERTICALS TAB */}
            {reportTab === 'verticals' && (
              <div className="animate-fade-in">
                {verticals && verticals.length > 0 ? (
                  <VerticalsView verticals={verticals} />
                ) : (
                  <p className="text-[var(--ink-ghost)]">No vertical analysis available</p>
                )}
              </div>
            )}

            {/* SYNTHESIS TAB */}
            {reportTab === 'synthesis' && (
              <div className="animate-fade-in">
                <div className="mb-6">
                  <h2 className="text-title mb-2">Model Synthesis</h2>
                  <p className="text-sm text-[var(--ink-faded)]">
                    Compare the competing analysis from Claude and GPT
                  </p>
                </div>

                {ef && (
                  <div className="mb-6 p-4 border border-[var(--paper-darker)]">
                    <div className="text-label mb-2">JUDGE DECISION</div>
                    <p className="text-sm text-[var(--ink-light)] mb-3">{ef.preference_reasoning}</p>
                    <div className="flex gap-4 text-xs font-mono">
                      <span>Claude: {Math.round((ef.claude_score || 0) * 100)}</span>
                      <span>GPT: {Math.round((ef.gpt_score || 0) * 100)}</span>
                      <span className="text-[var(--signal)]">Winner: {ef.preferred_synthesis}</span>
                    </div>
                  </div>
                )}

                <SynthesisCompare
                  claude={fullRunData?.claude_synthesis}
                  gpt={fullRunData?.gpt_synthesis}
                  winner={ef?.preferred_synthesis}
                />

                {!fullRunData?.claude_synthesis && !fullRunData?.gpt_synthesis && (
                  <p className="text-[var(--ink-ghost)]">No synthesis data available</p>
                )}
              </div>
            )}

            {/* FINANCIALS TAB */}
            {reportTab === 'financials' && (
              <div className="animate-fade-in">
                <FinancialsView ticker={selectedRun.ticker} />
              </div>
            )}

            {/* COSTS TAB */}
            {reportTab === 'costs' && costs && (
              <div className="animate-fade-in">
                <div className="mb-6">
                  <h2 className="text-title mb-2">Cost Breakdown</h2>
                  <p className="text-sm text-[var(--ink-faded)]">
                    Token usage and API costs for this analysis
                  </p>
                </div>

                <div className="grid grid-cols-4 gap-4 mb-8">
                  <div className="p-4 border border-[var(--paper-darker)]">
                    <div className="text-label mb-1">TOTAL</div>
                    <div className="text-2xl font-mono">${costs.total_cost_usd.toFixed(2)}</div>
                  </div>
                  <div className="p-4 border border-[var(--paper-darker)]">
                    <div className="text-label mb-1">BUDGET</div>
                    <div className="text-2xl font-mono">${costs.budget_limit}</div>
                  </div>
                  <div className="p-4 border border-[var(--paper-darker)]">
                    <div className="text-label mb-1">INPUT</div>
                    <div className="text-2xl font-mono">{Math.round(costs.total_input_tokens / 1000)}k</div>
                  </div>
                  <div className="p-4 border border-[var(--paper-darker)]">
                    <div className="text-label mb-1">OUTPUT</div>
                    <div className="text-2xl font-mono">{Math.round(costs.total_output_tokens / 1000)}k</div>
                  </div>
                </div>

                <Collapsible title="By Provider" defaultOpen>
                  <div className="space-y-2">
                    {Object.entries(costs.by_provider || {}).sort((a, b) => b[1] - a[1]).map(([provider, cost]) => (
                      <CostBar key={provider} label={provider} value={cost} total={costs.total_cost_usd} />
                    ))}
                  </div>
                </Collapsible>

                <Collapsible title="By Agent">
                  <div className="space-y-2">
                    {Object.entries(costs.by_agent || {}).sort((a, b) => b[1] - a[1]).map(([agent, cost]) => (
                      <CostBar key={agent} label={agent} value={cost} total={costs.total_cost_usd} />
                    ))}
                  </div>
                </Collapsible>

                <Collapsible title="By Model">
                  <div className="space-y-2">
                    {Object.entries(costs.by_model || {}).sort((a, b) => b[1] - a[1]).map(([model, cost]) => (
                      <CostBar key={model} label={model.split('-').slice(0, 2).join('-')} value={cost} total={costs.total_cost_usd} />
                    ))}
                  </div>
                </Collapsible>

                <Collapsible title="Call Log">
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono">
                      <thead>
                        <tr className="border-b border-[var(--paper-darker)]">
                          <th className="text-left p-2">Phase</th>
                          <th className="text-left p-2">Model</th>
                          <th className="text-right p-2">In</th>
                          <th className="text-right p-2">Out</th>
                          <th className="text-right p-2">Cost</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(costs.records || []).map((r, i) => (
                          <tr key={i} className="border-b border-[var(--paper-darker)]">
                            <td className="p-2 text-[var(--ink-faded)]">{r.phase}</td>
                            <td className="p-2">{r.model.split('-').slice(0, 2).join('-')}</td>
                            <td className="p-2 text-right text-[var(--ink-faded)]">{Math.round(r.input_tokens / 1000)}k</td>
                            <td className="p-2 text-right text-[var(--ink-faded)]">{Math.round(r.output_tokens / 1000)}k</td>
                            <td className="p-2 text-right">${r.cost_usd.toFixed(2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Collapsible>
              </div>
            )}

            {reportTab === 'costs' && !costs && (
              <p className="text-[var(--ink-ghost)]">No cost data available</p>
            )}
          </div>
        </main>
      </div>
    );
  }

  return null;
}
