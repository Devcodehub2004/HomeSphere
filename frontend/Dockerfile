FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:stable-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/homesphere.conf.template
COPY docker-entrypoint.sh /usr/local/bin/homesphere-web
RUN chmod 755 /usr/local/bin/homesphere-web
USER nginx
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/homesphere-web"]
