"use client";

import * as React from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export interface CodeTabItem {
  value: string;
  label: string;
  content: React.ReactNode;
}

/**
 * Language switcher over pre-highlighted code blocks.
 *
 * `content` is rendered on the server (Shiki) and passed down as children, so
 * this client component carries only the tab interaction — not a highlighter.
 */
export function CodeTabs({ items }: { items: CodeTabItem[] }) {
  const first = items[0];
  if (!first) return null;

  return (
    <Tabs defaultValue={first.value}>
      <TabsList>
        {items.map((item) => (
          <TabsTrigger key={item.value} value={item.value}>
            {item.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {items.map((item) => (
        <TabsContent key={item.value} value={item.value} className="mt-3">
          {item.content}
        </TabsContent>
      ))}
    </Tabs>
  );
}
