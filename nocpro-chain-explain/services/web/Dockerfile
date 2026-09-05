FROM node:24-alpine AS build
WORKDIR /app
ARG VITE_NOCPRO_MOCK_URL
ENV VITE_NOCPRO_MOCK_URL=${VITE_NOCPRO_MOCK_URL}
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
