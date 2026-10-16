# Laboratorio: un agente del Mundial 2026 en Amazon Bedrock AgentCore

Construyes **Parcero**, un agente de IA que responde preguntas sobre el Mundial 2026 con RAG y lleva el tracker de tu álbum Panini (qué láminas te faltan y cuáles tienes repetidas) en una tabla de DynamoDB. El álbum viene precargado con el tracker real de Camilo, exportado de Figuritas App. El agente está escrito con **Strands Agents**, corre en **Amazon Bedrock AgentCore Runtime**, usa **Amazon Nova 2 Lite** como modelo y recuerda la conversación con **AgentCore Memory**. Los documentos viven en una **base de conocimiento administrada de Amazon Bedrock**. Lo usas desde una aplicación web en React con inicio de sesión de **Amazon Cognito**.

```
            ┌──────────────────────────────── AWS · stack AgenteMundial ─────────────────────────────────┐
            │                                                                                              │
 Navegador ─┼─► CloudFront ─┬─► S3 (frontend React)                                                       │
 (login     │               └─► /runtimes/* ─► AgentCore Runtime ─► Agente Strands ─► Nova 2 Lite          │
  Cognito)  │                   (valida el token JWT    │  ├─► buscar_mundial ─► Base de conocimiento ◄── S3│
            │                    de Cognito)            │  ├─► catálogo + CRUD del álbum ─► DynamoDB        │
            │                                           │  └─► botones: álbum, subir documento, sincronizar │
            │                                           └─► AgentCore Memory (historial por sesión)         │
            │   CodeBuild: empaqueta el agente y publica el frontend y los datos durante el despliegue     │
            └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

| Parte | Qué haces | Tiempo |
|---|---|---|
| 0 | Preparar la cuenta | 5 min |
| A | RAG sin código: crear una base de conocimiento administrada en la consola | 15 min |
| B | Desplegar todo con una plantilla de CloudFormation | 20 min |
| C | Entrar a la aplicación y sincronizar la base de conocimiento | 5 min |
| D | Conversar con el agente | 15 min |
| E | Mirar por dentro: memoria, trazas, herramientas y autenticación | 10 min |
| F | *(Opcional)* Retos | — |
| G | Limpiar todo | 5 min |

> **Costo estimado:** unos pocos dólares si borras todo el mismo día. Todo es de pago por uso: Nova 2 Lite cobra por token (es de los modelos más baratos de Bedrock), AgentCore Runtime cobra por el CPU y la memoria que consume tu sesión mientras trabaja (no cobra mientras espera), AgentCore Memory por evento guardado, la base administrada por almacenamiento y por llamada de recuperación, DynamoDB on-demand por solicitud, CodeBuild unos minutos por despliegue y CloudFront por tráfico. Cognito no cobra en este volumen (plan Essentials, capa gratuita). **No hay servidores encendidos**: el frontend es un sitio estático y el agente solo consume mientras responde. Precios vigentes: [aws.amazon.com/bedrock/pricing](https://aws.amazon.com/bedrock/pricing/) y [aws.amazon.com/bedrock/agentcore/pricing](https://aws.amazon.com/bedrock/agentcore/pricing/).

---

## Parte 0 · Preparar la cuenta

Necesitas solamente:

* Una cuenta de AWS con acceso a **Amazon Nova 2 Lite** en Bedrock. Usa la región **us-east-1** (N. Virginia). Los modelos de Amazon están habilitados por defecto; puedes probarlo en **Bedrock → Playgrounds → Chat** eligiendo *Nova 2 Lite*.
* El archivo `plantilla.yaml` del laboratorio.

No necesitas instalar Python, Node.js, Docker ni AWS CDK: todo se construye dentro de tu cuenta durante el despliegue.

Mira la estructura del proyecto (en el zip del laboratorio) antes de seguir:

| Ruta | Qué es |
|---|---|
| `plantilla.yaml` | La plantilla de CloudFormation que vas a desplegar. La genera CDK (`cdk synth`). |
| `mundial_agente/agente_stack.py` | La infraestructura en CDK (Python). Los `CfnParameter` son los parámetros que llenas en la consola. |
| `mundial_agente/construccion.py` | El proyecto de CodeBuild y el *custom resource* que lo ejecuta durante el despliegue. |
| `scripts/construir.sh` | Lo que hace CodeBuild: empaquetar el agente, compilar el frontend, subir documentos y cargar las tablas. |
| `agent/main.py` | El agente: `BedrockAgentCoreApp` + Strands + memoria. Lee el usuario del token de Cognito. |
| `agent/herramientas.py` | Las 8 herramientas: `buscar_mundial` (RAG), `buscar_catalogo` (qué jugador es cada lámina) y el tracker del álbum (resumen + CRUD), ligado al usuario. |
| `agent/acciones.py` | Lo que piden los botones del frontend sin pasar por el modelo: ver el álbum, subir un documento y sincronizar la base. |
| `agent/prompt.md` | El *system prompt*: el comportamiento del agente en lenguaje natural. |
| `frontend/` | La aplicación web: React + Cloudscape, inicio de sesión con Cognito (`react-oidc-context`). |
| `assets/knowledge-base/` | 20 documentos del Mundial: PDF, CSV e imágenes. |
| `assets/album/camilo.txt` | El tracker de Camilo tal como lo exporta Figuritas App: 185 faltantes y 123 repetidas. |
| `mundial_agente/figuritas.py` | Convierte esa exportación en ítems de DynamoDB. |
| `assets/catalogo/catalogo.csv` | El catálogo del álbum: código, jugador y país de las 994 láminas de la lista base y las 120 del Update Set (`UPD-1` a `UPD-120`). |

---

## Parte A · RAG sin código en la consola

Antes de escribir código, veamos qué hace una base de conocimiento por sí sola.

1. Crea un bucket en S3 (`kb-manual-<tus-iniciales>`) y sube 3 o 4 archivos de `assets/knowledge-base/`, por ejemplo `Copa_Mundial_de_Fútbol_de_2026.pdf`, `teams.csv` y `grupos.png`.
2. Abre **Amazon Bedrock → Knowledge Bases → Create Managed KB** (también está en la consola de AgentCore).
3. Ponle un nombre, elige **Amazon S3** como fuente de datos y selecciona tu bucket. Deja el modelo de embeddings por defecto (administrado) y deja que la consola cree el rol de IAM.
4. Cuando la fuente quede *Available*, pulsa **Sync**. Mira cómo cambia el estado y cuántos documentos se indexan.
5. En el panel **Test knowledge base** prueba los dos modos:
   * **Retrieval only**: ves los fragmentos (*chunks*) que encontró y su puntaje. Esto es la "R" de RAG.
   * **Retrieval and response generation** con *Nova 2 Lite*: el modelo responde con citas. Esto es RAG completo.
   * Si está disponible, **Agentic retrieval**: el servicio divide una pregunta compleja en varias búsquedas.
6. Preguntas para probar: *"¿En qué grupo quedó Colombia?"*, *"¿Qué muestra la imagen de las eliminatorias?"* (sí, también indexa imágenes).

Fíjate en lo que **no** tuviste que hacer: elegir un vector store, configurar el chunking, escoger un modelo de embeddings ni un re-ranker. Eso es lo que significa *administrada*. Al terminar, borra esta base de conocimiento y su bucket: en la parte B la plantilla crea la suya.

---

## Parte B · Desplegar con CloudFormation

1. Abre **CloudFormation → Create stack → With new resources (standard)**.
2. Elige **Upload a template file**, sube `plantilla.yaml` y pulsa **Next**.
3. Nombre del stack: `AgenteMundial`. Llena los parámetros:

   | Parámetro | Qué poner |
   |---|---|
   | `CorreoUsuario` | Tu correo. Ahí llega la contraseña temporal. |
   | `UsuarioDemo` | Tu usuario para entrar. Déjalo en `camilo` para tener el álbum de ejemplo con ese nombre, o pon el tuyo (el álbum de ejemplo se carga a tu nombre). |
   | `ModeloId` | Déjalo en `global.amazon.nova-2-lite-v1:0`. |
   | `PrefijoDominio`, `Version`, `CodigoFuente` | Déjalos como están. |

4. Pulsa **Next** dos veces, marca *I acknowledge that AWS CloudFormation might create IAM resources* y pulsa **Submit**.

El despliegue tarda unos 15 a 20 minutos. Mientras tanto, mira en la pestaña **Events** cómo aparecen los recursos y abre `mundial_agente/agente_stack.py` para encontrar cada uno:

1. Tres buckets de S3: documentos del Mundial, frontend y artefactos (el zip del agente).
2. La base de conocimiento administrada (`type: MANAGED`) y su fuente de datos S3.
3. Dos tablas de DynamoDB: el álbum, con *partition key* `owner` (el usuario) y *sort key* `codigo` (por ejemplo `MEX-15`), y el catálogo.
4. Una memoria de AgentCore para el historial de cada conversación.
5. Cognito: un *user pool* con inicio de sesión administrado (*managed login*), el cliente de la aplicación web y tu usuario.
6. **CodeBuild, etapa `agente`** (el recurso `PaqueteAgente`): descarga el código del laboratorio, instala las librerías del agente para **Linux ARM64** (lo que usa AgentCore) y sube el .zip a S3. No hay Docker: es el **despliegue directo de código** de AgentCore.
7. El runtime de AgentCore, creado desde ese .zip (`AgentRuntimeArtifact.from_s3`), con un **autorizador JWT de Cognito**: solo acepta peticiones con un token válido de tu *user pool*.
8. CloudFront: sirve el frontend desde S3 y reenvía `/runtimes/*` a AgentCore, así el navegador llama al agente en el mismo dominio.
9. **CodeBuild, etapa `web`** (`PublicarWeb`): compila el frontend con su configuración (`config.json`), lo publica, sube los documentos, carga el álbum y el catálogo en DynamoDB y lanza la primera ingesta de la base de conocimiento.

> **¿Por qué CDK genera una plantilla con parámetros?** Lo normal en CDK es pasar valores en tiempo de síntesis (contexto). Aquí cada estudiante despliega la misma plantilla con su correo, así que esos valores son `CfnParameter`: CDK escribe `Parameters` en la plantilla y CloudFormation los pide en la consola. Compara `agente_stack.py` con la sección `Parameters` de `plantilla.yaml`.

Si algo falla, la pestaña **Events** muestra el recurso y el motivo. Si falló un recurso `Custom::Construccion`, el motivo trae el ID del build: ábrelo en **CodeBuild → Build history** para ver el log.

Al terminar, abre la pestaña **Outputs** y copia `UrlAplicacion`.

---

## Parte C · Entrar a la aplicación y sincronizar la base de conocimiento

1. Revisa tu correo: llega un mensaje de Cognito con el enlace, tu usuario y una contraseña temporal.
2. Abre `UrlAplicacion`, pulsa **Iniciar sesión**, entra y elige tu contraseña definitiva. Ese formulario es el *managed login* de Cognito, no código del laboratorio.
3. Ve a **Documentos**. En *Sincronizar* ves la ingesta que lanzó el despliegue: la base analiza los documentos (*smart parsing*), los divide en fragmentos, calcula los embeddings y los indexa. Espera a que diga **Completa** (la página se actualiza sola).
4. Sube un documento propio (por ejemplo, un PDF con noticias del Mundial) y pulsa **Sincronizar base de conocimiento**. Mira cómo cambian los contadores *Nuevos* y *Modificados*: la ingesta es incremental.

También puedes ver la base en la consola: **Bedrock → Knowledge Bases → AgenteMundial-mundial**, y probarla como en la parte A.

---

## Parte D · Conversar con el agente

En **Conversación**, prueba esto en orden:

1. *¿Quién ganó la final del Mundial 2026 y con qué marcador?* → usa `buscar_mundial` y cita fuentes. Debajo de la respuesta ves qué herramientas usó.
2. *¿Cuántas láminas me faltan y cuántas puedo cambiar?* → usa `resumen_album` (185 faltantes y 135 copias para cambiar).
3. *¿Qué me falta de los dos equipos que jugaron la final?* → primero busca los finalistas en la base de conocimiento y luego llama a `listar_laminas` por cada selección. **Este es el momento agéntico**: el modelo decidió encadenar herramientas de dos fuentes distintas.
4. *Me salió Julián Álvarez.* → `buscar_catalogo` dice que es la `ARG-19`; la consulta, ve que le faltaba y la pasa a `tengo`.
5. *Cambié la CRO 3 por la COL 1.* → dos cambios: la CRO 3 pierde su única repetida y queda en `tengo`; la COL 1 deja de faltar.
6. *¿Qué fue lo primero que registré hoy?* → responde gracias a la memoria de la sesión.

Abre **Mi álbum** y busca `ARG-19`, `CRO-3` y `COL-1`: los cambios son reales, están en DynamoDB.

Ahora pulsa **Nueva conversación** y repite la pregunta 6. Como es otra sesión, ya no lo sabe.

Por último, crea otro usuario: **Cognito → User pools → (tu pool) → Users → Create user**. Entra con él (en otra ventana privada) y pregunta por tu álbum: está vacío. Cada usuario solo ve sus láminas, y aquí nadie puede hacerse pasar por otro: el agente toma el usuario del **token de Cognito** que ya validó AgentCore, no de algo que escriba el navegador.

---

## Parte E · Mirar por dentro

* **Cómo llama el frontend al agente:** abre las herramientas de desarrollador del navegador (pestaña *Network*) y envía un mensaje. Es un `POST /runtimes/<id>/invocations` con el header `Authorization: Bearer <token>` y el ID de sesión en `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`. Sin token, AgentCore responde 401 antes de llegar a tu código. Lee `frontend/src/api/agente.ts` y `usuario_del_token` en `agent/main.py`.
* **Trazas:** CloudWatch → **GenAI Observability → Bedrock AgentCore**. Abre una sesión y mira cada ciclo del agente: la llamada al modelo, la herramienta elegida, la latencia y los tokens. Si no ves trazas, activa **CloudWatch Transaction Search** (una vez por cuenta: CloudWatch → Application Signals → Transaction Search) y vuelve a conversar.
* **Logs:** CloudWatch → Log groups → `/aws/bedrock-agentcore/runtimes/...`.
* **Memoria:** AgentCore → Memory → tu memoria. Los eventos son los turnos de cada sesión.
* **Un solo endpoint, dos usos:** los botones de **Mi álbum** y **Documentos** llaman al mismo runtime con `{"accion": ...}` en vez de `{"prompt": ...}` (`agent/acciones.py`). No hay API Gateway ni Lambdas: menos piezas que pagar y mantener.

---

## Parte F · Retos opcionales

Para cambiar el código necesitas el entorno de desarrollo: Python 3.12+, Node.js 22+ y AWS CDK (`npm install -g aws-cdk`), con credenciales de AWS en la terminal. Despliega tus cambios con:

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cdk bootstrap                                          # solo la primera vez en la cuenta y región
cdk deploy -c fuente=local --parameters CorreoUsuario=tu@correo.com --parameters Version=2
```

`-c fuente=local` sube tu carpeta como código fuente en vez de descargarlo de GitHub, y subir `Version` hace que CodeBuild vuelva a construir el agente y el frontend.

1. **El prompt manda:** cambia una regla de `agent/prompt.md` (por ejemplo, que responda siempre como narrador de fútbol) y despliega. Solo cambió texto, no código.
2. **Una herramienta nueva:** agrega en `herramientas_para()` una herramienta `proponer_cambio(faltantes_del_otro: list[str])` que diga qué repetidas le sirven a otra persona, agrégala a la lista que devuelve la función y despliega.
3. **Memoria de largo plazo:** agrega a la memoria la estrategia `MemoryStrategy.using_built_in_user_preference()` en el stack. El agente recordará tus gustos entre sesiones distintas del mismo usuario.
4. **Guardrails:** crea un guardrail de Bedrock contra *prompt injection* y pásalo al `BedrockModel` (`guardrail_id`, `guardrail_version`). Intenta engañar al agente.
5. **Comparar modelos:** si tienes acceso a otro modelo (por ejemplo `us.anthropic.claude-haiku-4-5-20251001-v1:0`), actualiza el stack en CloudFormation cambiando solo el parámetro `ModeloId` y compara calidad, latencia y tokens en la observabilidad.

---

## Parte G · Limpiar

**CloudFormation → AgenteMundial → Delete.** Borra los buckets (el despliegue los vacía antes), la base de conocimiento, las tablas, la memoria, el runtime, Cognito y CloudFront. CloudFront tarda unos minutos en borrarse. Si hiciste la parte A, confirma que borraste también esa base de conocimiento y su bucket.

---

## Para el instructor: generar la plantilla

La plantilla sale del código CDK y no usa *assets*, así que se despliega sin `cdk bootstrap`:

```bash
cdk synth -c codigo_fuente=https://github.com/Cerozob/generativeai-luisamigo/archive/refs/heads/main.zip > plantilla.yaml
```

`codigo_fuente` es el valor por defecto del parámetro `CodigoFuente`: el zip que descarga CodeBuild, con esta carpeta en la raíz del repositorio (o en una subcarpeta). Debe ser público. Para probar sin publicar nada, usa `cdk deploy -c fuente=local` (parte F).

---

## Para llevar esto a producción

Este laboratorio es deliberadamente pequeño. Un sistema real normalmente agrega:

* **Respuestas en streaming:** el agente devuelve la respuesta completa al final. AgentCore admite *Server-Sent Events* para mostrarla a medida que se genera. CloudFront corta una respuesta que tarda más de 60 segundos sin enviar datos, otro motivo para usar streaming en turnos largos.
* **AgentCore Gateway:** las herramientas como Lambdas expuestas por MCP, con permisos e IAM por herramienta, en lugar de funciones dentro del agente.
* **Sincronización automática:** eventos de S3 → EventBridge → SQS → Lambda que lanza la ingesta cuando cambia un documento, en vez del botón.
* **Permisos más finos:** el rol del agente puede invocar cualquier modelo porque el modelo es un parámetro; en producción se limita al ARN del modelo elegido. Los botones que cambian la base (subir y sincronizar) serían solo para un grupo de administradores de Cognito.
* **Guardrails, evaluaciones** (AgentCore Evaluations, Strands Evals) y **políticas** (AgentCore Policy) para controlar lo que el agente puede hacer.
