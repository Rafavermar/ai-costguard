# Prompt: validacion controlada en PC de trabajo

Usa este prompt cuando quieras instalar y validar `ai-costguard` en un ordenador de trabajo con Cline, sin exponer secretos y sin tocar configuraciones reales hasta que el smoke aislado haya pasado.

Esta version incorpora aprendizajes reales de Windows corporativo: `python` puede no estar en PATH, `uv` puede ser la ruta mas fiable, los repos en OneDrive pueden fallar con hardlinks, y conviene instalar `costguard` como comando global antes del smoke.

````text
Quiero instalar y validar el repo `ai-costguard` en mi ordenador de trabajo de forma controlada y sin exponer secretos.

IMPORTANTE SOBRE CLINE Y CONTEXTO:
- Empieza siempre con una task nueva en Cline para esta validacion.
- No uses Retry sobre conversaciones anteriores si aparece un error de seguridad.
- No reutilices una task que haya contenido referencias a credenciales, secretos, tokens, API keys, `.env`, Databricks tokens, Azure secrets o configuracion corporativa sensible.
- Si aparece el error `payload blocked by secret filter`, asume primero que puede deberse a contexto acumulado enviado por Cline, no necesariamente a Cost Guard.
- Antes de diagnosticar Cost Guard, valida con una task nueva y un prompt minimo: `Di OK`.
- No cargues como contexto archivos `.env`, `.env.*`, `databricks.yml`, `.pem`, `.key`, `.pfx`, `.p12`, carpetas `.cline`, `.vscode` ni ficheros de credenciales.
- No incluyas en respuestas ni en prompts valores reales de secretos. Usa siempre placeholders como `<REDACTED>`.

No ejecutes nada sobre mi HOME real hasta que yo lo confirme explicitamente.

Reglas de seguridad:
- No me pidas pegar secretos en el chat.
- No imprimas claves, tokens ni contenido sensible.
- No leas ni muestres `.env` si contiene secretos.
- No pases secretos como argumentos de comandos.
- No subas ni commitees `.env`.
- No modifiques repos de cliente.
- No toques ningun repo distinto a `ai-costguard` salvo que yo lo pida.
- No cambies configuracion real de Claude Code hasta que yo lo confirme.
- Primero valida todo con `COSTGUARD_HOME` y `COSTGUARD_CLAUDE_HOME` dentro del repo.

Primero lee:
- `README.md`
- `docs/RUNBOOK.md`
- `docs/SECURITY.md`
- `docs/TROUBLESHOOTING.md`
- `pyproject.toml`

Resume:
- que es Cost Guard
- como se instala
- como se configura Cline
- como se configura Claude Code
- como se desinstala
- que ficheros locales toca
- que componentes son obligatorios y cuales opcionales
- que contexto envia Cline y como evitar que una task previa contamine nuevas pruebas
- como actuar si aparece `payload blocked by secret filter`

## FASE 1 - Detectar Python y uv disponibles

En maquinas corporativas, `python` puede no estar en PATH. Antes de crear el venv, detecta el ejecutable disponible:

```powershell
where.exe python
where.exe python3
Get-Command py -ErrorAction SilentlyContinue
where.exe uv
```

Si `uv` esta disponible, usalo como opcion recomendada.
Si solo hay `python`, `python3` o `py`, usa ese ejecutable directamente.
No instales ni cambies Python global sin mi permiso.

## FASE 2 - Crear entorno local e instalar dependencias

Opcion A: con `uv` (recomendada si esta disponible):

```powershell
uv python list
uv venv .venv --python 3.14
uv pip install -e ".[dev]" --python .venv\Scripts\python.exe --link-mode=copy
```

Notas:
- La version Python debe ser `>=3.10`; usa la version disponible en el equipo si no existe Python 3.14.
- En repos bajo OneDrive, usa siempre `--link-mode=copy` para evitar errores de hardlinks.

Opcion B: con `python` / `pip` estandar:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
```

Luego ejecuta tests:

```powershell
.\.venv\Scripts\pytest.exe
```

## FASE 3 - Instalar `costguard` como comando global

Esto es importante para poder usar `costguard` directamente desde cualquier terminal sin activar venv ni usar rutas largas.

Con `uv tool install` (recomendado):

```powershell
uv tool install --editable "." --link-mode=copy
```

Si estas fuera de la raiz del repo, usa la ruta completa:

```powershell
uv tool install --editable "<ruta-al-repo-ai-costguard>" --link-mode=copy
```

Ejemplo:

```powershell
uv tool install --editable "C:\Users\<user>\OneDrive - Empresa\Documentos\Github\AI\ai-costguard" --link-mode=copy
```

Notas:
- En maquinas con OneDrive, `--link-mode=copy` es obligatorio para evitar fallos de hardlinks.
- Si el paquete ya estaba instalado, usa la opcion de reinstalacion/upgrade que indique `uv`, manteniendo `--link-mode=copy`.
- No edites PATH global sin mi permiso. Si el comando no aparece, dime donde quedo instalado.

Verifica:

```powershell
costguard --help
```

Alternativa con `pipx`:

```powershell
pipx install --editable "<ruta-al-repo-ai-costguard>"
```

## FASE 4 - Smoke tests aislados

Nunca ejecutes smoke tests contra el HOME real. Usa paths temporales dentro del repo:

```powershell
$env:COSTGUARD_HOME = "$(Get-Location)\.tmp\costguard"
$env:COSTGUARD_CLAUDE_HOME = "$(Get-Location)\.tmp\claude"
```

Luego ejecuta en orden:

```powershell
costguard --help
costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
costguard cline-config
costguard status
costguard rules test "cat .env"
costguard rules test "git diff"
costguard rules test "find ."
costguard budget status
costguard usage today
costguard cache status
costguard headroom status
costguard uninstall --yes
```

Despues del uninstall aislado, ejecuta tests de nuevo:

```powershell
.\.venv\Scripts\pytest.exe
```

Todos deben pasar.

En PowerShell no uses `&&`; ejecuta comandos separados o usa `;`.

Prueba adicional obligatoria para validar proxy OpenAI Compatible sin Cline:
- Arranca `costguard start` en una terminal separada si no esta arrancado.
- Ejecuta una llamada minima contra `http://127.0.0.1:4040/v1/chat/completions` usando:
  - model: `cg-active`
  - message: `Di OK`
  - API key local: `sk-costguard-local`
- Comprueba que responde correctamente.
- Despues comprueba `costguard usage today`.

Prueba adicional obligatoria para validar Cline:
- Abre una task nueva en Cline.
- No uses Retry.
- Envia solo: `Di OK`.
- Comprueba que responde `OK`.
- Despues comprueba `costguard usage today`.
- Si funciona en task nueva pero no en task anterior, documenta que la causa probable era contexto acumulado de Cline bloqueado por el secret filter corporativo.
- Si Headroom esta habilitado, valida evidencia en `costguard usage today`:
  - `headroom_applied_count > 0`
  - `headroom_tokens_saved > 0` si el prompt/contexto era suficientemente largo
  - `headroom_reduction_ratio > 0` si hubo compresion efectiva
  - `outputs_reduced` NO es evidencia de Headroom; es recorte de salida por output limits.

## FASE 5 - Setup real SOLO para Cline

Si todos los smoke tests estan OK, limpia las variables de entorno temporales y ejecuta el setup real:

```powershell
Remove-Item Env:COSTGUARD_HOME -ErrorAction SilentlyContinue
Remove-Item Env:COSTGUARD_CLAUDE_HOME -ErrorAction SilentlyContinue
costguard setup --tool cline --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
```

No configures Claude Code todavia.

## FASE 6 - Credenciales corporativas

Indicame que fichero debo editar.
No imprimas el contenido sensible.
Yo introducire manualmente la Base URL, API key y modelo corporativo en `.env`.

El fichero a editar normalmente es:

```text
C:\Users\<user>\.costguard\.env
```

Variables habituales:

```text
# Endpoint de inferencia: lo usa CostGuard para llamar al modelo.
OPENAI_UPSTREAM_BASE_URL=<base URL corporativa>
OPENAI_UPSTREAM_API_KEY=<API key corporativa>
OPENAI_MODEL_CHEAP=<modelo barato/aprobado>
OPENAI_MODEL_STANDARD=<nombre del modelo>
OPENAI_MODEL_STRONG=<modelo potente/aprobado>

# Endpoint de pricing: lo usa CostGuard solo para obtener precios/catalogo.
COSTGUARD_PRICING_URL=<endpoint catalogo modelos/precios>
COSTGUARD_PRICING_API_KEY_ENV=OPENAI_UPSTREAM_API_KEY
COSTGUARD_PRICING_AUTH_HEADER=x-api-key
COSTGUARD_PRICING_AUTH_SCHEME=
```

Si la empresa usa una key distinta para pricing, usa `COSTGUARD_PRICING_API_KEY_ENV=PRICING_API_KEY` y define esa variable solo en el entorno local. No dupliques ni imprimas secretos.

No imprimas los valores reales.

Nota sobre modelos Claude/Haiku/Sonnet/Opus:
- Si esos modelos estan disponibles a traves del endpoint OpenAI-compatible corporativo, usalos primero con Cline + CostGuard mapeando `OPENAI_MODEL_CHEAP`, `OPENAI_MODEL_STANDARD` y `OPENAI_MODEL_STRONG`.
- El endpoint Anthropic-compatible es otra ruta distinta y solo aplica si el proveedor expone API tipo Anthropic Messages `/v1/messages`.
- Para Claude Code, CostGuard usa `ANTHROPIC_MODEL=cg-active` y enruta internamente con `costguard use cheap|standard|strong`.
- El plugin oficial de Claude Code en VS Code debe validarse con una prueba real: solo dalo por bueno si confirma trafico por `http://127.0.0.1:4040` y aparece en `costguard usage today`.

## FASE 7 - Validacion post-credenciales

```powershell
costguard doctor
costguard status
costguard cline-config
costguard pricing status
```

El doctor debe mostrar 0 ERRORs. Los WARNs de upstream deben desaparecer tras anadir credenciales.

Si `COSTGUARD_PRICING_URL` esta configurado, refresca precios:

```powershell
costguard pricing refresh
costguard pricing status
```

El pricing endpoint debe ser generico y de la empresa/proveedor que se este usando. No hardcodees precios reales ni endpoints reales en el repo.

## Cache basico, opcional y controlado

Estado seguro recomendado:

```text
COSTGUARD_CACHE_MODE=disabled
COSTGUARD_CACHE_STORE_CONTENT=false
```

No actives `COSTGUARD_CACHE_STORE_CONTENT=true` con prompts que puedan contener secretos, datos de cliente, credenciales, tokens, `.env`, logs sensibles o informacion que no deba persistirse localmente.

Para validar cache basico, usa primero llamadas directas identicas al proxy, no Cline. Cline puede anadir historial, herramientas, metadata o diferencias internas que cambian la cache key aunque el prompt parezca igual.

Si yo pido validar cache basico:

```powershell
costguard cache enable --mode basic
$env:COSTGUARD_CACHE_STORE_CONTENT = "true"
$env:COSTGUARD_CACHE_MAX_ENTRIES = "1000"
$env:COSTGUARD_CACHE_MAX_SIZE_MB = "100"
$env:COSTGUARD_CACHE_EVICTION_POLICY = "lru"
```

Haz dos llamadas directas identicas y seguras al proxy local con:

```text
POST http://127.0.0.1:4040/v1/chat/completions
Authorization: Bearer sk-costguard-local
model: cg-cheap o cg-active
temperature: 0
max_tokens: 10
message: Responde exactamente: CACHE TEST OK
```

Despues revisa:

```powershell
costguard usage today
costguard cache status
```

Evidencia esperada:

```text
cache_misses=1
cache_hits=1
cache_hit_ratio=0.5
cache_tokens_saved > 0
response_entries=1
functional=True
```

Despues de la prueba vuelve al estado seguro:

```powershell
costguard cache disable
$env:COSTGUARD_CACHE_STORE_CONTENT = "false"
```

Semantic cache sigue siendo experimental hasta que existan embeddings, vector storage, similarity threshold, metricas de semantic hits/misses y tests.

## Configuracion de Cline

Muestrame que poner en Cline:

```text
Provider: OpenAI Compatible
Base URL: http://127.0.0.1:4040/v1
API Key: sk-costguard-local
Model ID: cg-active
```

Explica la diferencia:
- `cg-active` permite que `costguard use cheap|standard|strong` cambie el routing sin editar Cline.
- `cg-standard`, `cg-cheap` y `cg-strong` son aliases fijos.

No intentes modificar Cline automaticamente si no esta claro como hacerlo.

## Arrancar Cost Guard

`costguard start` bloquea la terminal. Para dejarlo corriendo:

1. Abre una terminal nueva en VS Code.
2. Ejecuta `costguard start`.
3. Deja esa terminal abierta.
4. Usa otra terminal para el resto de comandos.

Valida desde otra terminal:

```powershell
costguard doctor
costguard status
```

## Prueba real minima con Cline

Cuando yo haya configurado Cline con `http://127.0.0.1:4040/v1`, hare una pregunta muy pequena en Cline.

Despues revisa:

```powershell
costguard usage today
costguard budget status
```

Valida que:
- Cost Guard ha registrado uso.
- No ha guardado prompts/respuestas por defecto.
- El budget funciona.
- Cline sigue operativo.
- Si aparece un error `429`, separa el diagnostico: puede ser cuota/rate limit del upstream aunque Cost Guard muestre `action=allow`.

## Claude Code, opcional

No configures Claude Code hasta que yo lo confirme.

Aclara antes:
- si vamos a validar Claude Code CLI o el plugin oficial de VS Code;
- que CostGuard implementa ruta Anthropic-compatible `/v1/messages` con streaming para Claude Code;
- que `ANTHROPIC_MODEL=cg-active` permite switching con `costguard use cheap|standard|strong`;
- que setup/backup/uninstall, headers, aliases y proxy Anthropic-compatible estan cubiertos con tests/mock;
- que una validacion real requiere licencia/key y endpoint Anthropic-compatible;
- que el plugin oficial queda pendiente hasta comprobar trafico real por el proxy local.

Si confirmo Claude Code:
- comprueba si existe `~/.claude/settings.json`
- explica que se va a modificar
- confirma que se creara backup
- primero prueba `costguard setup --tool claude-code` con `COSTGUARD_CLAUDE_HOME` apuntando a `.tmp\claude`
- confirma que `.env` local contiene `ANTHROPIC_UPSTREAM_BASE_URL`, `ANTHROPIC_UPSTREAM_API_KEY`, `ANTHROPIC_UPSTREAM_AUTH_HEADER`, `ANTHROPIC_UPSTREAM_AUTH_SCHEME` si aplica, y `ANTHROPIC_MODEL_CHEAP/STANDARD/STRONG`
- ejecuta setup real solo cuando yo lo autorice
- valida despues con `costguard doctor`
- valida una request real o controlada a `/v1/messages` si existe key/licencia
- comprueba `costguard usage today` y `costguard budget status`
- ejecuta `costguard uninstall` y confirma que restaura settings si se toco configuracion real

## Uninstall

Antes de ejecutar uninstall:
- explicame que hara `costguard uninstall`
- no ejecutes `costguard uninstall --purge` salvo que yo lo pida
- valida que Claude Code vuelve a su configuracion previa si se toco

## Resumen final

Al terminar, resume:
- tests ejecutados y resultado
- smoke tests ejecutados y resultado
- si `costguard` quedo disponible como comando global
- prueba directa al proxy local
- prueba desde Cline en task nueva
- si hubo errores de `payload blocked by secret filter`
- si esos errores se resolvieron empezando una task nueva
- si hubo errores `429` del upstream y como se diferenciaron del budget local
- si Cline quedo configurado
- si Claude Code quedo configurado
- como arrancar Cost Guard cada dia
- como ver consumo
- como cambiar presupuesto
- como editar reglas
- como desinstalar
- problemas encontrados, especialmente PATH, OneDrive y hardlinks
- cambios realizados en el repo
````
