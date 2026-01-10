# syntax=docker/dockerfile:1

# Build stage
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies (cached layer)
COPY package*.json ./
RUN npm ci

# Copy source code
COPY . .

# Build arguments (passed at build time)
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

ARG VITE_DEPLOYMENT_MODE=self-hosted
ENV VITE_DEPLOYMENT_MODE=$VITE_DEPLOYMENT_MODE

ARG VITE_ENABLE_GOOGLE_AUTH=true
ENV VITE_ENABLE_GOOGLE_AUTH=$VITE_ENABLE_GOOGLE_AUTH

ARG VITE_ROLE_OPTIONS="Product,Engineering,Design,Data,Ops,Other"
ENV VITE_ROLE_OPTIONS=$VITE_ROLE_OPTIONS

# Build the application
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy built assets from build stage
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost/ || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
