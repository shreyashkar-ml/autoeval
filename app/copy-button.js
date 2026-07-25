"use client";

import { useState } from "react";

export default function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }

  return (
    <button className="copy" onClick={copy} aria-label="Copy install command">
      {copied ? "copied" : "copy"}
    </button>
  );
}
