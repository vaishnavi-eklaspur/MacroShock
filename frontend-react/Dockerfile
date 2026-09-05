# Build the React/TS app, then serve the static bundle with nginx.
FROM node:26-alpine@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3 AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# API base is baked at build time (Vite import.meta.env). Override per environment.
# NOTE: never pass a secret here -- anything Vite can read is compiled into the public bundle.
ARG VITE_API_BASE=http://localhost:5000
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# nginx-unprivileged: the stock nginx image runs its master process as root. This variant runs
# entirely as a non-root user (uid 101) and listens on 8080, since binding :80 requires
# privilege. Nothing here needs root, so it doesn't get it.
FROM nginxinc/nginx-unprivileged:alpine@sha256:aa8c9087d36d93e9d650c5365f883b421e8214aedbad24ade52b844c583358f1
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
