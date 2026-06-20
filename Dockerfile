FROM node:22-slim AS build

WORKDIR /app/typescript

COPY typescript/package*.json ./
RUN npm ci

COPY typescript/tsconfig.json ./tsconfig.json
COPY typescript/src ./src
RUN npm run build

FROM node:22-slim AS runtime

ENV NODE_ENV=production
WORKDIR /app

COPY typescript/package*.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=build /app/typescript/dist ./dist
COPY LICENSE README.md ./

USER node

CMD ["node", "dist/index.js"]
