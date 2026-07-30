FROM golang:1.23-alpine AS builder

WORKDIR /src

COPY go.mod ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/brandymanager-go ./cmd/server

FROM alpine:3.20

RUN adduser -D -H appuser
USER appuser

COPY --from=builder /bin/brandymanager-go /app/brandymanager-go

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1:8080/health >/dev/null || exit 1

CMD ["/app/brandymanager-go"]
