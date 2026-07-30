package main

import (
	"log"
	"net/http"

	"brandymanager/back_go/internal/api"
	"brandymanager/back_go/internal/config"
)

func main() {
	cfg := config.Load()

	server := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           api.NewRouter(cfg),
		ReadHeaderTimeout: cfg.ReadHeaderTimeout,
	}

	log.Printf("%s listening on :%s", cfg.ServiceName, cfg.Port)
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}
