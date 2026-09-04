package operations

import "fmt"

type Boundary struct {
	Service          string   `json:"service"`
	Responsibilities []string `json:"responsibilities"`
}

type Module struct {
	Code        string `json:"code"`
	Name        string `json:"name"`
	Description string `json:"description"`
	ManagedBy   string `json:"managed_by"`
	Status      string `json:"status"`
}

type Service struct {
	modules []Module
}

func NewService() Service {
	return Service{
		modules: []Module{
			{Code: "organizations", Name: "Organizaciones", Description: "Empresas, sedes, zonas, ambitos y estructura operativa.", ManagedBy: "django", Status: "ready"},
			{Code: "billing", Name: "Facturacion", Description: "Planes, suscripciones, licencias y asignaciones.", ManagedBy: "django", Status: "planned"},
			{Code: "catalog", Name: "Catalogo", Description: "Contenidos de audio, canciones IA, etiquetas, assets y procesamiento.", ManagedBy: "django", Status: "ready"},
			{Code: "playlists", Name: "Playlists y canales", Description: "Playlists, snapshots y canales. Canales operativos quedan para fases posteriores.", ManagedBy: "django", Status: "partial"},
			{Code: "scheduling", Name: "Programaciones", Description: "Configuracion persistente de horarios, excepciones y asignaciones por ambito.", ManagedBy: "django", Status: "ready"},
			{Code: "campaigns", Name: "Campanas", Description: "Mensajes corporativos, reglas y objetivos.", ManagedBy: "django", Status: "planned"},
			{Code: "devices", Name: "Dispositivos", Description: "Provisioning, credenciales, estado y sincronizacion.", ManagedBy: "go", Status: "planned"},
			{Code: "playback", Name: "Reproduccion", Description: "Comandos, manifiestos, sesiones y eventos de reproduccion.", ManagedBy: "go", Status: "ready"},
		},
	}
}

func (s Service) Boundaries() []Boundary {
	return []Boundary{
		{
			Service: "back_django",
			Responsibilities: []string{
				"autenticacion",
				"usuarios",
				"roles y permisos",
				"empresas, sedes, zonas y ambitos",
				"catalogo, playlists y programacion persistente",
				"administracion interna mediante Django Admin",
			},
		},
		{
			Service: "back_go",
			Responsibilities: []string{
				"dispositivos",
				"resolucion operativa de programacion publicada",
				"motor de reproduccion",
			},
		},
	}
}

func (s Service) Modules() []Module {
	return append([]Module(nil), s.modules...)
}

func (s Service) ModuleStatus(code string) (Module, error) {
	for _, module := range s.modules {
		if module.Code == code {
			return module, nil
		}
	}
	return Module{}, fmt.Errorf("module %q not found", code)
}
