# TaskFlow Pro Frontend - Production Dockerfile
# Multi-stage build with optimized React build
# Node 20 + React + TypeScript + Vite

# =============================================================================
# STAGE 1: Dependencies
# =============================================================================
FROM node:20-alpine AS dependencies

# Install build dependencies
RUN apk add --no-cache libc6-compat

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./
COPY yarn.lock* ./
COPY pnpm-lock.yaml* ./

# Install dependencies based on lockfile
RUN if [ -f yarn.lock ]; then yarn install --frozen-lockfile; \
    elif [ -f package-lock.json ]; then npm ci; \
    elif [ -f pnpm-lock.yaml ]; then npm install -g pnpm && pnpm install --frozen-lockfile; \
    else npm install; \
    fi

# =============================================================================
# STAGE 2: Builder
# =============================================================================
FROM node:20-alpine AS builder

# Set working directory
WORKDIR /app

# Copy dependencies from dependencies stage
COPY --from=dependencies /app/node_modules ./node_modules

# Copy source code
COPY . .

# Build arguments for environment variables
ARG VITE_API_URL
ARG VITE_WS_URL
ARG VITE_APP_NAME

# Set environment variables for build
ENV VITE_API_URL=${VITE_API_URL} \
    VITE_WS_URL=${VITE_WS_URL} \
    VITE_APP_NAME=${VITE_APP_NAME}

# Build the application
RUN npm run build

# =============================================================================
# STAGE 3: Production (Nginx)
# =============================================================================
FROM nginx:1.25-alpine-slim AS production

# Security: Create non-root user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nextjs -u 1001

# Install security updates
RUN apk upgrade --no-cache

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/

# Copy built application from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Set proper permissions
RUN chown -R nextjs:nodejs /usr/share/nginx/html && \
    chown -R nextjs:nodejs /var/cache/nginx && \
    chown -R nextjs:nodejs /var/log/nginx && \
    chown -R nextjs:nodejs /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && \
    chown -R nextjs:nodejs /var/run/nginx.pid

# Remove unnecessary tools
RUN rm -rf /usr/share/nginx/html/*.map \
    /usr/share/nginx/html/vite.svg

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:80/health || exit 1

# Expose port
EXPOSE 80

# Switch to non-root user
USER nextjs

# Start Nginx
CMD ["nginx", "-g", "daemon off;"]
