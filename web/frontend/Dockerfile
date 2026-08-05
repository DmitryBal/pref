FROM node:22

WORKDIR /frontend

COPY web/frontend/package*.json ./

RUN npm install

COPY web/frontend .

EXPOSE 5173

CMD ["npm","run","dev","--","--host"]