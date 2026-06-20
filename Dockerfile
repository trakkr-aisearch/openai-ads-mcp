FROM node:22-slim AS build

WORKDIR /app/typescript

COPY typescript/package*.json ./
RUN npm ci

COPY typescript/tsconfig.json ./tsconfig.json
COPY typescript/src ./src
RUN npm run build

FROM node:22-slim AS runtime

ENV NODE_ENV=production
ENV OPENAI_ADS_MCP_TRANSPORT=http
ENV OPENAI_ADS_MCP_HOSTED_PUBLIC=1
WORKDIR /app

COPY typescript/package*.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=build /app/typescript/dist ./dist
COPY LICENSE README.md ./

USER node

EXPOSE 8080
CMD ["node", "dist/index.js", "--http"]
