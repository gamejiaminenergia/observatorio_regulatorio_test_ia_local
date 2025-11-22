from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from bs4 import BeautifulSoup
from ollama import chat
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from pydantic import BaseModel


class News(BaseModel):
    companies: list[str]
    persons: list[str]
    events: list[str]


# MODEL_NAME = "gpt-oss:latest"
# MODEL_NAME = "qwen3:14b"
MODEL_NAME = "gpt-oss:120b-cloud"

DEFAULT_URL = "https://gestornormativo.creg.gov.co/gestor/entorno/docs/resolucion_minminas_40505_2025.htm"


def fetch_url_content(url: str) -> str:
    """
    Descarga contenido renderizado de una URL usando Playwright.
    Maneja JavaScript, SPAs y contenido dinámico.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            # Navegar y esperar a que cargue
            page.goto(url, wait_until="networkidle", timeout=60000)
            
            # Esperar un poco más para contenido dinámico
            page.wait_for_timeout(2000)
            
            # Obtener HTML renderizado
            html_content = page.content()
            
        except PlaywrightTimeout:
            print("⚠️ Timeout alcanzado, usando contenido parcial")
            html_content = page.content()
        finally:
            browser.close()
    
    # Limpiar con BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Eliminar elementos no relevantes
    for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe']):
        element.decompose()
    
    # Extraer texto limpio
    text = soup.get_text(separator='\n', strip=True)
    
    # Limpiar líneas vacías
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    clean_text = '\n'.join(lines)
    
    # Limitar tamaño
    max_chars = 50000
    if len(clean_text) > max_chars:
        clean_text = clean_text[:max_chars] + "\n\n[Contenido truncado...]"
    
    return clean_text


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "persons": ("persons", "personas", "people", "individuos"),
    "companies": ("companies", "empresas", "organizations", "organizaciones"),
    "events": ("events", "eventos", "hechos", "acontecimientos"),
}


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    return [str(value).strip()]


def parse_news_response(content: Any) -> News:
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Respuesta del modelo no es JSON válido: {exc}") from exc
    elif isinstance(content, dict):
        payload = content
    else:
        raise ValueError("Respuesta del modelo tiene un formato inesperado")

    normalized: dict[str, Any] = {}
    lowered_keys = {key.lower(): key for key in payload}

    for field, aliases in FIELD_ALIASES.items():
        selected_key = next((lowered_keys[alias] for alias in aliases if alias in lowered_keys), None)
        selected_value = payload.get(selected_key, []) if selected_key else []
        normalized[field] = _coerce_list(selected_value)

    return News(**normalized)


TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "fetch_url_content",
            "description": "Descarga contenido web renderizado (incluyendo JavaScript) y extrae texto limpio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL completa (http/https) que se debe consultar.",
                    }
                },
                "required": ["url"],
            },
        },
    }
]

TOOL_EXECUTORS: dict[str, Callable[..., str]] = {
    "fetch_url_content": fetch_url_content,
}


def call_model(messages: list[dict[str, Any]]):
    return chat(
        model=MODEL_NAME,
        messages=messages,
        think="high",
        format=News.model_json_schema(),
        tools=TOOLS_SPEC,
    )


def run_news_extraction(url: str = DEFAULT_URL) -> News:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "Eres un analista experto que extrae información estructurada de documentos web. "
                "Identifica personas (nombres completos), empresas (razones sociales) y eventos relevantes. "
                "Si necesitas datos frescos, llama al tool `fetch_url_content` con la URL exacta. "
                "Devuelve SIEMPRE un JSON válido siguiendo el esquema proporcionado."
            ),
        },
        {
            "role": "user",
            "content": (
                "Analiza el contenido de la siguiente URL y extrae:\n"
                "- Personas: nombres de individuos mencionados\n"
                "- Empresas: organizaciones, compañías o entidades\n"
                "- Eventos: hechos, resoluciones, acuerdos o acontecimientos importantes\n\n"
                f"URL objetivo: {url}"
            ),
        },
    ]

    response = call_model(messages)

    # Manejar llamadas a tools iterativamente
    iteration = 0
    max_iterations = 5
    
    while getattr(response.message, "tool_calls", None) and iteration < max_iterations:
        iteration += 1
        print(f"\n🔄 Iteración {iteration}")
        
        for tool_call in response.message.tool_calls:
            function_name = tool_call.function.name
            arguments = tool_call.function.arguments or "{}"

            if isinstance(arguments, str):
                payload = json.loads(arguments)
            else:
                payload = arguments

            executor = TOOL_EXECUTORS.get(function_name)
            if executor is None:
                raise ValueError(f"Tool '{function_name}' no está implementado.")

            print(f"🔧 Ejecutando tool: {function_name}")
            print(f"   URL: {payload.get('url', 'N/A')}")
            
            tool_result = executor(**payload)
            print(f"✅ Tool ejecutado. Contenido extraído: {len(tool_result)} caracteres")
            
            messages.append(
                {
                    "role": "tool",
                    "name": function_name,
                    "content": tool_result,
                }
            )

        response = call_model(messages)

    return parse_news_response(response.message.content)


if __name__ == "__main__":
    print("🚀 Iniciando extracción de noticias con Playwright...")
    print("📦 Asegúrate de tener instalado: pip install playwright beautifulsoup4")
    print("🔧 Y ejecuta: playwright install chromium\n")
    
    try:
        news = run_news_extraction()
        
        print("\n" + "="*60)
        print("📊 RESULTADOS EXTRAÍDOS")
        print("="*60)
        
        print(f"\n👥 Personas ({len(news.persons)}):")
        for person in news.persons:
            print(f"  • {person}")
        
        print(f"\n🏢 Empresas ({len(news.companies)}):")
        for company in news.companies:
            print(f"  • {company}")
        
        print(f"\n📅 Eventos ({len(news.events)}):")
        for event in news.events:
            print(f"  • {event}")

        output_path = Path("data.json")
        output_path.write_text(
            json.dumps(news.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n💾 Resultados guardados en: {output_path.resolve()}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
