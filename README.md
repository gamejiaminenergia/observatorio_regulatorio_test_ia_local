# Observatorio Regulatorio · Extracción IA de la Resolución 40505 de 2025

Este repositorio contiene el flujo que **sí produjo resultados consistentes** al analizar la [Resolución 40505 de 2025 del Ministerio de Minas y Energía](https://gestornormativo.creg.gov.co/gestor/entorno/docs/resolucion_minminas_40505_2025.htm). El pipeline `chunked_news_extraction.py` usa LangChain + Ollama en local para descargar la resolución, dividirla en fragmentos manejables y extraer listas de **personas**, **entidades** y **eventos** clave.

> ⚠️ Los demás scripts Python se mantienen fuera de este README porque no alcanzaron el desempeño esperado. Aquí solo se describe el flujo de fragmentación (`chunked_news_extraction.py`) y el despliegue de Ollama con Docker.

## Importancia del análisis regulatorio con IA local

- **Privacidad y confidencialidad**: al ejecutar los modelos en tu propia infraestructura no se exponen documentos sensibles ni trazas de uso a servicios externos.
- **Cumplimiento normativo**: los equipos jurídicos pueden auditar el flujo completo (desde la descarga hasta el JSON final) y mantener un registro verificable de cada corrida.
- **Reproducibilidad y control**: al fijar la versión del modelo y los prompts, cada análisis puede replicarse para sustentar decisiones regulatorias o responder a entes de control.
- **Costos predecibles**: se evita depender de APIs de terceros y sus variaciones de precio o disponibilidad.

## Visión general del flujo por fragmentos

```text
PlaywrightURLLoader  ──► Texto limpio (sin script/style)
                ┌───── ► Chunking con solapamiento (2 000 + 100 caracteres)
                │
LangChain + Ollama ───► LLM local con formato JSON (Pydantic)
                │
                └───── ► Fusión de resultados y deduplicación
```

1. **Descarga confiable**: `PlaywrightURLLoader` renderiza la página y elimina elementos ruidosos.
2. **Fragmentación controlada**: cada chunk conserva contexto gracias al solapamiento de 100 caracteres.
3. **Modelo local**: `ChatOllama` ejecuta `gpt-oss:latest` (puedes cambiarlo) y responde en JSON validado con Pydantic.
4. **Merge inteligente**: se consolidan las listas y se eliminan duplicados manteniendo el orden original.

## Requisitos

- Python 3.10+
- [Ollama](https://ollama.com/) funcionando localmente
- Dependencias Python:
  ```bash
  pip install -r requirements.txt
  playwright install chromium
  ```

## Levantar Ollama por Docker

`docker-compose.yml` ya expone el puerto `11434` y reserva GPU si está disponible.

```bash
docker compose up -d
ollama pull gpt-oss:latest   # u otro modelo compatible
```

Una vez que el contenedor esté arriba, el script Python puede conectarse vía `http://localhost:11434`.

## Ejecución del pipeline principal

```bash
python chunked_news_extraction.py
```

- Cambia la URL editando `DEFAULT_URL` si necesitas otra norma.
- Ajusta `CHUNK_SIZE`/`CHUNK_OVERLAP` para documentos más extensos o equipos con menos RAM.
- El resultado estructurado se imprime en consola y se guarda como `data.json`.

## Carpeta `example/` y resultado de referencia

La carpeta `example/` almacena los **resultados obtenidos durante la experimentación**. Son JSON reales que documentan qué devolvió el pipeline bajo diferentes configuraciones de modelo.

`example/final.json` incluye un ejemplo generado con este flujo (recorte abajo):

```json
{
  "companies": ["MINISTERIO DE MINAS Y ENERGÍA", "CREG", "XM Compañía de Expertos en Mercados"],
  "persons": ["presidente de la República", "Karen Schutt Esmeral"],
  "events": ["Resolución 40505 de 2025", "Resoluciones CREG 024 y 025 del 2021"]
}
```

## Personalización rápida

- **Modelo**: cambia `MODEL_NAME = "gpt-oss:latest"` por cualquier modelo instalado en Ollama.
- **Selectores a remover**: edita `remove_selectors` en el loader si necesitas conservar cierto HTML.
- **Validación**: amplía el esquema `News` para capturar más campos (por ejemplo, artículos citados o fechas clave).

## Próximos pasos sugeridos

1. Crear una interfaz (Flask/ngrok ya están en `requirements.txt`) para lanzar ejecuciones sin tocar la terminal.
2. Automatizar pruebas que comparen los JSON resultantes contra expected outputs en `example/`.
3. Documentar nuevos modelos o prompts que mejoren la precisión sobre otras resoluciones.

---

¿Comentarios o mejoras? Abre un issue o pull request con tus hallazgos.
