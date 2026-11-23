FROM golang:1.22-alpine AS build
WORKDIR /src
COPY . .
RUN go build -o /voucher-api ./cmd/server

FROM alpine:3.20
COPY --from=build /voucher-api /voucher-api
ENV DATA_DIR=/data
VOLUME /data
EXPOSE 8080
HEALTHCHECK CMD wget -qO- http://localhost:8080/healthz || exit 1
ENTRYPOINT ["/voucher-api"]
