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
			{Code: "organizations", Name: "Organizaciones", Description: "Empresas, sedes, zonas, ambitos y estructura operativa.", ManagedBy: "go", Status: "planned"},
			{Code: "billing", Name: "Facturacion", Description: "Planes, suscripciones, licencias y asignaciones.", ManagedBy: "go", Status: "planned"},
			{Code: "catalog", Name: "Catalogo", Description: "Contenidos de audio, canciones IA, etiquetas, assets y procesamiento.", ManagedBy: "go", Status: "planned"},
			{Code: "playlists", Name: "Playlists y canales", Description: "Playlists, snapshots, canales y politicas musicales.", ManagedBy: "go", Status: "planned"},
			{Code: "scheduling", Name: "Programaciones", Description: "Horarios, excepciones y asignaciones por ambito.", ManagedBy: "go", Status: "planned"},
			{Code: "campaigns", Name: "Campanas", Description: "Mensajes corporativos, reglas y objetivos.", ManagedBy: "go", Status: "planned"},
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
				"administracion interna mediante Django Admin",
			},
		},
		{
			Service: "back_go",
			Responsibilities: []string{
				"gestion operativa multiempresa",
				"dispositivos",
				"programaciones",
				"catalogo y playlists",
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
