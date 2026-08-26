"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { Toaster } from "sonner";

import { ThemeProvider } from "@/components/theme-provider";
import { ApiError, setSessionExpiredHandler } from "@/lib/api-client";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Long enough that navigating back to a page does not refetch, short
        // enough that stale data does not mislead an operator.
        staleTime: 30_000,
        retry: (failureCount, error) => {
          // Never retry a 4xx — it will fail identically every time, and
          // retrying a 401 fights the silent-refresh logic in api-client.
          if (error instanceof ApiError && !error.isRetryable) return false;
          return failureCount < 2;
        },
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}

export function Providers({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  // useState, not a module-level client: a module singleton would be shared
  // across requests on the server and leak one user's cache into another's.
  const [queryClient] = React.useState(makeQueryClient);

  React.useEffect(() => {
    setSessionExpiredHandler(() => {
      queryClient.clear();
      // Preserve where they were so login can send them back.
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      router.replace(`/login?next=${next}&reason=expired`);
    });
    return () => setSessionExpiredHandler(null);
  }, [queryClient, router]);

  return (
    // NuqsAdapter is required by nuqs v2 — `useQueryState` throws without it.
    // Console list pages keep their filters in the URL so a view is shareable
    // and the back button behaves, and every one of them depends on this.
    <NuqsAdapter>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          {children}
          <Toaster
            position="bottom-right"
            // Errors persist until dismissed; successes clear themselves. An
            // error the user never saw is an error that gets reported as a bug.
            toastOptions={{ duration: 4000 }}
            closeButton
            richColors
          />
        </ThemeProvider>
      </QueryClientProvider>
    </NuqsAdapter>
  );
}
