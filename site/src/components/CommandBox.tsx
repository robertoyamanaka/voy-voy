"use client";

import { useState } from "react";

export function CommandBox({ command, className = "" }: { command: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {}
  };
  return (
    <div className={`command ${className}`}>
      <code>{command}</code>
      <button type="button" className="icon-btn" onClick={copy} aria-label={copied ? "Copied" : `Copy ${command}`}>
        {copied ? (
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M3 8.5l3 3 7-7" fill="none" stroke="currentColor" strokeWidth="1.75" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <rect x="5.25" y="5.25" width="8" height="8" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M10.75 3V2.75h-8v8H3" fill="none" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        )}
      </button>
      <span className="sr-only" aria-live="polite">
        {copied ? "Copied to clipboard" : ""}
      </span>
    </div>
  );
}
