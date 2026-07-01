# Desafío AI FinOps — Especificación

**Formato:** Hackathon universitario · 2 días
**Entregable:** Turno de 10 minutos por equipo

---

## Contexto

Las empresas consumen cada vez más servicios de IA generativa (LLMs, modelos de imagen, speech-to-text…), a menudo de varios proveedores a la vez. El problema: **nadie tiene visibilidad real sobre cuánto se gasta, quién lo gasta ni si ese gasto está justificado**. Según Flexera 2025, el 32 % del gasto cloud se desperdicia, y la IA generativa está acelerando esa cifra.

Tu misión: construir la pieza de infraestructura que falta.

---

## Enunciado del Desafío

**Título:** *AI FinOps Proxy — Construye la capa de control de costes para la IA*

Diseña e implementa un **proxy** (reverse proxy, API gateway, sidecar…) que se interponga entre los consumidores internos y los proveedores de IA. El proxy debe:

1. **Interceptar** las llamadas a la API de IA de forma transparente.
2. **Registrar** el coste estimado de cada solicitud (tokens consumidos × tarifa del modelo).
3. **Controlar** el gasto aplicando límites de presupuesto por consumidor.
4. **Recomendar** optimizaciones de coste (modelo más barato, caché de respuestas, reducción de tokens, etc.).

### Restricciones

| Regla | Detalle |
|---|---|
| Multi-proveedor | Debe soportar **al menos 2 proveedores de IA** (p. ej. Ollama + Groq, o 2 contenedores Ollama como los del starter kit) |
| Stack libre | Cada equipo elige su propio stack tecnológico; no hay restricción de lenguaje, framework ni base de datos |
| Sin claves de producción | Se permiten cuentas sandbox, tiers gratuitos, modelos locales o mocks que simulen respuestas reales |
| Simulación de consumidores | El sistema debe simular **al menos 2 consumidores internos distintos** (p. ej. "equipo-marketing", "equipo-producto") con seguimiento de costes independiente |

---

## Criterios de Aceptación (puertas de paso obligatorias)

Una solución se considera **válida** solo si **todos** los siguientes puntos se demuestran en la demo en vivo:

- [ ] El proxy intercepta solicitudes y las distribuye (enruta/balancea) de forma inteligente entre al menos 2 proveedores de IA, seleccionando el modelo más adecuado según los criterios de coste y/o calidad definidos por el equipo.
- [ ] El uso de tokens y el coste se registran para cada solicitud.
- [ ] Se identifican al menos 2 consumidores distintos, cada uno con su propio historial y acumulado de gasto.
- [ ] Existe un límite de presupuesto configurable; al superarse, el sistema genera una respuesta visible (bloqueo, alerta o degradación).
- [ ] El equipo articula al menos **2 criterios explícitos** usados para decidir cuándo y cómo ahorrar costes.
- [ ] La demo es en vivo

---

## Rúbrica de Evaluación (110 puntos + 5 bonus)

### Pilar 1 — Visibilidad de Costes (25 pts)

> *«¿Puedo ver en qué se está gastando?»*

| Criterio | Puntos | Qué buscan los jueces |
|---|---|---|
| Captura el uso de tokens por solicitud para ambos proveedores | 10 | La demo muestra una llamada real siendo rastreada |
| Desglosa el coste por equipo/proyecto/consumidor | 10 | Al menos 2 consumidores simulados con gasto diferenciado |
| Los datos son precisos respecto a los precios del proveedor | 5 | El juez pregunta: «¿cuánto costó esa llamada?» y el equipo puede verificarlo |

### Pilar 2 — Gobernanza, Control y Definición de Presupuesto (25 pts)

> *«¿Puedo controlar quién gasta qué?»*

| Criterio | Puntos | Qué buscan los jueces |
|---|---|---|
| Se pueden establecer límites de presupuesto por consumidor/equipo | 5 | La demo muestra un presupuesto alcanzado y la solicitud bloqueada/advertida |
| Se disparan alertas al cruzar un umbral | 5 | Notificación visible (email, webhook, UI — cualquier canal) |
| Existe un registro de auditoría de todas las llamadas a IA | 5 | Los jueces pueden consultar el uso histórico |
| Predicción de costes futuros basada en tendencias de uso | 10 | El equipo muestra un gráfico o dashboard con proyección de gasto |

### Pilar 3 — Criterios de Decisión para Ahorro de Costes (30 pts)

> *«¿Cómo decidisteis qué optimizar y por qué?»*

| Criterio | Puntos | Qué buscan los jueces |
|---|---|---|
| Define criterios explícitos para cuándo enrutar a un modelo más barato | 10 | El equipo presenta una regla de decisión (p. ej. «tareas con menos de N tokens y sin contexto de código usan el modelo X») |
| Justifica los trade-offs entre coste y calidad | 10 | El equipo explica qué señales de calidad midieron y qué degradación es aceptable |
| Demuestra los criterios aplicados a datos de uso reales | 10 | Un dashboard o salida muestra qué solicitudes activaron la regla y el ahorro estimado |

### Pilar 4 — Arquitectura y Diseño (20 pts)

> *«¿Es un planteamiento listo para producción?»*

| Criterio | Puntos | Qué buscan los jueces |
|---|---|---|
| Diseño agnóstico al proveedor (funciona con OpenAI + Anthropic, Ollama + Groq, etc.) | 10 | Ambos proveedores mostrados en la demo |
| Clara separación de responsabilidades (proxy / almacenamiento / reporting) | 5 | Diagrama de arquitectura presentado |
| Seguridad: las claves de API nunca se exponen a los consumidores | 5 | Explicado durante las preguntas |

#### Nota sobre herramientas de terceros

Los equipos pueden usar herramientas open-source como componentes. Esto **no penaliza ni favorece** — el Pilar 4 evalúa la **comprensión y las decisiones de diseño**, no las líneas de código escritas.

### Pilar 5 — Presentación y Equipo (10 pts)

| Criterio | Puntos | Qué buscan los jueces |
|---|---|---|
| La demo es clara y cuenta una historia | 10 | Un juez no técnico puede seguir la narrativa |

---

**¡Buena suerte! Construid algo que cualquier CTO querría tener en producción el lunes.**
