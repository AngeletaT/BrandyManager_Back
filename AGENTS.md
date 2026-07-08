# Django Modular API Architecture Skill

## Objetivo

Este repositorio debe mantenerse como una **API Django modular**, preparada para crecer por dominios funcionales y facilitar una futura separación en servicios independientes si el producto lo requiere.

La arquitectura debe priorizar:

* Separación clara por dominios funcionales.
* Bajo acoplamiento entre módulos.
* Casos de uso explícitos.
* Endpoints delgados.
* Validaciones centralizadas.
* Modelos persistentes claros.
* Código fácil de testear.
* Estructura mantenible para equipos pequeños.

No se debe construir una arquitectura innecesariamente compleja al inicio. El objetivo es un **monolito modular bien separado**, no múltiples servicios independientes.

---

## Estructura base del proyecto

La estructura recomendada del backend es:

```txt
backend/
  manage.py

  config/
    __init__.py
    settings/
      __init__.py
      base.py
      local.py
      production.py
      test.py
    urls.py
    asgi.py
    wsgi.py

  apps/
    users/
      __init__.py
      admin.py
      apps.py
      models.py
      serializers.py
      views.py
      urls.py
      services.py
      selectors.py
      permissions.py
      exceptions.py
      tests/
        __init__.py
        test_models.py
        test_services.py
        test_api.py
      migrations/
        __init__.py

    companies/
      __init__.py
      admin.py
      apps.py
      models.py
      serializers.py
      views.py
      urls.py
      services.py
      selectors.py
      permissions.py
      exceptions.py
      tests/
      migrations/

    example_domain/
      __init__.py
      admin.py
      apps.py
      models.py
      serializers.py
      views.py
      urls.py
      services.py
      selectors.py
      permissions.py
      exceptions.py
      tests/
      migrations/

  shared/
    __init__.py
    api/
      __init__.py
      pagination.py
      responses.py
      exceptions.py
      error_codes.py
    auth/
      __init__.py
      jwt.py
      permissions.py
    db/
      __init__.py
      models.py
    utils/
      __init__.py
      dates.py
      strings.py

  requirements/
    base.txt
    local.txt
    production.txt
    test.txt

  pytest.ini
  README.md
```

---

## Conceptos principales

### Project

El directorio `config/` representa la configuración global del backend.

Debe contener:

* Settings.
* URLs raíz.
* ASGI/WSGI.
* Configuración global de Django.
* Configuración global de Django REST Framework.
* Registro de rutas principales.

No debe contener lógica de negocio.

---

### App

Cada carpeta dentro de `apps/` representa un **dominio funcional**.

Ejemplos:

```txt
apps/users/
apps/companies/
apps/billing/
apps/orders/
apps/notifications/
apps/reports/
```

Una app debe tener una responsabilidad clara. No debe convertirse en una carpeta genérica donde cabe todo.

Correcto:

```txt
apps/companies/
apps/company_members/
apps/invitations/
```

Aceptable si el dominio es pequeño:

```txt
apps/companies/
```

Incorrecto:

```txt
apps/core/
apps/misc/
apps/general/
apps/common_business/
```

---

## Regla de oro

La API debe seguir este flujo:

```txt
HTTP Request
  ↓
urls.py
  ↓
views.py
  ↓
serializers.py
  ↓
services.py / selectors.py
  ↓
models.py
  ↓
Database
```

Las vistas no deben contener lógica de negocio compleja.

Los serializers no deben ejecutar procesos de negocio importantes.

Los modelos no deben conocer detalles de la API.

Los servicios deben concentrar las acciones que modifican el estado del sistema.

Los selectors deben concentrar las consultas de lectura.

---

## Responsabilidad de cada archivo

### models.py

Contiene modelos persistentes de Django.

Debe usarse para:

* Definir tablas.
* Definir relaciones.
* Definir constraints.
* Definir propiedades simples.
* Definir métodos pequeños estrictamente ligados al modelo.

Puede contener:

```python
class Company(models.Model):
    name = models.CharField(max_length=255)
    tax_id = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

No debe contener:

* Lógica compleja de casos de uso.
* Envío de emails.
* Llamadas HTTP externas.
* Procesos de negocio largos.
* Decisiones de permisos de API.
* Construcción de respuestas JSON.

---

### serializers.py

Contiene serializers de entrada y salida para la API.

Debe usarse para:

* Validar datos de entrada.
* Definir campos expuestos por la API.
* Transformar modelos o datos en respuestas JSON.
* Separar serializers de lectura y escritura cuando sea necesario.

Convención recomendada:

```python
class CompanyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    tax_id = serializers.CharField(max_length=50)


class CompanyDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "name", "tax_id", "is_active", "created_at"]
```

Reglas:

* Los serializers de entrada deben llamarse `SomethingCreateSerializer`, `SomethingUpdateSerializer`, etc.
* Los serializers de salida deben llamarse `SomethingDetailSerializer`, `SomethingListSerializer`, etc.
* No meter lógica de negocio compleja en `validate`.
* No llamar directamente a servicios externos desde un serializer.
* No usar un único serializer gigante para todos los casos.

---

### views.py

Contiene endpoints de la API.

Debe usarse para:

* Recibir la request.
* Instanciar serializers.
* Validar entrada.
* Llamar a services o selectors.
* Devolver respuestas.
* Aplicar permisos.
* Aplicar filtros simples.
* Aplicar paginación.

Una vista debe ser fina.

Ejemplo recomendado:

```python
class CompanyViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def create(self, request):
        serializer = CompanyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        company = create_company(
            user=request.user,
            data=serializer.validated_data,
        )

        output = CompanyDetailSerializer(company)
        return Response(output.data, status=status.HTTP_201_CREATED)
```

Evitar esto:

```python
class CompanyViewSet(viewsets.ViewSet):
    def create(self, request):
        # Validaciones largas
        # Queries complejas
        # Creación de múltiples modelos
        # Envío de emails
        # Lógica de permisos manual
        # Respuesta construida a mano
```

---

### services.py

Contiene casos de uso que modifican estado.

Debe usarse para acciones como:

* Crear registros.
* Actualizar entidades.
* Cambiar estados.
* Ejecutar procesos de negocio.
* Coordinar varias entidades.
* Lanzar eventos internos.
* Ejecutar acciones transaccionales.

Ejemplos:

```python
def create_company(*, user, data):
    if not user.has_perm("companies.create_company"):
        raise PermissionDenied("User cannot create companies")

    company = Company.objects.create(
        name=data["name"],
        tax_id=data["tax_id"],
    )

    return company
```

Reglas:

* Los services deben recibir datos ya validados.
* Los services no deben depender de `request`.
* Los services no deben devolver `Response`.
* Los services no deben importar serializers.
* Los services pueden usar transacciones.
* Los services pueden llamar a otros services si pertenece al mismo flujo de negocio.
* Evitar services genéricos tipo `utils_service.py`.

---

### selectors.py

Contiene consultas de lectura.

Debe usarse para:

* Listados.
* Filtros.
* Búsquedas.
* Detalles.
* Queries optimizadas.
* Prefetch/select_related.
* QuerySets reutilizables.

Ejemplo:

```python
def get_company_by_id(*, company_id):
    return Company.objects.get(id=company_id)


def list_companies_for_user(*, user):
    return Company.objects.filter(memberships__user=user).distinct()
```

Reglas:

* Los selectors no deben modificar datos.
* Los selectors no deben crear registros.
* Los selectors no deben enviar emails.
* Los selectors pueden devolver QuerySets.
* Los selectors deben concentrar queries que se reutilizan en varias vistas o servicios.

---

### permissions.py

Contiene permisos específicos de la app.

Debe usarse para:

* Permisos de acceso a endpoints.
* Reglas simples de autorización.
* Permisos reutilizables dentro del dominio.

Ejemplo:

```python
class IsCompanyAdmin(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.memberships.filter(
            user=request.user,
            role="admin",
        ).exists()
```

Reglas:

* Los permisos de API viven en `permissions.py`.
* Las reglas de negocio complejas no deben esconderse dentro de permisos.
* Si una acción requiere validaciones de negocio importantes, deben ir en `services.py`.

---

### exceptions.py

Contiene excepciones propias del dominio.

Ejemplo:

```python
class CompanyAlreadyExists(Exception):
    pass


class CompanyUserLimitExceeded(Exception):
    pass
```

Reglas:

* Usar excepciones de dominio cuando la causa sea de negocio.
* No lanzar strings genéricos.
* No mezclar excepciones técnicas con excepciones de negocio.
* Convertir excepciones a respuestas API en una capa compartida cuando sea necesario.

---

### urls.py

Cada app debe exponer sus propias rutas.

Ejemplo:

```python
router = DefaultRouter()
router.register(r"companies", CompanyViewSet, basename="companies")

urlpatterns = router.urls
```

El `config/urls.py` solo debe incluir las rutas principales:

```python
urlpatterns = [
    path("api/users/", include("apps.users.urls")),
    path("api/companies/", include("apps.companies.urls")),
]
```

---

## Reglas de dependencias entre apps

Una app no debe depender libremente de los detalles internos de otra app.

Permitido:

```python
from apps.companies.selectors import get_company_by_id
from apps.companies.services import add_user_to_company
```

Evitar:

```python
from apps.companies.models import Company
```

No siempre es posible evitar importar modelos de otra app, pero debe intentarse que la comunicación entre dominios pase por:

* `services.py`
* `selectors.py`
* funciones públicas explícitas
* eventos internos si el flujo crece

Regla práctica:

> Si otra app necesita hacer algo con este dominio, este dominio debe ofrecer una función clara para hacerlo.

---

## Convenciones de nombres

### Apps

Usar nombres en plural cuando representen recursos principales:

```txt
users
companies
orders
invoices
notifications
```

Usar nombres específicos cuando representen procesos:

```txt
auth_tokens
payment_attempts
email_verifications
```

Evitar nombres vagos:

```txt
core
common
base
general
misc
```

---

### Services

Nombrar funciones como acciones:

```python
create_company()
update_company()
deactivate_company()
invite_user_to_company()
accept_invitation()
cancel_subscription()
```

---

### Selectors

Nombrar funciones como lecturas:

```python
get_company_by_id()
list_companies_for_user()
find_active_subscription()
count_pending_invitations()
```

---

### Serializers

Usar nombres según caso de uso:

```python
CompanyCreateSerializer
CompanyUpdateSerializer
CompanyDetailSerializer
CompanyListSerializer
CompanyMemberSerializer
```

---

### ViewSets

Usar nombres de recurso:

```python
CompanyViewSet
CompanyMemberViewSet
InvitationViewSet
```

---

## Transacciones

Cuando un caso de uso modifique varias entidades, usar transacciones.

Ejemplo:

```python
from django.db import transaction

@transaction.atomic
def invite_user_to_company(*, company, email, role):
    invitation = Invitation.objects.create(
        company=company,
        email=email,
        role=role,
    )

    send_invitation_email(invitation)

    return invitation
```

Si hay efectos externos, como emails o llamadas HTTP, evaluar si deben ejecutarse después de confirmar la transacción.

---

## Validaciones

Distribución recomendada:

### Serializer

Validaciones de formato, campos requeridos y estructura.

Ejemplos:

* Email válido.
* Campo obligatorio.
* Longitud máxima.
* Fecha con formato correcto.
* Enum permitido.

### Service

Validaciones de negocio.

Ejemplos:

* El usuario puede crear una empresa.
* La empresa no supera el límite de usuarios.
* Una invitación no puede aceptarse dos veces.
* Una suscripción no puede cancelarse si ya está cancelada.

### Model

Restricciones persistentes.

Ejemplos:

* `unique=True`.
* `null=False`.
* `CheckConstraint`.
* `UniqueConstraint`.

---

## Respuestas API

Usar respuestas consistentes.

Ejemplo de éxito:

```json
{
  "id": 1,
  "name": "Example Company",
  "is_active": true
}
```

Ejemplo de error:

```json
{
  "error": {
    "code": "company_already_exists",
    "message": "A company with this tax ID already exists."
  }
}
```

No devolver errores improvisados con formatos distintos en cada endpoint.

---

## Paginación

Los endpoints de listado deben usar paginación cuando puedan crecer.

Ejemplo:

```txt
GET /api/companies/
GET /api/users/
GET /api/invoices/
```

Evitar devolver listas ilimitadas.

---

## Filtros

Para filtros simples se pueden usar query params:

```txt
GET /api/companies/?is_active=true
GET /api/invoices/?status=pending
```

Los filtros complejos deben encapsularse en selectors.

---

## Migrations

Reglas:

* No editar migraciones antiguas ya aplicadas en entornos compartidos.
* Crear nuevas migraciones para cambios nuevos.
* Revisar migraciones antes de commitear.
* No mezclar cambios de muchos dominios en una misma migración si no es necesario.
* Evitar migraciones con lógica compleja salvo que esté justificado.
* Mantener los modelos y migraciones alineados.

---

## Admin de Django

El admin puede usarse para gestión interna, soporte o pruebas.

Reglas:

* Registrar modelos útiles en `admin.py`.
* No basar la lógica principal del producto en el admin.
* No usar el admin como sustituto de la API pública.
* Personalizarlo solo cuando aporte valor real.

---

## Settings

Separar settings por entorno:

```txt
config/settings/base.py
config/settings/local.py
config/settings/production.py
config/settings/test.py
```

Reglas:

* No hardcodear secretos.
* Usar variables de entorno.
* No commitear `.env`.
* Mantener configuración de producción separada.
* Activar settings de seguridad en producción.
* Configurar CORS explícitamente.
* Configurar logs desde el inicio.

---

## Tests

Cada app debe tener tests propios.

Estructura recomendada:

```txt
apps/companies/tests/
  test_models.py
  test_services.py
  test_selectors.py
  test_api.py
```

Prioridad:

1. Tests de services.
2. Tests de API.
3. Tests de selectors con queries importantes.
4. Tests de permisos.
5. Tests de modelos cuando tengan lógica propia.

No testear internals irrelevantes.

---

## Cuándo crear una nueva app

Crear una nueva app cuando aparezca un dominio con responsabilidad clara.

Sí crear app nueva para:

* Usuarios.
* Empresas.
* Invitaciones.
* Facturación.
* Notificaciones.
* Informes.
* Fichajes.
* Productos.
* Pedidos.

No crear app nueva para:

* Una única función auxiliar.
* Un serializer suelto.
* Un endpoint aislado sin dominio claro.
* Código compartido genérico.

---

## Cuándo crear un módulo shared

Usar `shared/` solo para código realmente transversal.

Permitido:

```txt
shared/api/responses.py
shared/api/pagination.py
shared/auth/permissions.py
shared/utils/dates.py
shared/db/models.py
```

No meter lógica de negocio en `shared/`.

Incorrecto:

```txt
shared/company_logic.py
shared/user_services.py
shared/billing_rules.py
```

Si algo pertenece a un dominio, debe vivir en su app.

---

## Reglas para endpoints

Cada endpoint debe responder a una intención clara.

Bueno:

```txt
POST /api/companies/
POST /api/companies/{id}/invite-user/
POST /api/invitations/{token}/accept/
GET /api/companies/{id}/members/
```

Evitar endpoints genéricos:

```txt
POST /api/action/
POST /api/process/
POST /api/manage/
POST /api/update-status/
```

---

## ViewSets vs APIView

Usar `ViewSet` o `ModelViewSet` cuando el recurso encaje bien con operaciones tipo:

* list
* retrieve
* create
* update
* destroy

Usar `APIView` cuando el endpoint represente una acción muy específica o un flujo que no encaje bien como recurso estándar.

Ejemplo:

```txt
POST /api/auth/login/
POST /api/auth/refresh/
POST /api/invitations/{token}/accept/
```

---

## ModelViewSet

`ModelViewSet` es cómodo, pero no debe usarse de forma automática en todos los casos.

Puede usarse cuando:

* El CRUD sea simple.
* No haya lógica compleja.
* Los permisos sean claros.
* La creación/actualización no requiera coordinación compleja.

Si el flujo tiene reglas de negocio importantes, usar `ViewSet` y llamar explícitamente a services.

---

## Principios de diseño

### 1. Endpoints delgados

Las vistas coordinan, no gobiernan el negocio.

### 2. Servicios explícitos

Cada acción importante debe tener una función clara en `services.py`.

### 3. Lecturas separadas

Las queries reutilizables o complejas deben vivir en `selectors.py`.

### 4. Serializers específicos

No usar el mismo serializer para todos los casos si eso obliga a meter condicionales raros.

### 5. Apps con límites claros

Cada dominio debe controlar sus propios modelos, services, selectors y reglas.

### 6. Shared pequeño

`shared/` debe ser útil, no un cajón desastre.

### 7. Preparado para crecer

La arquitectura debe permitir separar una app en otro servicio en el futuro con el mínimo dolor posible.

---

## Checklist antes de añadir código nuevo

Antes de crear una funcionalidad, responder:

1. ¿A qué app pertenece?
2. ¿Es una acción de escritura? Entonces va en `services.py`.
3. ¿Es una lectura reutilizable? Entonces va en `selectors.py`.
4. ¿Necesita validar input HTTP? Entonces va en `serializers.py`.
5. ¿Necesita permisos específicos? Entonces va en `permissions.py`.
6. ¿Necesita modelo nuevo? Entonces va en `models.py` y migración.
7. ¿Afecta a varias entidades? Entonces revisar transacciones.
8. ¿Es compartido de verdad? Solo entonces va en `shared/`.
9. ¿Necesita test de service?
10. ¿Necesita test de API?

---

## Checklist de pull request

Antes de aceptar una PR:

* La funcionalidad está en la app correcta.
* No hay lógica de negocio compleja en views.
* No hay lógica de negocio compleja en serializers.
* Los services no dependen de `request`.
* Los services no devuelven `Response`.
* Los selectors no modifican datos.
* Las queries importantes están optimizadas.
* Los serializers tienen responsabilidad clara.
* Los permisos están separados.
* Las migraciones han sido revisadas.
* Hay tests suficientes.
* No se han añadido secretos al repo.
* No se ha usado `shared/` como cajón desastre.
* Los nombres son claros y expresan intención.

---

## Ejemplo de app bien estructurada

```txt
apps/companies/
  models.py
  serializers.py
  views.py
  urls.py
  services.py
  selectors.py
  permissions.py
  exceptions.py
  tests/
    test_services.py
    test_selectors.py
    test_api.py
  migrations/
```

Ejemplo de flujo para crear empresa:

```python
# serializers.py

class CompanyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    tax_id = serializers.CharField(max_length=50)
```

```python
# services.py

def create_company(*, user, data):
    if Company.objects.filter(tax_id=data["tax_id"]).exists():
        raise CompanyAlreadyExists()

    return Company.objects.create(
        name=data["name"],
        tax_id=data["tax_id"],
        created_by=user,
    )
```

```python
# serializers.py

class CompanyDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "name", "tax_id", "is_active", "created_at"]
```

```python
# views.py

class CompanyViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def create(self, request):
        serializer = CompanyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        company = create_company(
            user=request.user,
            data=serializer.validated_data,
        )

        output = CompanyDetailSerializer(company)
        return Response(output.data, status=status.HTTP_201_CREATED)
```

---

## Anti-patrones prohibidos

Evitar:

```txt
views.py con cientos de líneas de lógica.
serializers.py haciendo procesos de negocio.
models.py enviando emails o llamando APIs externas.
shared/ lleno de lógica de dominios concretos.
apps/core/ como carpeta principal de negocio.
services.py genérico para todo el proyecto.
queries duplicadas por muchas vistas.
endpoints sin serializers.
respuestas de error inconsistentes.
migraciones sin revisar.
imports cruzados sin control entre apps.
```

---

## Decisión arquitectónica principal

Este backend debe crecer como una **API Django modular por dominios**.

Cada dominio debe poder entenderse, testearse y evolucionar de forma aislada.

La arquitectura debe ser simple al principio, pero lo bastante ordenada para que, si una parte del sistema crece mucho, pueda separarse en el futuro con menos fricción.
