"use client";

import * as React from "react";
import { motion, useReducedMotion } from "motion/react";

/**
 * Scroll-into-view reveal: fade plus a 16px rise, 400ms ease-out, fired once
 * (docs/04-design-system.md §7).
 *
 * `useReducedMotion` is checked in JS rather than relying on the global CSS
 * media query, because Motion drives these values through inline styles the
 * stylesheet cannot reach. Under reduced motion the content renders in its
 * final state immediately — visible, never animated in.
 */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduced = useReducedMotion();

  if (reduced) return <div className={className}>{children}</div>;

  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.4, ease: "easeOut", delay }}
    >
      {children}
    </motion.div>
  );
}

/**
 * Reveals children in sequence with a 60ms stagger.
 *
 * Stagger communicates that items belong to one group. Beyond ~6 items the
 * last one arrives late enough to feel broken, so callers should cap the count.
 */
export function RevealGroup({
  children,
  className,
  stagger = 0.06,
}: {
  children: React.ReactNode;
  className?: string;
  stagger?: number;
}) {
  const reduced = useReducedMotion();
  const items = React.Children.toArray(children);

  if (reduced) return <div className={className}>{children}</div>;

  return (
    <div className={className}>
      {items.map((child, index) => (
        <motion.div
          key={index}
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.4, ease: "easeOut", delay: index * stagger }}
        >
          {child}
        </motion.div>
      ))}
    </div>
  );
}
