# syntax=docker/dockerfile:1.7
# ==============================================================================
# Fvas web
#
# Vercel builds from source and ignores this file. It exists for local parity
# with the compose stack and for self-hosted deploys.
# ==============================================================================

FROM node:26-alpine AS base
WORKDIR /app
# Alpine's musl needs libc6-compat for some native Node addons.
RUN apk add --no-cache libc6-compat


# ── Dependencies ──────────────────────────────────────────────────────────────
FROM base AS deps
# Copy only manifests first so a source change does not invalidate the install.
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/
COPY packages/shared/package.json ./packages/shared/
RUN npm ci


# ── Development ───────────────────────────────────────────────────────────────
FROM deps AS development
ENV NEXT_TELEMETRY_DISABLED=1
EXPOSE 3000
CMD ["npm", "run", "dev", "--workspace=@fvas/web"]


# ── Build ─────────────────────────────────────────────────────────────────────
FROM deps AS builder
ENV NEXT_TELEMETRY_DISABLED=1
COPY . .
# NEXT_PUBLIC_* values are inlined into the client bundle at build time, so the
# API URL must be supplied here, not at runtime.
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_APP_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_APP_URL=$NEXT_PUBLIC_APP_URL
RUN npm run build --workspace=@fvas/web


# ── Production ────────────────────────────────────────────────────────────────
FROM base AS production
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# `output: "standalone"` emits a minimal server plus only the traced
# dependencies — a fraction of a full node_modules copy.
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/public ./apps/web/public

USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "apps/web/server.js"]
