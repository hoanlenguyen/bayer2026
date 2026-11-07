# Frontend image: builds the React app, then serves it with Caddy.
# Caddy also forwards /api/* to the backend container and gets an HTTPS certificate on its own.
# Build context is frontend/ (see docker-compose.yml); the Caddyfile is mounted at run time.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2.10-alpine
COPY --from=build /app/dist /srv
