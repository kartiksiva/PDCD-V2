# syntax=docker/dockerfile:1.7

FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html postcss.config.js tailwind.config.js vite.config.js staticwebapp.config.json ./
COPY src ./src

ARG VITE_API_BASE=
ARG VITE_API_KEY=

ENV VITE_API_BASE=${VITE_API_BASE} \
    VITE_API_KEY=${VITE_API_KEY}

RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1/health || exit 1

