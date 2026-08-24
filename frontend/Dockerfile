FROM node:20-alpine AS build

WORKDIR /app

# Dependency layer first: `npm ci` is only re-run when the lockfile changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:alpine

# Serves the built SPA and proxies /api and /admin to the backend container,
# so the whole app is reachable under a single origin (no CORS, no proxy.conf).
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html
