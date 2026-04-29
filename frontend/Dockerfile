# CI Engine - Frontend Dockerfile
FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Production server
FROM node:20-alpine
WORKDIR /app

# Install serve for static file serving
RUN npm install -g serve

COPY --from=builder /app/dist ./dist
COPY run.sh ./

EXPOSE 3000
CMD ["sh", "run.sh"]