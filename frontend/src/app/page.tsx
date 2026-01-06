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
  // Check if verdict has actual data (not just empty object)
  const hasVerdict = run.verdict && run.verdict.investment_view;
  const hasManifestVerdict = run.manifest?.final_verdict?.investment_view;

  return {
    id: run.run_id,
    ticker: run.ticker,
    status: run.status || 'unknown',
    createdAt: run.started_at || new Date().toISOString(),
    totalCost: run.total_cost || run.manifest?.total_cost_usd,
    currentStage: run.current_stage,
    isActive,
    verdict: hasVerdict ? {
      investmentView: run.verdict.investment_view,
      conviction: run.verdict.conviction,
      confidence: run.verdict.confidence
    } : hasManifestVerdict ? {
      investmentView: run.manifest!.final_verdict!.investment_view,
      conviction: run.manifest!.final_verdict!.conviction,
      confidence: run.manifest!.final_verdict!.confidence
    } : undefined
  };
}

// ===================== COMPONENTS =====================

function VerdictHero({ verdict, confidence, conviction }: { verdict: string; confidence: number; conviction?: string }) {
  const v = verdict.toUpperCase();
  const isBuy = v === 'BUY';
  const isSell = v === 'SELL';
  const isHold = v === 'HOLD';

  const colorClass = isBuy ? 'positive' : isSell ? 'negative' : 'warning';
  const textColorClass = isBuy ? 'text-[var(--positive)]' : isSell ? 'text-[var(--negative)]' : 'text-[var(--warning)]';

  return (
    <div className="mb-10 pb-8 border-b border-[var(--border-subtle)]">
      <div className="flex items-end gap-8 flex-wrap">
        <div
          className={`text-[5rem] md:text-[7rem] font-display font-extrabold tracking-tight leading-none ${textColorClass}`}
          style={{
            textShadow: isBuy
              ? '0 0 60px var(--positive-glow)'
              : isSell
              ? '0 0 60px var(--negative-glow)'
              : '0 0 60px var(--warning-muted)'
          }}
        >
          {v}
        </div>
        <div className="pb-3 space-y-4">
          {conviction && (
            <div className={`inline-block px-3 py-1.5 text-xs font-mono uppercase tracking-wider rounded ${
              conviction.toLowerCase().includes('high')
                ? 'bg-[var(--text-primary)] text-[var(--bg-void)]'
                : 'border border-[var(--border-default)] text-[var(--text-secondary)]'
            }`}>
              {conviction}
            </div>
          )}
          <div>
            <div className="text-label mb-2">CONFIDENCE</div>
            <div className="flex items-center gap-4">
              <div className="w-48 h-2 bg-[var(--bg-hover)] rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full confidence-bar-fill ${colorClass}`}
                  style={{ width: `${confidence * 100}%` }}
                />
              </div>
              <span className="text-data font-semibold">{Math.round(confidence * 100)}%</span>
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
      className={`tab ${active ? 'active' : ''}`}
    >
      {children}
      {count !== undefined && count > 0 && (
        <span className="tab-count">{count}</span>
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
      <div className="flex items-baseline gap-3 mb-4 pb-3 border-b border-[var(--border-subtle)]">
        <h3 className="text-sm font-mono uppercase tracking-wider text-[var(--text-primary)]">{info.label}</h3>
        <span className="text-xs text-[var(--text-ghost)]">{threads.length} threads</span>
      </div>

      <div className="space-y-1">
        {threads.map((thread, i) => (
          <div key={thread.thread_id || i} className="rounded-lg overflow-hidden">
            <button
              onClick={() => setExpanded(expanded === thread.thread_id ? null : thread.thread_id)}
              className={`w-full text-left px-4 py-3 flex items-start gap-3 transition-all ${
                expanded === thread.thread_id
                  ? 'bg-[var(--bg-elevated)]'
                  : 'hover:bg-[var(--bg-elevated)]'
              }`}
            >
              <span className="text-xs font-mono text-[var(--accent)] mt-0.5 shrink-0">
                {String(i + 1).padStart(2, '0')}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-[var(--text-primary)] truncate">{thread.name}</div>
                <div className="text-xs text-[var(--text-muted)] mt-1">
                  {thread.research_questions?.length || 0} questions · Priority {thread.priority}
                </div>
              </div>
              <span className="text-[var(--text-ghost)] text-sm shrink-0">
                {expanded === thread.thread_id ? '−' : '+'}
              </span>
            </button>

            {expanded === thread.thread_id && (
              <div className="px-4 pb-4 bg-[var(--bg-elevated)] border-t border-[var(--border-subtle)]">
                <div className="pt-4 pl-8 space-y-4">
                  {thread.value_driver_hypothesis && (
                    <div>
                      <div className="text-label mb-2">HYPOTHESIS</div>
                      <p className="text-sm text-[var(--text-secondary)]">{thread.value_driver_hypothesis}</p>
                    </div>
                  )}

                  {thread.research_questions && thread.research_questions.length > 0 && (
                    <div>
                      <div className="text-label mb-2">QUESTIONS ASKED</div>
                      <div className="space-y-2">
                        {thread.research_questions.map((q: string, qi: number) => (
                          <div key={qi} className="flex gap-2 text-sm">
                            <span className="text-[var(--accent)] shrink-0">→</span>
                            <span className="text-[var(--text-secondary)]">{q}</span>
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
      <div className="grid grid-cols-3 gap-4 mb-8">
        <div className="data-card">
          <div className="data-card-label">Research Threads</div>
          <div className="data-card-value">{discovery.research_threads?.length || 0}</div>
        </div>
        <div className="data-card">
          <div className="data-card-label">Questions Asked</div>
          <div className="data-card-value">{totalQuestions}</div>
        </div>
        {discovery.official_segments && (
          <div className="data-card">
            <div className="data-card-label">Official Segments</div>
            <div className="data-card-value">{discovery.official_segments.length}</div>
          </div>
        )}
      </div>

      {/* Official segments pills */}
      {discovery.official_segments && discovery.official_segments.length > 0 && (
        <div className="mb-8">
          <div className="text-label mb-3">OFFICIAL SEGMENTS</div>
          <div className="flex flex-wrap gap-2">
            {discovery.official_segments.map((seg, i) => (
              <span key={i} className="px-3 py-1.5 text-xs font-mono bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded text-[var(--text-secondary)]">
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

  lines.forEach((line) => {
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
  const contentRef = useRef<HTMLDivElement>(null);
  const toc = parseTableOfContents(report);

  // Filter out the metadata table at the beginning (EQUITY RESEARCH REPORT table)
  const cleanedReport = report.replace(/^#[^\n]*\n+\|[^|]*\|[^|]*\|\n\|[-:| ]+\|\n(\|[^\n]+\|\n)+/m, '');

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
      const offset = 120;
      const top = element.getBoundingClientRect().top + window.scrollY - offset;
      window.scrollTo({ top, behavior: 'smooth' });
      setActiveSection(id);
    }
  };

  // Track scroll position to highlight active section
  useEffect(() => {
    const handleScroll = () => {
      const sections = toc.filter(t => t.level === 2).map(t => document.getElementById(t.id));
      let current = '';

      for (const section of sections) {
        if (section) {
          const rect = section.getBoundingClientRect();
          if (rect.top <= 150) {
            current = section.id;
          }
        }
      }

      if (current && current !== activeSection) {
        setActiveSection(current);
      }
    };

    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, [activeSection, toc]);

  // Custom renderer for better styling
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
    // Better table rendering with visual pop
    table: ({ children, ...props }: any) => (
      <div className="my-8 rounded-xl overflow-hidden shadow-[0_4px_24px_rgba(0,0,0,0.2),0_0_0_1px_var(--border-subtle)] hover:shadow-[0_8px_32px_rgba(0,0,0,0.3),0_0_0_1px_var(--border-default)] transition-shadow duration-300">
        <table className="w-full" {...props}>{children}</table>
      </div>
    ),
    thead: ({ children, ...props }: any) => (
      <thead className="bg-gradient-to-b from-[var(--bg-elevated)] to-[var(--bg-active)]" {...props}>{children}</thead>
    ),
    tbody: ({ children, ...props }: any) => (
      <tbody className="bg-[var(--bg-surface)] [&>tr:nth-child(even)]:bg-[var(--bg-elevated)] [&>tr:hover]:bg-[var(--accent-muted)] [&>tr]:transition-colors" {...props}>{children}</tbody>
    ),
    th: ({ children, ...props }: any) => (
      <th className="px-5 py-4 text-left text-[10px] font-mono font-semibold uppercase tracking-widest text-[var(--accent-bright)] border-b-2 border-[var(--accent)] whitespace-nowrap" {...props}>
        {children}
      </th>
    ),
    td: ({ children, ...props }: any) => {
      const text = String(children);
      // Enhanced color-coding for financial data
      const isStrongPositive = text.includes('BUY') || text.includes('Outperform') || text.includes('Strong');
      const isPositive = text.includes('+') || text.includes('high') || text.includes('bullish') || text.toLowerCase().includes('growth');
      const isNegative = text.includes('SELL') || text.includes('bear') || text.includes('risk') || text.includes('decline') || (text.includes('-') && /[\d]/.test(text));
      const isNumber = /^\$?-?[\d,]+\.?\d*[BMK%]?$/.test(text.trim());
      const isCurrency = text.startsWith('$') || text.includes('USD');
      const isPercent = text.includes('%');

      let colorClass = 'text-[var(--text-secondary)]';
      if (isStrongPositive) colorClass = 'text-[var(--positive)] font-bold bg-[var(--positive-muted)] px-2 py-0.5 rounded inline-block';
      else if (isPositive && !isNegative) colorClass = 'text-[var(--positive)] font-medium';
      else if (isNegative) colorClass = 'text-[var(--negative)] font-medium';
      else if (isCurrency || isNumber) colorClass = 'font-mono text-[var(--text-primary)] tabular-nums';
      else if (isPercent) colorClass = 'font-mono font-medium text-[var(--text-primary)]';

      return (
        <td className={`px-5 py-3.5 text-sm ${colorClass}`} {...props}>
          {children}
        </td>
      );
    },
    // Better list styling
    ul: ({ children, ...props }: any) => (
      <ul className="my-4 space-y-3 list-disc list-outside pl-6" {...props}>{children}</ul>
    ),
    li: ({ children, ...props }: any) => (
      <li className="text-[var(--text-secondary)] marker:text-[var(--accent)]" {...props}>
        {children}
      </li>
    ),
    // Better blockquotes
    blockquote: ({ children, ...props }: any) => (
      <blockquote className="my-6 pl-4 border-l-2 border-[var(--accent)] bg-[var(--accent-muted)] py-3 pr-4 rounded-r-lg" {...props}>
        {children}
      </blockquote>
    ),
    // Better strong/bold
    strong: ({ children, ...props }: any) => (
      <strong className="font-semibold text-[var(--text-primary)]" {...props}>{children}</strong>
    ),
  };

  return (
    <div className="flex gap-10 relative">
      {/* Sticky TOC Sidebar - Now properly sticky */}
      <nav className="hidden lg:block w-56 shrink-0">
        <div className="sticky top-28 max-h-[calc(100vh-140px)] overflow-y-auto scrollbar-thin pr-2">
          <div className="text-[10px] font-mono uppercase tracking-widest text-[var(--text-ghost)] mb-4">Contents</div>
          <div className="space-y-0.5">
            {groupedToc.map(({ main, subs }) => (
              <div key={main.id}>
                <button
                  onClick={() => scrollToSection(main.id)}
                  className={`w-full text-left py-1.5 text-xs transition-all rounded px-2 -mx-2 ${
                    activeSection === main.id
                      ? 'text-[var(--text-primary)] bg-[var(--bg-elevated)] font-medium'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
                  }`}
                >
                  {main.text}
                </button>
                {subs.length > 0 && (
                  <div className="ml-2 border-l border-[var(--border-subtle)] pl-2 mt-1 mb-2 space-y-0.5">
                    {subs.slice(0, 6).map(sub => (
                      <button
                        key={sub.id}
                        onClick={() => scrollToSection(sub.id)}
                        className={`w-full text-left py-1 text-[11px] transition-colors truncate ${
                          activeSection === sub.id
                            ? 'text-[var(--text-secondary)]'
                            : 'text-[var(--text-ghost)] hover:text-[var(--text-muted)]'
                        }`}
                      >
                        {sub.text}
                      </button>
                    ))}
                    {subs.length > 6 && (
                      <span className="text-[10px] text-[var(--text-ghost)] pl-1">+{subs.length - 6} more</span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </nav>

      {/* Main content */}
      <div className="flex-1 min-w-0" ref={contentRef}>
        {/* Thesis callout */}
        {thesis && (
          <div className="mb-10 p-6 bg-gradient-to-r from-[var(--accent-muted)] to-transparent border-l-4 border-[var(--accent)] rounded-r-lg">
            <div className="text-[10px] font-mono uppercase tracking-widest text-[var(--accent)] mb-3">Investment Thesis</div>
            <p className="text-lg text-[var(--text-primary)] leading-relaxed font-medium">{thesis}</p>
          </div>
        )}

        {/* Mobile TOC dropdown */}
        <div className="lg:hidden mb-8">
          <details className="border border-[var(--border-subtle)] rounded-lg bg-[var(--bg-surface)]">
            <summary className="px-4 py-3 cursor-pointer text-xs font-mono uppercase tracking-wider text-[var(--text-muted)]">
              Jump to section
            </summary>
            <div className="px-4 pb-4 max-h-64 overflow-y-auto border-t border-[var(--border-subtle)]">
              {groupedToc.map(({ main }) => (
                <button
                  key={main.id}
                  onClick={() => {
                    scrollToSection(main.id);
                    (document.activeElement as HTMLElement)?.blur();
                  }}
                  className="block w-full text-left py-2 text-sm text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                >
                  {main.text}
                </button>
              ))}
            </div>
          </details>
        </div>

        {/* Report content */}
        <article className="prose prose-report">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {cleanedReport}
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

  return (
    <div>
      {/* Summary */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <div className="data-card">
          <div className="data-card-label">Vertical Analyses</div>
          <div className="data-card-value">{verticals.length}</div>
        </div>
        <div className="data-card">
          <div className="data-card-label">Research Threads</div>
          <div className="data-card-value">{threadIds.length}</div>
        </div>
        <div className="data-card">
          <div className="data-card-label">Avg Confidence</div>
          <div className="data-card-value">
            {Math.round(verticals.reduce((s, v) => s + (v.overall_confidence || 0), 0) / verticals.length * 100)}%
          </div>
        </div>
      </div>

      {/* Thread groups */}
      {threadIds.map((tid, tIdx) => {
        const items = grouped[tid];
        const isThreadExpanded = expandedThread === tid;
        const firstItem = items[0];

        return (
          <div key={tid} className="mb-3">
            {/* Thread header */}
            <button
              onClick={() => setExpandedThread(isThreadExpanded ? null : tid)}
              className={`w-full text-left p-4 rounded-lg border transition-all ${
                isThreadExpanded
                  ? 'border-[var(--accent)] bg-[var(--bg-elevated)]'
                  : 'border-[var(--border-subtle)] hover:border-[var(--border-default)] bg-[var(--bg-surface)]'
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-mono text-[var(--accent)]">
                      Thread {String(tIdx + 1).padStart(2, '0')}
                    </span>
                    <span className="text-xs text-[var(--text-ghost)]">·</span>
                    <span className="text-xs text-[var(--text-muted)]">{items.length} analyses</span>
                  </div>
                  <div className="text-sm font-medium text-[var(--text-primary)]">{firstItem.vertical_name?.split(':')[0] || `Thread ${tIdx + 1}`}</div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <div className="text-xs text-[var(--text-ghost)]">Confidence</div>
                    <div className="text-sm font-mono font-medium text-[var(--text-primary)]">
                      {Math.round(items.reduce((s, v) => s + (v.overall_confidence || 0), 0) / items.length * 100)}%
                    </div>
                  </div>
                  <span className="text-[var(--text-ghost)]">{isThreadExpanded ? '−' : '+'}</span>
                </div>
              </div>
            </button>

            {/* Expanded content */}
            {isThreadExpanded && (
              <div className="mt-1 border border-[var(--border-subtle)] rounded-lg overflow-hidden bg-[var(--bg-surface)]">
                {items.map((v, vIdx) => {
                  const vertKey = `${tid}-${vIdx}`;
                  const isVertExpanded = expandedVertical === vertKey;

                  return (
                    <div key={vIdx} className="border-b border-[var(--border-subtle)] last:border-b-0">
                      <button
                        onClick={() => setExpandedVertical(isVertExpanded ? null : vertKey)}
                        className={`w-full text-left px-4 py-3 flex items-center gap-3 ${
                          isVertExpanded ? 'bg-[var(--bg-elevated)]' : 'hover:bg-[var(--bg-elevated)]'
                        }`}
                      >
                        <span className="text-xs font-mono text-[var(--text-ghost)]">{vIdx + 1}</span>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm truncate text-[var(--text-secondary)]">{v.vertical_name}</div>
                        </div>
                        <div className="flex items-center gap-3 shrink-0">
                          <div className="w-20 h-1.5 bg-[var(--bg-hover)] rounded-full overflow-hidden">
                            <div
                              className="h-full bg-[var(--accent)] rounded-full"
                              style={{ width: `${(v.overall_confidence || 0) * 100}%` }}
                            />
                          </div>
                          <span className="text-xs font-mono w-10 text-[var(--text-muted)]">{Math.round((v.overall_confidence || 0) * 100)}%</span>
                          <span className="text-[var(--text-ghost)] text-sm">{isVertExpanded ? '−' : '+'}</span>
                        </div>
                      </button>

                      {isVertExpanded && v.business_understanding && (
                        <div className="px-4 pb-4 bg-[var(--bg-elevated)]">
                          <div className="pl-7 pt-2 prose prose-sm max-w-none">
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
    <div className="space-y-6">
      {/* Selector */}
      <div className="grid grid-cols-2 gap-3">
        {claude && (
          <button
            onClick={() => setSelected('claude')}
            className={`p-4 rounded-lg border text-left transition-all ${
              selected === 'claude'
                ? 'border-[var(--accent)] bg-[var(--accent-muted)]'
                : 'border-[var(--border-subtle)] hover:border-[var(--border-default)]'
            }`}
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)]">Claude</span>
              {winner === 'claude' && (
                <span className="text-xs px-1.5 py-0.5 bg-[var(--positive-muted)] text-[var(--positive)] rounded">Winner</span>
              )}
            </div>
            <div className="text-xl font-display font-bold text-[var(--text-primary)]">{claude.investment_view}</div>
            <div className="text-xs mt-1 text-[var(--text-muted)]">{Math.round(claude.confidence * 100)}% confidence</div>
          </button>
        )}
        {gpt && (
          <button
            onClick={() => setSelected('gpt')}
            className={`p-4 rounded-lg border text-left transition-all ${
              selected === 'gpt'
                ? 'border-[var(--accent)] bg-[var(--accent-muted)]'
                : 'border-[var(--border-subtle)] hover:border-[var(--border-default)]'
            }`}
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)]">GPT</span>
              {winner === 'gpt' && (
                <span className="text-xs px-1.5 py-0.5 bg-[var(--positive-muted)] text-[var(--positive)] rounded">Winner</span>
              )}
            </div>
            <div className="text-xl font-display font-bold text-[var(--text-primary)]">{gpt.investment_view}</div>
            <div className="text-xs mt-1 text-[var(--text-muted)]">{Math.round(gpt.confidence * 100)}% confidence</div>
          </button>
        )}
      </div>

      {/* Thesis */}
      {current?.thesis_summary && (
        <div className="p-4 bg-[var(--bg-elevated)] rounded-lg">
          <div className="text-label mb-2">THESIS</div>
          <p className="text-body-lg">{current.thesis_summary}</p>
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
    <div className="data-bar">
      <span className="data-bar-label truncate">{label}</span>
      <div className="data-bar-track">
        <div
          className="data-bar-fill bg-[var(--accent)]"
          style={{ width: `${Math.min(percentage, 100)}%` }}
        />
      </div>
      <span className="data-bar-value">${value.toFixed(2)}</span>
    </div>
  );
}

function Collapsible({ title, children, defaultOpen = false }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className={`collapsible mb-4 ${isOpen ? 'open' : ''}`}>
      <button onClick={() => setIsOpen(!isOpen)} className="collapsible-trigger">
        <span className="collapsible-title">{title}</span>
        <span className="collapsible-icon">{isOpen ? '−' : '+'}</span>
      </button>
      {isOpen && <div className="collapsible-content">{children}</div>}
    </div>
  );
}

// ===================== DATA VISUALIZATION COMPONENTS =====================

function formatCurrency(value: number): string {
  if (Math.abs(value) >= 1e12) return `$${(value / 1e12).toFixed(1)}T`;
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (Math.abs(value) >= 1e3) return `$${(value / 1e3).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}

function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
}

function formatCompact(value: number): string {
  if (Math.abs(value) >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(0)}M`;
  return value.toFixed(0);
}

// Mini sparkline component for inline trends
function Sparkline({ data, color = 'var(--accent)', height = 24, width = 80 }: {
  data: number[];
  color?: string;
  height?: number;
  width?: number;
}) {
  if (!data || data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * height;
    return `${x},${y}`;
  }).join(' ');

  const lastValue = data[data.length - 1];
  const firstValue = data[0];
  const trend = lastValue >= firstValue ? 'positive' : 'negative';
  const actualColor = color === 'auto'
    ? (trend === 'positive' ? 'var(--positive)' : 'var(--negative)')
    : color;

  return (
    <svg width={width} height={height} className="overflow-visible">
      <polyline
        points={points}
        fill="none"
        stroke={actualColor}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={(data.length - 1) / (data.length - 1) * width}
        cy={height - ((lastValue - min) / range) * height}
        r="2"
        fill={actualColor}
      />
    </svg>
  );
}

// Animated number counter
function AnimatedNumber({ value, prefix = '', suffix = '', decimals = 0 }: {
  value: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
}) {
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    const duration = 800;
    const steps = 30;
    const increment = value / steps;
    let current = 0;

    const timer = setInterval(() => {
      current += increment;
      if (current >= value) {
        setDisplay(value);
        clearInterval(timer);
      } else {
        setDisplay(current);
      }
    }, duration / steps);

    return () => clearInterval(timer);
  }, [value]);

  return <span>{prefix}{display.toFixed(decimals)}{suffix}</span>;
}

// Enhanced metric card with sparkline
function MetricCard({
  label,
  value,
  trend,
  sparklineData,
  format = 'number',
  prefix = '',
  suffix = '',
  decimals = 0,
  size = 'md'
}: {
  label: string;
  value: number;
  trend?: number;
  sparklineData?: number[];
  format?: 'currency' | 'percent' | 'number' | 'compact';
  prefix?: string;
  suffix?: string;
  decimals?: number;
  size?: 'sm' | 'md' | 'lg';
}) {
  const formattedValue = format === 'currency'
    ? formatCurrency(value)
    : format === 'percent'
    ? `${(value * 100).toFixed(decimals)}%`
    : format === 'compact'
    ? formatCompact(value)
    : value.toFixed(decimals);

  const displayValue = `${prefix}${formattedValue}${suffix}`;

  const sizeClasses = {
    sm: 'p-3',
    md: 'p-4',
    lg: 'p-5'
  };

  const valueSizes = {
    sm: 'text-lg',
    md: 'text-2xl',
    lg: 'text-3xl'
  };

  return (
    <div className={`bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg ${sizeClasses[size]} hover:border-[var(--border-default)] transition-all group`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="text-[10px] font-mono text-[var(--text-muted)] uppercase tracking-wider">{label}</span>
        {sparklineData && sparklineData.length > 1 && (
          <Sparkline data={sparklineData} color="auto" height={20} width={50} />
        )}
      </div>
      <div className={`font-mono font-semibold text-[var(--text-primary)] ${valueSizes[size]}`}>
        {displayValue}
      </div>
      {trend !== undefined && (
        <div className={`mt-1 text-xs font-mono ${trend >= 0 ? 'text-[var(--positive)]' : 'text-[var(--negative)]'}`}>
          {formatPercent(trend)} <span className="text-[var(--text-ghost)]">vs prior</span>
        </div>
      )}
    </div>
  );
}

// Waterfall chart for profitability breakdown
function WaterfallChart({ items }: {
  items: { label: string; value: number; color?: string }[];
}) {
  const maxValue = Math.max(...items.map(i => Math.abs(i.value)));

  return (
    <div className="mb-8 p-6 bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-lg">
      <div className="text-label mb-6">PROFITABILITY WATERFALL</div>
      <div className="space-y-4">
        {items.map((item, i) => {
          const width = maxValue > 0 ? (Math.abs(item.value) / maxValue) * 100 : 0;
          const isNegative = item.value < 0;
          const color = item.color || 'var(--accent)';

          return (
            <div key={i} className="group">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-mono text-[var(--text-muted)] uppercase tracking-wider">{item.label}</span>
                <span className={`text-sm font-mono font-semibold ${isNegative ? 'text-[var(--negative)]' : 'text-[var(--text-primary)]'}`}>
                  {formatCurrency(item.value)}
                </span>
              </div>
              <div className="h-8 bg-[var(--bg-hover)] rounded-lg relative overflow-hidden">
                <div
                  className="absolute h-full rounded-lg transition-all duration-700 group-hover:brightness-125"
                  style={{
                    width: `${width}%`,
                    background: color,
                    boxShadow: `0 0 20px ${color}33`
                  }}
                />
                {/* Percentage label inside bar */}
                <div
                  className="absolute h-full flex items-center px-3 text-[10px] font-mono font-medium transition-opacity"
                  style={{ color: width > 25 ? 'var(--bg-void)' : 'var(--text-muted)' }}
                >
                  {maxValue > 0 ? `${((item.value / items[0].value) * 100).toFixed(0)}%` : '0%'}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Interactive bar chart with tooltips
function BarChart({
  data,
  title,
  height = 140,
  color = 'var(--accent)',
  formatValue = formatCurrency
}: {
  data: { label: string; value: number; change?: number }[];
  title: string;
  height?: number;
  color?: string;
  formatValue?: (v: number) => string;
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  if (!data || data.length === 0) return null;

  const values = data.map(d => d.value);
  const maxValue = Math.max(...values.filter(v => v > 0), 1);
  const minValue = Math.min(...values);

  return (
    <div className="mb-8 p-6 bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-lg">
      <div className="flex items-center justify-between mb-4">
        <span className="text-label">{title}</span>
        {hoveredIndex !== null && (
          <div className="flex items-center gap-3 text-xs font-mono animate-fade-in">
            <span className="text-[var(--text-primary)]">{formatValue(values[hoveredIndex])}</span>
            {hoveredIndex > 0 && values[hoveredIndex - 1] !== 0 && (
              <span className={values[hoveredIndex] >= values[hoveredIndex - 1] ? 'text-[var(--positive)]' : 'text-[var(--negative)]'}>
                {formatPercent((values[hoveredIndex] - values[hoveredIndex - 1]) / Math.abs(values[hoveredIndex - 1]))}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="relative" style={{ height }}>
        {/* Grid lines */}
        <div className="absolute inset-0 flex flex-col justify-between pointer-events-none">
          {[0, 1, 2, 3].map(i => (
            <div key={i} className="border-t border-[var(--border-subtle)] border-dashed opacity-50" />
          ))}
        </div>

        {/* Bars */}
        <div className="absolute inset-0 flex items-end gap-2 px-1">
          {data.map((d, i) => {
            const value = d.value;
            const barHeight = maxValue > 0 ? (Math.abs(value) / maxValue) * 100 : 0;
            const isHovered = hoveredIndex === i;
            const isNegative = value < 0;

            return (
              <div
                key={d.label}
                className="flex-1 flex flex-col items-center justify-end h-full cursor-pointer group"
                onMouseEnter={() => setHoveredIndex(i)}
                onMouseLeave={() => setHoveredIndex(null)}
              >
                <div
                  className="w-full rounded-t transition-all duration-300"
                  style={{
                    height: `${barHeight}%`,
                    minHeight: value !== 0 ? '4px' : '0',
                    background: isHovered ? color : isNegative ? 'var(--negative)' : `${color}80`,
                    transform: isHovered ? 'scaleX(1.1)' : 'scaleX(1)',
                    boxShadow: isHovered ? `0 0 25px ${color}66` : 'none'
                  }}
                />
                <div className={`mt-2 text-center transition-opacity ${isHovered ? 'opacity-100' : 'opacity-60'}`}>
                  <div className="text-[9px] font-mono text-[var(--text-ghost)] uppercase truncate w-full">
                    {d.label}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Y-axis labels */}
      <div className="flex justify-between mt-2 text-[9px] font-mono text-[var(--text-ghost)]">
        <span>0</span>
        <span>{formatCompact(maxValue)}</span>
      </div>
    </div>
  );
}

// Comparison chart for year-over-year
function ComparisonChart({ data, metrics }: {
  data: { label: string; [key: string]: string | number }[];
  metrics: { key: string; label: string; color: string }[];
}) {
  if (!data || data.length === 0) return null;

  const allValues = metrics.flatMap(m => data.map(d => Number(d[m.key]) || 0));
  const maxValue = Math.max(...allValues.filter(v => v > 0), 1);

  return (
    <div className="mb-8 p-6 bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-lg">
      <div className="text-label mb-4">YEAR OVER YEAR</div>

      {/* Legend */}
      <div className="flex gap-6 mb-6">
        {metrics.map((m) => (
          <div key={m.key} className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full" style={{ background: m.color }} />
            <span className="text-xs font-mono text-[var(--text-muted)]">{m.label}</span>
          </div>
        ))}
      </div>

      <div className="space-y-6">
        {data.map((row, yi) => {
          return (
            <div key={row.label} className="group">
              <div className="flex items-center gap-4 mb-2">
                <span className="w-12 text-sm font-mono font-medium text-[var(--text-primary)]">{row.label}</span>
                <div className="flex-1 flex items-center gap-1">
                  {metrics.map((m) => {
                    const value = Number(row[m.key]) || 0;
                    const width = maxValue > 0 ? (value / maxValue) * 100 : 0;
                    const prevValue = yi > 0 ? Number(data[yi-1][m.key]) || 0 : value;
                    const growth = prevValue > 0 ? (value - prevValue) / prevValue : 0;

                    return (
                      <div key={m.key} className="flex-1 group/bar">
                        <div className="h-8 bg-[var(--bg-hover)] rounded-lg overflow-hidden relative">
                          <div
                            className="h-full rounded-lg transition-all duration-700 flex items-center justify-end pr-2 group-hover/bar:brightness-125"
                            style={{ width: `${width}%`, background: m.color }}
                          >
                            <span className="text-[10px] font-mono text-[var(--bg-void)] font-medium opacity-0 group-hover/bar:opacity-100 transition-opacity">
                              {formatCurrency(value)}
                            </span>
                          </div>
                        </div>
                        {yi > 0 && (
                          <div className={`text-[9px] font-mono mt-1 text-center ${growth >= 0 ? 'text-[var(--positive)]' : 'text-[var(--negative)]'}`}>
                            {formatPercent(growth)}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Donut chart for composition
function DonutChart({ segments, size = 120, label }: {
  segments: { label: string; value: number; color: string }[];
  size?: number;
  label?: string;
}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  const strokeWidth = size * 0.15;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  let currentOffset = 0;

  return (
    <div className="flex items-center gap-6">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="transform -rotate-90">
          {segments.map((segment, i) => {
            const percent = segment.value / total;
            const strokeDasharray = `${percent * circumference} ${circumference}`;
            const strokeDashoffset = -currentOffset * circumference;
            currentOffset += percent;

            return (
              <circle
                key={i}
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={segment.color}
                strokeWidth={strokeWidth}
                strokeDasharray={strokeDasharray}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
                className="transition-all duration-700"
              />
            );
          })}
        </svg>
        {label && (
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-xs font-mono text-[var(--text-muted)]">{label}</span>
          </div>
        )}
      </div>

      <div className="space-y-2">
        {segments.map((segment, i) => (
          <div key={i} className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full" style={{ background: segment.color }} />
            <span className="text-xs text-[var(--text-muted)]">{segment.label}</span>
            <span className="text-xs font-mono text-[var(--text-primary)]">
              {((segment.value / total) * 100).toFixed(0)}%
            </span>
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
            className="py-3 border-b border-[var(--border-subtle)] last:border-b-0 group hover:bg-[var(--bg-elevated)] px-3 -mx-3 rounded transition-colors"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <h4 className="text-sm font-medium text-[var(--text-primary)] leading-snug mb-1 group-hover:text-[var(--accent)] transition-colors">
                  {item.title}
                </h4>
                {item.summary && (
                  <p className="text-xs text-[var(--text-muted)] line-clamp-2">{item.summary}</p>
                )}
              </div>
              <div className="shrink-0 text-right">
                <div className="text-[10px] font-mono text-[var(--text-ghost)]">
                  {new Date(item.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                </div>
                <div className="text-[9px] font-mono text-[var(--text-ghost)] uppercase">{item.source}</div>
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
          <div className="w-8 h-8 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-sm text-[var(--text-muted)] font-mono">Loading financials...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-20">
        <p className="text-[var(--negative)] text-sm">{error}</p>
      </div>
    );
  }

  if (!data) return null;

  const profile = data.profile || {};
  const quarterly = data.income_statement?.quarterly || [];
  const annual = data.income_statement?.annual || [];
  const latestQ = quarterly[0];
  const latestA = annual[0];

  const latestRevenue = latestQ?.revenue || latestA?.revenue || 0;
  const latestGrossProfit = latestQ?.grossProfit || latestA?.grossProfit || 0;
  const latestNetIncome = latestQ?.netIncome || latestA?.netIncome || 0;
  const grossMargin = latestRevenue > 0 ? latestGrossProfit / latestRevenue : 0;
  const netMargin = latestRevenue > 0 ? latestNetIncome / latestRevenue : 0;

  return (
    <div>
      {/* Company Header */}
      <div className="mb-8 pb-6 border-b border-[var(--border-subtle)]">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-2xl font-display font-bold text-[var(--text-primary)]">{profile.companyName || ticker}</h2>
            <div className="text-sm text-[var(--text-muted)] mt-1">
              {profile.sector && <span>{profile.sector}</span>}
              {profile.industry && <span> · {profile.industry}</span>}
            </div>
          </div>
          <div className="text-right">
            {profile.price && (
              <div className="text-2xl font-mono font-bold text-[var(--text-primary)]">${profile.price.toFixed(2)}</div>
            )}
            {profile.marketCap && (
              <div className="text-xs text-[var(--text-muted)] font-mono">
                {formatCurrency(profile.marketCap)} market cap
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Sub-navigation */}
      <div className="tabs mb-8">
        {(['overview', 'quarterly', 'annual', 'news'] as const).map(view => (
          <button
            key={view}
            onClick={() => setActiveView(view)}
            className={`tab ${activeView === view ? 'active' : ''}`}
          >
            {view}
          </button>
        ))}
      </div>

      {/* Overview */}
      {activeView === 'overview' && (
        <div className="animate-fade-in">
          {/* Key Metrics Grid with Sparklines */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <MetricCard
              label="Revenue (TTM)"
              value={latestRevenue}
              prefix="$"
              format="currency"
              trend={quarterly.length > 1 && quarterly[1]?.revenue
                ? (latestRevenue - quarterly[1].revenue) / quarterly[1].revenue
                : undefined}
              sparklineData={quarterly.slice(0, 8).map(q => q.revenue).reverse()}
            />
            <MetricCard
              label="Net Income"
              value={latestNetIncome}
              prefix="$"
              format="currency"
              trend={quarterly.length > 1 && quarterly[1]?.netIncome
                ? (latestNetIncome - quarterly[1].netIncome) / Math.abs(quarterly[1].netIncome)
                : undefined}
              sparklineData={quarterly.slice(0, 8).map(q => q.netIncome).reverse()}
            />
            <MetricCard
              label="Gross Margin"
              value={grossMargin * 100}
              suffix="%"
              decimals={1}
            />
            <MetricCard
              label="Net Margin"
              value={netMargin * 100}
              suffix="%"
              decimals={1}
              trend={netMargin >= 0.1 ? 0.05 : netMargin >= 0 ? 0 : -0.05}
            />
          </div>

          {/* Quarterly Revenue Chart - Interactive */}
          {quarterly.length > 0 && (
            <BarChart
              data={quarterly.slice(0, 8).reverse().map(q => ({
                label: q.date?.slice(0, 7) || '',
                value: q.revenue,
                change: undefined
              }))}
              title="QUARTERLY REVENUE"
              height={220}
              color="var(--accent)"
              formatValue={(v) => formatCurrency(v)}
            />
          )}

          {/* Profitability Waterfall - Visual breakdown */}
          {latestRevenue > 0 && (
            <WaterfallChart
              items={[
                { label: 'Revenue', value: latestRevenue, color: 'var(--accent)' },
                { label: 'Gross Profit', value: latestGrossProfit, color: 'var(--positive)' },
                { label: 'Operating Income', value: latestQ?.operatingIncome || latestA?.operatingIncome || 0, color: 'var(--warning)' },
                { label: 'Net Income', value: latestNetIncome, color: latestNetIncome >= 0 ? 'var(--positive)' : 'var(--negative)' },
              ]}
            />
          )}

          {/* Quick News */}
          {data.news && data.news.length > 0 && (
            <div className="border-t border-[var(--border-subtle)] pt-6">
              <NewsTimeline news={data.news.slice(0, 3)} />
            </div>
          )}
        </div>
      )}

      {/* Quarterly Detail */}
      {activeView === 'quarterly' && quarterly.length > 0 && (
        <div className="animate-fade-in">
          {/* Revenue Chart with YoY changes */}
          <BarChart
            data={quarterly.slice(0, 8).reverse().map((q, i, arr) => {
              const prevYearQ = arr[i - 4];
              return {
                label: q.date?.slice(0, 7) || '',
                value: q.revenue,
                change: prevYearQ ? (q.revenue - prevYearQ.revenue) / prevYearQ.revenue : undefined
              };
            })}
            title="REVENUE BY QUARTER"
            height={200}
            color="var(--accent)"
            formatValue={(v) => formatCurrency(v)}
          />

          {/* Net Income Chart */}
          <BarChart
            data={quarterly.slice(0, 8).reverse().map(q => ({
              label: q.date?.slice(0, 7) || '',
              value: q.netIncome,
              change: undefined
            }))}
            title="NET INCOME BY QUARTER"
            height={200}
            color="var(--positive)"
            formatValue={(v) => formatCurrency(v)}
          />

          <div className="text-label mb-4">QUARTERLY BREAKDOWN</div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b-2 border-[var(--border-default)]">
                  <th className="text-left py-3 pr-4 text-[var(--text-muted)]">Period</th>
                  <th className="text-right py-3 px-2 text-[var(--text-muted)]">Revenue</th>
                  <th className="text-right py-3 px-2 text-[var(--text-muted)]">Gross</th>
                  <th className="text-right py-3 px-2 text-[var(--text-muted)]">Op Inc</th>
                  <th className="text-right py-3 px-2 text-[var(--text-muted)]">Net Inc</th>
                  <th className="text-right py-3 pl-2 text-[var(--text-muted)]">EPS</th>
                </tr>
              </thead>
              <tbody>
                {quarterly.slice(0, 8).map((q, i) => {
                  const prevQ = quarterly[i + 1];
                  const revGrowth = prevQ?.revenue ? (q.revenue - prevQ.revenue) / prevQ.revenue : 0;

                  return (
                    <tr key={q.date} className="border-b border-[var(--border-subtle)] hover:bg-[var(--bg-elevated)]">
                      <td className="py-3 pr-4 text-[var(--text-muted)]">
                        {q.date?.slice(0, 7)}
                      </td>
                      <td className="py-3 px-2 text-right text-[var(--text-primary)]">
                        {formatCurrency(q.revenue)}
                        {prevQ && (
                          <span className={`ml-2 ${revGrowth >= 0 ? 'text-[var(--positive)]' : 'text-[var(--negative)]'}`}>
                            {formatPercent(revGrowth)}
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-2 text-right text-[var(--text-secondary)]">{formatCurrency(q.grossProfit)}</td>
                      <td className="py-3 px-2 text-right text-[var(--text-secondary)]">{formatCurrency(q.operatingIncome)}</td>
                      <td className={`py-3 px-2 text-right ${q.netIncome < 0 ? 'text-[var(--negative)]' : 'text-[var(--text-secondary)]'}`}>
                        {formatCurrency(q.netIncome)}
                      </td>
                      <td className="py-3 pl-2 text-right text-[var(--text-secondary)]">${q.epsDiluted?.toFixed(2) || '—'}</td>
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
          {/* Multi-year comparison chart */}
          <ComparisonChart
            data={annual.slice(0, 5).reverse().map(a => ({
              label: a.date?.slice(0, 4) || '',
              revenue: a.revenue,
              grossProfit: a.grossProfit,
              netIncome: a.netIncome,
            }))}
            metrics={[
              { key: 'revenue', label: 'Revenue', color: 'var(--accent)' },
              { key: 'grossProfit', label: 'Gross Profit', color: 'var(--positive)' },
              { key: 'netIncome', label: 'Net Income', color: 'var(--warning)' },
            ]}
          />

          <div className="text-label mb-4">ANNUAL STATEMENTS</div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b-2 border-[var(--border-default)]">
                  <th className="text-left py-3 pr-4 text-[var(--text-muted)]">Year</th>
                  <th className="text-right py-3 px-2 text-[var(--text-muted)]">Revenue</th>
                  <th className="text-right py-3 px-2 text-[var(--text-muted)]">YoY</th>
                  <th className="text-right py-3 px-2 text-[var(--text-muted)]">Gross Profit</th>
                  <th className="text-right py-3 px-2 text-[var(--text-muted)]">Net Income</th>
                  <th className="text-right py-3 pl-2 text-[var(--text-muted)]">EPS</th>
                </tr>
              </thead>
              <tbody>
                {annual.slice(0, 5).map((a, i) => {
                  const prevA = annual[i + 1];
                  const revGrowth = prevA?.revenue ? (a.revenue - prevA.revenue) / prevA.revenue : 0;

                  return (
                    <tr key={a.date} className="border-b border-[var(--border-subtle)] hover:bg-[var(--bg-elevated)]">
                      <td className="py-3 pr-4 font-medium text-[var(--text-primary)]">{a.date?.slice(0, 4)}</td>
                      <td className="py-3 px-2 text-right text-[var(--text-primary)]">{formatCurrency(a.revenue)}</td>
                      <td className={`py-3 px-2 text-right ${revGrowth >= 0 ? 'text-[var(--positive)]' : 'text-[var(--negative)]'}`}>
                        {prevA ? formatPercent(revGrowth) : '—'}
                      </td>
                      <td className="py-3 px-2 text-right text-[var(--text-secondary)]">{formatCurrency(a.grossProfit)}</td>
                      <td className={`py-3 px-2 text-right ${a.netIncome < 0 ? 'text-[var(--negative)]' : 'text-[var(--text-secondary)]'}`}>
                        {formatCurrency(a.netIncome)}
                      </td>
                      <td className="py-3 pl-2 text-right text-[var(--text-secondary)]">${a.epsDiluted?.toFixed(2) || '—'}</td>
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
            <p className="text-[var(--text-ghost)] text-center py-10">No recent news available</p>
          )}
        </div>
      )}
    </div>
  );
}

// ===================== MAIN COMPONENT =====================

// Theme toggle component
function ThemeToggle({ theme, setTheme }: { theme: 'dark' | 'light'; setTheme: (t: 'dark' | 'light') => void }) {
  return (
    <button
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      className="p-2 rounded-lg border border-[var(--border-subtle)] hover:border-[var(--border-default)] hover:bg-[var(--bg-hover)] transition-all"
      title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
    >
      {theme === 'dark' ? (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-[var(--text-muted)]">
          <circle cx="12" cy="12" r="5"/>
          <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-[var(--text-muted)]">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
        </svg>
      )}
    </button>
  );
}

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
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');

  // Apply theme to document
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  // Load saved theme
  useEffect(() => {
    const saved = localStorage.getItem('theme') as 'dark' | 'light' | null;
    if (saved) setTheme(saved);
  }, []);

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
      <div className="min-h-screen flex flex-col bg-[var(--bg-void)]">
        {/* Header */}
        <header className="px-6 py-4 flex items-center justify-between border-b border-[var(--border-subtle)]">
          <span className="font-mono text-sm uppercase tracking-wider text-[var(--text-muted)]">K+ Research</span>
          <nav className="flex items-center gap-4">
            {activeRuns.length > 0 && (
              <button
                onClick={() => goToRun(activeRuns[0])}
                className="flex items-center gap-2 px-3 py-1.5 bg-[var(--accent-muted)] border border-[var(--accent)] text-[var(--accent)] text-xs font-mono uppercase rounded"
              >
                <span className="status-dot processing" />
                {activeRuns.length} Active
              </button>
            )}
            <button
              onClick={() => { loadRuns(); setView('archive'); }}
              className="nav-link"
            >
              Archive ({allRuns.length})
            </button>
          </nav>
        </header>

        {/* Main - Centered hero */}
        <main className="flex-1 flex flex-col items-center justify-center px-8">
          {/* K+ Brand */}
          <h1 className="text-massive animate-fade-up">
            K<span className="text-[var(--accent)]">+</span>
          </h1>

          {/* Ticker Input */}
          <div className="mt-16 animate-fade-up delay-2">
            <div className="flex items-center gap-6">
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
                className="btn btn-primary"
              >
                Analyze
              </button>
            </div>
            {error && (
              <p className="mt-4 text-sm text-[var(--negative)] text-center">{error}</p>
            )}
          </div>

          {/* Subtle tagline */}
          <p className="mt-8 text-xs text-[var(--text-ghost)] font-mono tracking-wider animate-fade-up delay-4">
            EQUITY INTELLIGENCE
          </p>
        </main>
      </div>
    );
  }

  // ==================== ARCHIVE ====================
  if (view === 'archive') {
    return (
      <div className="min-h-screen flex flex-col bg-[var(--bg-void)]">
        <header className="px-6 py-4 flex items-center justify-between border-b border-[var(--border-subtle)]">
          <button
            onClick={() => setView('home')}
            className="nav-link"
          >
            ← Home
          </button>
          <span className="font-mono text-sm text-[var(--text-muted)]">
            {activeRuns.length} active · {completedRuns.length} completed
          </span>
        </header>

        <main className="flex-1 px-6 py-6 overflow-auto">
          {allRuns.length === 0 ? (
            <p className="text-center text-[var(--text-ghost)] py-20">No runs yet.</p>
          ) : (
            <div className="max-w-3xl mx-auto space-y-2">
              {allRuns.map((run) => (
                <div
                  key={run.id}
                  className="card card-interactive flex items-center gap-4"
                >
                  <button
                    onClick={() => goToRun(run)}
                    className="flex-1 text-left flex items-center gap-4"
                  >
                    <span className="font-mono font-semibold text-[var(--text-primary)] w-16">{run.ticker}</span>
                    <span className="text-xs text-[var(--text-ghost)] w-24">
                      {new Date(run.createdAt).toLocaleDateString()}
                    </span>
                    {run.isActive ? (
                      <span className="ml-auto flex items-center gap-2 text-xs font-mono text-[var(--accent)]">
                        <span className="status-dot processing" />
                        Stage {run.currentStage || '?'}/5
                      </span>
                    ) : run.verdict ? (
                      <span className={`ml-auto text-xs font-mono font-semibold ${
                        run.verdict.investmentView.toUpperCase() === 'BUY' ? 'text-[var(--positive)]' :
                        run.verdict.investmentView.toUpperCase() === 'SELL' ? 'text-[var(--negative)]' :
                        'text-[var(--warning)]'
                      }`}>
                        {run.verdict.investmentView}
                      </span>
                    ) : (
                      <span className="ml-auto text-xs text-[var(--text-ghost)]">—</span>
                    )}
                  </button>
                  {!run.isActive && (
                    <button
                      onClick={(e) => deleteRun(run.id, e)}
                      className="px-2 py-2 text-sm text-[var(--text-ghost)] hover:text-[var(--negative)] transition-colors"
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
      <div className="min-h-screen flex flex-col bg-[var(--bg-void)]">
        <header className="px-6 py-4 flex items-center justify-between border-b border-[var(--border-subtle)]">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setView('home')}
              className="nav-link"
            >
              ← Home
            </button>
            <span className="text-[var(--text-ghost)]">·</span>
            <span className="font-mono font-bold text-[var(--text-primary)]">{runningTicker}</span>
          </div>
          <div className="flex items-center gap-4">
            {isRunning ? (
              <>
                <span className="flex items-center gap-2 text-xs font-mono text-[var(--accent)]">
                  <span className="status-dot processing" />
                  Processing
                </span>
                {runningRunId && (
                  <button
                    onClick={() => cancelRun(runningRunId)}
                    className="text-xs font-mono uppercase text-[var(--text-muted)] hover:text-[var(--negative)] transition-colors"
                  >
                    Cancel
                  </button>
                )}
              </>
            ) : (
              <span className="flex items-center gap-2 text-xs font-mono text-[var(--positive)]">
                <span className="status-dot active" />
                Complete
              </span>
            )}
          </div>
        </header>

        <main className="flex-1 px-6 py-8 overflow-auto">
          <div className="max-w-5xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* Left: Progress */}
            <div>
              <h1 className="text-2xl font-display font-bold text-[var(--text-primary)] mb-6">
                {isRunning ? 'Processing...' : 'Analysis Complete'}
              </h1>

              {/* Progress bar */}
              <div className="progress-line mb-8">
                <div className="progress-fill" style={{ width: `${progress}%` }} />
              </div>

              {/* Stages */}
              <div className="space-y-1">
                {stages.map((stage, i) => {
                  const isComplete = i < currentStage;
                  const isCurrent = i === currentStage - 1 && isRunning;

                  return (
                    <div
                      key={stage.num}
                      className={`stage ${isCurrent ? 'active' : ''} ${isComplete ? 'complete' : ''}`}
                    >
                      <span className="stage-num">{String(stage.num).padStart(2, '0')}</span>
                      <span className="stage-name">{stage.name}</span>
                      <span className="ml-auto text-sm">
                        {isComplete && <span className="text-[var(--positive)]">✓</span>}
                        {isCurrent && <span className="animate-pulse text-[var(--accent)]">●</span>}
                      </span>
                    </div>
                  );
                })}
              </div>

              {/* Actions */}
              {!isRunning && (
                <div className="mt-8 flex gap-3">
                  {runningRunId && (
                    <button
                      onClick={() => goToRun({
                        id: runningRunId,
                        ticker: runningTicker,
                        status: 'complete',
                        createdAt: new Date().toISOString(),
                        isActive: false
                      })}
                      className="btn btn-primary"
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

            {/* Right: Event Log */}
            <div className="event-log">
              <div className="text-xs font-mono text-[var(--text-ghost)] mb-3">
                {events.length} events
              </div>
              {events.length === 0 ? (
                <p className="text-[var(--text-ghost)] text-sm">Waiting for events...</p>
              ) : (
                <div className="space-y-1">
                  {events.slice(-50).map((event, i) => (
                    <div key={i} className={`event-log-item ${
                      event.type === 'stage_start' ? 'stage-start' :
                      event.type === 'stage_complete' ? 'stage-complete' :
                      event.type === 'error' ? 'error' : ''
                    }`}>
                      {event.type === 'stage_start' && <span>→ {event.data?.stage_name}</span>}
                      {event.type === 'stage_complete' && <span>✓ {event.data?.stage_name}</span>}
                      {event.type === 'agent_event' && <span>{event.data?.message || '...'}</span>}
                      {event.type === 'complete' && <span className="font-bold">● Complete</span>}
                      {event.type === 'error' && <span>× {event.data?.detail}</span>}
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
      <div className="min-h-screen bg-[var(--bg-void)]">
        {/* Header */}
        <header className="px-6 py-4 flex items-center justify-between border-b border-[var(--border-subtle)]">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setView('home')}
              className="nav-link"
            >
              ←
            </button>
            <span className="font-mono font-bold text-xl text-[var(--text-primary)]">{selectedRun.ticker}</span>
            {sr?.conviction && (
              <span className={`px-2 py-1 text-xs font-mono uppercase rounded ${
                sr.conviction.toLowerCase().includes('high')
                  ? 'bg-[var(--text-primary)] text-[var(--bg-void)]'
                  : 'border border-[var(--border-default)] text-[var(--text-secondary)]'
              }`}>
                {sr.conviction}
              </span>
            )}
          </div>
          <div className="flex items-center gap-4 text-xs text-[var(--text-ghost)]">
            <span>{new Date(selectedRun.createdAt).toLocaleDateString()}</span>
            {costs && <span className="font-mono">${costs.total_cost_usd.toFixed(2)}</span>}
            <ThemeToggle theme={theme} setTheme={setTheme} />
          </div>
        </header>

        {/* Tabs */}
        <div className="px-6 border-b border-[var(--border-subtle)] tabs">
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
          <div className={reportTab === 'report' ? 'max-w-[85rem] mx-auto' : 'max-w-5xl mx-auto'}>

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

                {/* Scenarios Chart - Horizontal Bar */}
                {sr?.scenarios && (
                  <div className="mb-10 p-6 border border-[var(--border-subtle)] rounded-lg bg-[var(--bg-surface)]">
                    <div className="text-label mb-4">SCENARIO ANALYSIS</div>

                    {/* Probability bar */}
                    <div className="flex mb-6 h-10 rounded-lg overflow-hidden">
                      <div
                        className="bg-[var(--positive)] flex items-center justify-center text-xs text-white font-mono font-medium"
                        style={{ width: `${sr.scenarios.bull.probability * 100}%` }}
                      >
                        {Math.round(sr.scenarios.bull.probability * 100)}%
                      </div>
                      <div
                        className="bg-[var(--text-muted)] flex items-center justify-center text-xs text-white font-mono font-medium"
                        style={{ width: `${sr.scenarios.base.probability * 100}%` }}
                      >
                        {Math.round(sr.scenarios.base.probability * 100)}%
                      </div>
                      <div
                        className="bg-[var(--negative)] flex items-center justify-center text-xs text-white font-mono font-medium"
                        style={{ width: `${sr.scenarios.bear.probability * 100}%` }}
                      >
                        {Math.round(sr.scenarios.bear.probability * 100)}%
                      </div>
                    </div>

                    {/* Scenario cards */}
                    <div className="grid grid-cols-3 gap-4">
                      <div className="scenario-card bull">
                        <div className="text-xs font-mono text-[var(--positive)] mb-2">BULL</div>
                        <p className="text-sm text-[var(--text-primary)]">{sr.scenarios.bull.headline}</p>
                      </div>
                      <div className="scenario-card base">
                        <div className="text-xs font-mono text-[var(--text-muted)] mb-2">BASE</div>
                        <p className="text-sm text-[var(--text-primary)]">{sr.scenarios.base.headline}</p>
                      </div>
                      <div className="scenario-card bear">
                        <div className="text-xs font-mono text-[var(--negative)] mb-2">BEAR</div>
                        <p className="text-sm text-[var(--text-primary)]">{sr.scenarios.bear.headline}</p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Key Risks & Debates */}
                {(sr?.top_risks || sr?.key_debates) && (
                  <div className="mb-10 grid grid-cols-1 md:grid-cols-2 gap-4">
                    {sr?.top_risks && sr.top_risks.length > 0 && (
                      <div className="p-4 border border-[var(--border-subtle)] rounded-lg bg-[var(--bg-surface)]">
                        <div className="text-label mb-3">TOP RISKS</div>
                        <div className="space-y-2">
                          {sr.top_risks.slice(0, 4).map((risk, i) => (
                            <div key={i} className="flex gap-2 text-sm">
                              <span className="text-[var(--negative)] shrink-0">!</span>
                              <span className="text-[var(--text-secondary)]">{risk}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {sr?.key_debates && sr.key_debates.length > 0 && (
                      <div className="p-4 border border-[var(--border-subtle)] rounded-lg bg-[var(--bg-surface)]">
                        <div className="text-label mb-3">KEY DEBATES</div>
                        <div className="space-y-2">
                          {sr.key_debates.slice(0, 4).map((debate, i) => (
                            <div key={i} className="flex gap-2 text-sm">
                              <span className="text-[var(--warning)] shrink-0">?</span>
                              <span className="text-[var(--text-secondary)]">{debate}</span>
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
                  <p className="text-[var(--text-ghost)]">Loading report...</p>
                )}
              </div>
            )}

            {/* DISCOVERY TAB */}
            {reportTab === 'discovery' && (
              <div className="animate-fade-in">
                {discovery ? (
                  <DiscoveryView discovery={discovery} />
                ) : (
                  <p className="text-[var(--text-ghost)]">No discovery data available</p>
                )}
              </div>
            )}

            {/* VERTICALS TAB */}
            {reportTab === 'verticals' && (
              <div className="animate-fade-in">
                {verticals && verticals.length > 0 ? (
                  <VerticalsView verticals={verticals} />
                ) : (
                  <p className="text-[var(--text-ghost)]">No vertical analysis available</p>
                )}
              </div>
            )}

            {/* SYNTHESIS TAB */}
            {reportTab === 'synthesis' && (
              <div className="animate-fade-in">
                <div className="mb-6">
                  <h2 className="text-title text-[var(--text-primary)] mb-2">Model Synthesis</h2>
                  <p className="text-sm text-[var(--text-muted)]">
                    Compare the competing analysis from Claude and GPT
                  </p>
                </div>

                {ef && (
                  <div className="mb-6 p-4 border border-[var(--border-subtle)] rounded-lg bg-[var(--bg-surface)]">
                    <div className="text-label mb-2">JUDGE DECISION</div>
                    <p className="text-sm text-[var(--text-secondary)] mb-3">{ef.preference_reasoning}</p>
                    <div className="flex gap-4 text-xs font-mono">
                      <span className="text-[var(--text-muted)]">Claude: {Math.round((ef.claude_score || 0) * 100)}</span>
                      <span className="text-[var(--text-muted)]">GPT: {Math.round((ef.gpt_score || 0) * 100)}</span>
                      <span className="text-[var(--accent)]">Winner: {ef.preferred_synthesis}</span>
                    </div>
                  </div>
                )}

                <SynthesisCompare
                  claude={fullRunData?.claude_synthesis}
                  gpt={fullRunData?.gpt_synthesis}
                  winner={ef?.preferred_synthesis}
                />

                {!fullRunData?.claude_synthesis && !fullRunData?.gpt_synthesis && (
                  <p className="text-[var(--text-ghost)]">No synthesis data available</p>
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
                <div className="mb-8">
                  <h2 className="text-title text-[var(--text-primary)] mb-2">Cost Analysis</h2>
                  <p className="text-sm text-[var(--text-muted)]">
                    Token usage and API costs for this analysis run
                  </p>
                </div>

                {/* Key Metrics with AnimatedNumber */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
                  <MetricCard
                    label="Total Cost"
                    value={costs.total_cost_usd}
                    prefix="$"
                    decimals={2}
                    trend={costs.budget_limit > 0 ? -(1 - costs.total_cost_usd / costs.budget_limit) : undefined}
                  />
                  <MetricCard
                    label="Budget Used"
                    value={costs.budget_limit > 0 ? (costs.total_cost_usd / costs.budget_limit) * 100 : 0}
                    suffix="%"
                    decimals={0}
                  />
                  <MetricCard
                    label="Input Tokens"
                    value={costs.total_input_tokens}
                    format="compact"
                  />
                  <MetricCard
                    label="Output Tokens"
                    value={costs.total_output_tokens}
                    format="compact"
                  />
                </div>

                {/* Cost Distribution Visual */}
                <div className="grid md:grid-cols-2 gap-8 mb-10">
                  {/* Provider Donut */}
                  {costs.by_provider && Object.keys(costs.by_provider).length > 0 && (
                    <div className="p-6 bg-[var(--bg-surface)] rounded-lg border border-[var(--border-subtle)]">
                      <div className="text-label mb-6">COST BY PROVIDER</div>
                      <DonutChart
                        segments={Object.entries(costs.by_provider)
                          .sort((a, b) => b[1] - a[1])
                          .map(([label, value], i) => ({
                            label,
                            value,
                            color: ['var(--accent)', 'var(--positive)', 'var(--warning)', 'var(--text-muted)'][i % 4]
                          }))}
                        size={140}
                        label={`$${costs.total_cost_usd.toFixed(2)}`}
                      />
                    </div>
                  )}

                  {/* Agent Breakdown */}
                  {costs.by_agent && Object.keys(costs.by_agent).length > 0 && (
                    <div className="p-6 bg-[var(--bg-surface)] rounded-lg border border-[var(--border-subtle)]">
                      <div className="text-label mb-6">COST BY AGENT</div>
                      <div className="space-y-4">
                        {Object.entries(costs.by_agent)
                          .sort((a, b) => b[1] - a[1])
                          .slice(0, 6)
                          .map(([agent, cost], i) => {
                            const pct = (cost / costs.total_cost_usd) * 100;
                            return (
                              <div key={agent} className="group">
                                <div className="flex justify-between items-center mb-1">
                                  <span className="text-xs font-mono text-[var(--text-secondary)] truncate max-w-[60%]">{agent}</span>
                                  <span className="text-xs font-mono text-[var(--text-primary)]">${cost.toFixed(2)}</span>
                                </div>
                                <div className="h-2 bg-[var(--bg-hover)] rounded-full overflow-hidden">
                                  <div
                                    className="h-full rounded-full transition-all duration-500 group-hover:brightness-125"
                                    style={{
                                      width: `${pct}%`,
                                      backgroundColor: ['var(--accent)', 'var(--positive)', 'var(--warning)', 'var(--text-muted)'][i % 4]
                                    }}
                                  />
                                </div>
                              </div>
                            );
                          })}
                      </div>
                    </div>
                  )}
                </div>

                {/* Model Breakdown */}
                <Collapsible title="Cost by Model" defaultOpen>
                  <div className="space-y-3">
                    {Object.entries(costs.by_model || {}).sort((a, b) => b[1] - a[1]).map(([model, cost]) => (
                      <CostBar key={model} label={model.split('-').slice(0, 2).join('-')} value={cost} total={costs.total_cost_usd} />
                    ))}
                  </div>
                </Collapsible>

                {/* Call Log */}
                <Collapsible title="Detailed Call Log">
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono">
                      <thead>
                        <tr className="border-b-2 border-[var(--border-default)]">
                          <th className="text-left p-3 text-[var(--text-muted)]">Phase</th>
                          <th className="text-left p-3 text-[var(--text-muted)]">Model</th>
                          <th className="text-right p-3 text-[var(--text-muted)]">Input</th>
                          <th className="text-right p-3 text-[var(--text-muted)]">Output</th>
                          <th className="text-right p-3 text-[var(--text-muted)]">Cost</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(costs.records || []).slice(0, 20).map((r, i) => (
                          <tr key={i} className="border-b border-[var(--border-subtle)] hover:bg-[var(--bg-elevated)] transition-colors">
                            <td className="p-3 text-[var(--text-secondary)]">{r.phase}</td>
                            <td className="p-3 text-[var(--accent)]">{r.model.split('-').slice(0, 2).join('-')}</td>
                            <td className="p-3 text-right text-[var(--text-muted)]">{formatCompact(r.input_tokens)}</td>
                            <td className="p-3 text-right text-[var(--text-muted)]">{formatCompact(r.output_tokens)}</td>
                            <td className="p-3 text-right font-semibold text-[var(--text-primary)]">${r.cost_usd.toFixed(3)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {(costs.records || []).length > 20 && (
                      <div className="p-3 text-center text-xs text-[var(--text-ghost)]">
                        Showing 20 of {costs.records.length} calls
                      </div>
                    )}
                  </div>
                </Collapsible>
              </div>
            )}

            {reportTab === 'costs' && !costs && (
              <p className="text-[var(--text-ghost)]">No cost data available</p>
            )}
          </div>
        </main>
      </div>
    );
  }

  return null;
}
