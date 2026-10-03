# --- Build stage ---------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app

# Allow overriding the Rasa REST webhook URL at build time.
ARG VITE_RASA_URL=http://localhost:5005
ENV VITE_RASA_URL=${VITE_RASA_URL}

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

# --- Runtime stage ---------------------------------------------------------
FROM nginx:alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
