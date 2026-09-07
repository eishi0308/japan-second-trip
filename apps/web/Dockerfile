# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS deps
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000
RUN addgroup -g 10001 -S jst && adduser -S -u 10001 -G jst jst

# next.config.mjs pins outputFileTracingRoot to the web app directory, so the
# standalone bundle has the same shape here as it does locally: server.js at the
# root, with .next/static and public alongside it.
COPY --from=builder --chown=jst:jst /app/.next/standalone ./
COPY --from=builder --chown=jst:jst /app/.next/static ./.next/static
COPY --from=builder --chown=jst:jst /app/public ./public

USER jst
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/',r=>process.exit(r.statusCode<500?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "server.js"]
