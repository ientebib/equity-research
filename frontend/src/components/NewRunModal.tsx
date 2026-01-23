'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Play, AlertCircle, DollarSign, Calendar, Zap, Search } from 'lucide-react';
import { cn } from '@/lib/utils';

interface NewRunModalProps {
  isOpen: boolean;
  onClose: () => void;
  onStart: (ticker: string, budget: number, options: RunOptions) => Promise<void>;
}

interface RunOptions {
  quarters: number;
  useDualDiscovery: boolean;
  useDeepResearch: boolean;
}

export function NewRunModal({ isOpen, onClose, onStart }: NewRunModalProps) {
  const [ticker, setTicker] = useState('');
  const [budget, setBudget] = useState(50);
  const [quarters, setQuarters] = useState(4);
  const [useDualDiscovery, setUseDualDiscovery] = useState(true);
  const [useDeepResearch, setUseDeepResearch] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!ticker.trim()) {
      setError('Please enter a ticker symbol');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await onStart(ticker.toUpperCase(), budget, {
        quarters,
        useDualDiscovery,
        useDeepResearch,
      });
      // Reset form
      setTicker('');
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start analysis');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-lg"
          >
            <div className="kp-panel m-4">
              {/* Header */}
              <div className="kp-panel-header flex items-center justify-between">
                <h2 className="kp-display text-lg">New Analysis</h2>
                <button
                  onClick={onClose}
                  className="p-1.5 rounded hover:bg-[var(--kp-border)] transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Form */}
              <form onSubmit={handleSubmit} className="p-6 space-y-6">
                {/* Ticker input */}
                <div>
                  <label className="kp-label block mb-2">Ticker Symbol</label>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-[var(--kp-text-muted)]" />
                    <input
                      type="text"
                      value={ticker}
                      onChange={(e) => setTicker(e.target.value.toUpperCase())}
                      placeholder="AAPL, GOOGL, MSFT..."
                      className="kp-input w-full pl-10 text-xl font-semibold tracking-wider"
                      maxLength={5}
                      autoFocus
                    />
                  </div>
                </div>

                {/* Budget slider */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="kp-label flex items-center gap-2">
                      <DollarSign className="w-3.5 h-3.5" />
                      Budget
                    </label>
                    <span className="kp-mono text-[var(--kp-green)]">${budget}</span>
                  </div>
                  <input
                    type="range"
                    min={10}
                    max={100}
                    step={5}
                    value={budget}
                    onChange={(e) => setBudget(Number(e.target.value))}
                    className="w-full accent-[var(--kp-green)]"
                  />
                  <div className="flex justify-between text-xs text-[var(--kp-text-muted)] mt-1">
                    <span>$10 (quick)</span>
                    <span>$100 (thorough)</span>
                  </div>
                </div>

                {/* Quarters selector */}
                <div>
                  <label className="kp-label flex items-center gap-2 mb-2">
                    <Calendar className="w-3.5 h-3.5" />
                    Transcript Quarters
                  </label>
                  <div className="flex gap-2">
                    {[2, 4, 6, 8].map((q) => (
                      <button
                        key={q}
                        type="button"
                        onClick={() => setQuarters(q)}
                        className={cn(
                          'flex-1 py-2 rounded border transition-colors',
                          quarters === q
                            ? 'bg-[var(--kp-green)] border-[var(--kp-green)] text-[var(--kp-void)]'
                            : 'border-[var(--kp-border)] hover:border-[var(--kp-text-muted)]'
                        )}
                      >
                        {q}Q
                      </button>
                    ))}
                  </div>
                </div>

                {/* Options */}
                <div className="space-y-3">
                  <label className="kp-label flex items-center gap-2">
                    <Zap className="w-3.5 h-3.5" />
                    Research Options
                  </label>

                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={useDualDiscovery}
                      onChange={(e) => setUseDualDiscovery(e.target.checked)}
                      className="w-4 h-4 rounded border-[var(--kp-border)] accent-[var(--kp-green)]"
                    />
                    <div>
                      <span className="text-sm">Dual Discovery</span>
                      <p className="text-xs text-[var(--kp-text-muted)]">
                        Run internal + external discovery in parallel
                      </p>
                    </div>
                  </label>

                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={useDeepResearch}
                      onChange={(e) => setUseDeepResearch(e.target.checked)}
                      className="w-4 h-4 rounded border-[var(--kp-border)] accent-[var(--kp-green)]"
                    />
                    <div>
                      <span className="text-sm">Deep Research</span>
                      <p className="text-xs text-[var(--kp-text-muted)]">
                        Use Claude subagents for deep vertical research
                      </p>
                    </div>
                  </label>
                </div>

                {/* Error */}
                {error && (
                  <div className="flex items-center gap-2 text-[var(--kp-red)] text-sm">
                    <AlertCircle className="w-4 h-4" />
                    {error}
                  </div>
                )}

                {/* Submit */}
                <button
                  type="submit"
                  disabled={isSubmitting || !ticker.trim()}
                  className={cn(
                    'kp-btn kp-btn-primary w-full flex items-center justify-center gap-2 text-base py-3',
                    (isSubmitting || !ticker.trim()) && 'opacity-50 cursor-not-allowed'
                  )}
                >
                  <Play className="w-5 h-5" />
                  {isSubmitting ? 'Starting...' : 'Start Analysis'}
                </button>
              </form>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
