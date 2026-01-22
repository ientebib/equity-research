'use client';

import { useEffect, useState, useRef } from 'react';
import { motion } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Download, Share2, TrendingUp, TrendingDown, Minus, Loader2 } from 'lucide-react';
import { cn, formatPercentage } from '@/lib/utils';
import api from '@/lib/api';

interface ReportViewerProps {
  runId: string;
  className?: string;
}

interface ReportData {
  report: string;
  manifest?: {
    ticker: string;
    final_verdict?: {
      investment_view: string;
      conviction: string;
      confidence: number;
    };
    total_cost_usd?: number;
    duration_seconds?: number;
  };
}

const verdictConfig = {
  BUY: { icon: TrendingUp, color: 'kp-verdict-buy', label: 'BUY' },
  SELL: { icon: TrendingDown, color: 'kp-verdict-sell', label: 'SELL' },
  HOLD: { icon: Minus, color: 'kp-verdict-hold', label: 'HOLD' },
};

export function ReportViewer({ runId, className }: ReportViewerProps) {
  const [data, setData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toc, setToc] = useState<{ id: string; text: string; level: number }[]>([]);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fetchReport = async () => {
      setLoading(true);
      setError(null);

      try {
        const runData = await api.getRun(runId);
        const reportData = await api.getReport(runId);

        setData({
          report: reportData.report,
          manifest: runData.manifest || runData,
        });

        // Extract TOC from headings
        const headings: { id: string; text: string; level: number }[] = [];
        const lines = reportData.report.split('\n');
        lines.forEach((line, idx) => {
          const match = line.match(/^(#{1,3})\s+(.+)$/);
          if (match) {
            const level = match[1].length;
            const text = match[2];
            const id = `heading-${idx}`;
            headings.push({ id, text, level });
          }
        });
        setToc(headings);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load report');
      } finally {
        setLoading(false);
      }
    };

    fetchReport();
  }, [runId]);

  const scrollToHeading = (id: string) => {
    const element = document.getElementById(id);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  if (loading) {
    return (
      <div className={cn('flex items-center justify-center h-full', className)}>
        <Loader2 className="w-8 h-8 animate-spin text-[var(--kp-text-muted)]" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className={cn('flex items-center justify-center h-full text-[var(--kp-red)]', className)}>
        {error || 'Report not found'}
      </div>
    );
  }

  const verdict = data.manifest?.final_verdict;
  const VerdictConfig = verdict ? verdictConfig[verdict.investment_view as keyof typeof verdictConfig] : null;

  return (
    <div className={cn('flex h-full', className)}>
      {/* Table of Contents sidebar */}
      <div className="w-64 flex-shrink-0 border-r border-[var(--kp-border)] overflow-y-auto hidden lg:block">
        <div className="p-4">
          <h4 className="kp-label mb-3">Contents</h4>
          <nav className="space-y-1">
            {toc.map((item, idx) => (
              <button
                key={idx}
                onClick={() => scrollToHeading(item.id)}
                className={cn(
                  'block w-full text-left text-sm py-1.5 px-2 rounded transition-colors',
                  'text-[var(--kp-text-muted)] hover:text-[var(--kp-text)] hover:bg-[var(--kp-elevated)]',
                  item.level === 1 && 'font-medium text-[var(--kp-text-secondary)]',
                  item.level === 2 && 'pl-4',
                  item.level === 3 && 'pl-6 text-xs'
                )}
              >
                {item.text}
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* Main report content */}
      <div className="flex-1 overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 z-10 bg-[var(--kp-surface)] border-b border-[var(--kp-border)]">
          <div className="p-4 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <span className="kp-ticker text-lg">{data.manifest?.ticker}</span>

              {VerdictConfig && (
                <div className={cn('kp-verdict', VerdictConfig.color)}>
                  <VerdictConfig.icon className="w-4 h-4" />
                  {VerdictConfig.label}
                </div>
              )}

              {verdict && (
                <>
                  <div className="text-sm">
                    <span className="kp-label mr-2">Conviction</span>
                    <span className="text-[var(--kp-text)]">{verdict.conviction}</span>
                  </div>
                  <div className="text-sm">
                    <span className="kp-label mr-2">Confidence</span>
                    <span className="text-[var(--kp-text)]">{formatPercentage(verdict.confidence)}</span>
                  </div>
                </>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button className="kp-btn flex items-center gap-2">
                <Share2 className="w-4 h-4" />
                Share
              </button>
              <button className="kp-btn flex items-center gap-2">
                <Download className="w-4 h-4" />
                PDF
              </button>
            </div>
          </div>

          {/* Confidence bar */}
          {verdict && (
            <div className="px-4 pb-3">
              <div className="kp-confidence-bar">
                <div
                  className="kp-confidence-fill"
                  style={{ width: `${verdict.confidence * 100}%` }}
                />
              </div>
            </div>
          )}
        </div>

        {/* Report content */}
        <motion.div
          ref={contentRef}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-8 max-w-4xl mx-auto"
        >
          <article className="kp-report">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ children, ...props }) => {
                  const text = String(children);
                  const id = `heading-h1-${text.toLowerCase().replace(/\s+/g, '-')}`;
                  return <h1 id={id} {...props}>{children}</h1>;
                },
                h2: ({ children, ...props }) => {
                  const text = String(children);
                  const id = `heading-h2-${text.toLowerCase().replace(/\s+/g, '-')}`;
                  return <h2 id={id} {...props}>{children}</h2>;
                },
                h3: ({ children, ...props }) => {
                  const text = String(children);
                  const id = `heading-h3-${text.toLowerCase().replace(/\s+/g, '-')}`;
                  return <h3 id={id} {...props}>{children}</h3>;
                },
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--kp-cyan)] hover:underline"
                  >
                    {children}
                  </a>
                ),
              }}
            >
              {data.report}
            </ReactMarkdown>
          </article>
        </motion.div>
      </div>
    </div>
  );
}
