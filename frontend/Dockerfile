# Frontend image: build the Vite app, then serve it with nginx.
# nginx also forwards /api to the backend, so the browser talks to one origin.
#   docker compose up --build   (from the repository root)
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
