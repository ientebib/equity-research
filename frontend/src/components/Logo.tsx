'use client';

import { motion } from 'framer-motion';

export function Logo({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const sizes = {
    sm: { text: 'text-lg', icon: 20 },
    md: { text: 'text-2xl', icon: 28 },
    lg: { text: 'text-4xl', icon: 40 },
  };

  const { text, icon } = sizes[size];

  return (
    <div className="flex items-center gap-3">
      {/* K+ Symbol */}
      <div className="relative" style={{ width: icon, height: icon }}>
        <svg
          viewBox="0 0 40 40"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="w-full h-full"
        >
          {/* Outer ring */}
          <circle
            cx="20"
            cy="20"
            r="18"
            stroke="url(#logo-gradient)"
            strokeWidth="2"
            fill="none"
          />
          {/* K+ mark */}
          <path
            d="M14 12V28M14 20L22 12M14 20L22 28"
            stroke="url(#logo-gradient)"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M26 16V24M22 20H30"
            stroke="url(#logo-gradient)"
            strokeWidth="2"
            strokeLinecap="round"
          />
          <defs>
            <linearGradient id="logo-gradient" x1="0" y1="0" x2="40" y2="40">
              <stop offset="0%" stopColor="#3ddc97" />
              <stop offset="100%" stopColor="#5bc0eb" />
            </linearGradient>
          </defs>
        </svg>
        {/* Subtle glow */}
        <div
          className="absolute inset-0 blur-md opacity-30"
          style={{
            background: 'linear-gradient(135deg, #3ddc97 0%, #5bc0eb 100%)',
            borderRadius: '50%',
          }}
        />
      </div>

      {/* Text */}
      <div className="flex flex-col">
        <span className={`kp-display kp-logo-mark ${text}`}>K+ RESEARCH</span>
        <span className="kp-label text-[0.6rem] tracking-[0.2em] opacity-60">
          EQUITY INTELLIGENCE
        </span>
      </div>
    </div>
  );
}

export function LogoMark({ className = '' }: { className?: string }) {
  return (
    <motion.div
      className={`relative ${className}`}
      whileHover={{ scale: 1.05 }}
      transition={{ type: 'spring', stiffness: 400 }}
    >
      <svg
        viewBox="0 0 40 40"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full"
      >
        <circle
          cx="20"
          cy="20"
          r="18"
          stroke="url(#mark-gradient)"
          strokeWidth="2"
          fill="none"
        />
        <path
          d="M14 12V28M14 20L22 12M14 20L22 28"
          stroke="url(#mark-gradient)"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M26 16V24M22 20H30"
          stroke="url(#mark-gradient)"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <defs>
          <linearGradient id="mark-gradient" x1="0" y1="0" x2="40" y2="40">
            <stop offset="0%" stopColor="#3ddc97" />
            <stop offset="100%" stopColor="#5bc0eb" />
          </linearGradient>
        </defs>
      </svg>
    </motion.div>
  );
}
