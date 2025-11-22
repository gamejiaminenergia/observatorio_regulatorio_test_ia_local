from __future__ import annotations

import json
from pathlib import Path

from langchain_ollama import ChatOllama
from langchain_community.document_loaders import PlaywrightURLLoader
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field


class News(BaseModel):
    """Información estructurada extraída de una noticia."""
    companies: list[str] = Field(description="Empresas, organizaciones o entidades mencionadas")
    persons: list[str] = Field(description="Personas (nombres completos) mencionadas")
    events: list[str] = Field(description="Eventos, resoluciones o acontecimientos importantes")


# Configuración
# MODEL_NAME = "gpt-oss:120b-cloud"
MODEL_NAME = "gpt-oss:latest"
DEFAULT_URL = "https://gestornormativo.creg.gov.co/gestor/entorno/docs/resolucion_minminas_40505_2025.htm"


def run_news_extraction(url: str = DEFAULT_URL) -> News:
    """
    Extrae información estructurada de una URL usando LangChain.
    
    Args:
        url: URL del documento a analizar
        
    Returns:
        News: Objeto con personas, empresas y eventos extraídos
    """
    print(f"🌐 Cargando contenido de: {url}")
    
    # 1️⃣ Cargar contenido web (maneja JavaScript automáticamente)
    loader = PlaywrightURLLoader(
        urls=[url],
        remove_selectors=["script", "style", "nav", "header", "footer", "aside", "iframe"]
    )
    docs = loader.load()
    content = docs[0].page_content if docs else ""
    
    # Limitar tamaño del contenido
    max_chars = 50000
    if len(content) > max_chars:
        content = content[:max_chars] + "\n[Contenido truncado...]"
    
    print(f"✅ Contenido cargado: {len(content)} caracteres")
    
    # 2️⃣ Configurar modelo con salida estructurada
    llm = ChatOllama(
        model=MODEL_NAME,
        temperature=0,
        format="json"  # Solicita salida JSON al servidor Ollama
    )

    parser = PydanticOutputParser(pydantic_object=News)

    # 3️⃣ Crear prompt con instrucciones de formato
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "Eres un analista experto que extrae información estructurada de documentos. "
         "Identifica personas (nombres completos), empresas (razones sociales) y eventos relevantes. "
         "Debes responder exclusivamente con JSON válido que siga el siguiente esquema:\n{format_instructions}"),
        ("human",
         "Analiza el siguiente contenido y extrae:\n"
         "- Personas: nombres de individuos mencionados\n"
         "- Empresas: organizaciones, compañías o entidades\n"
         "- Eventos: hechos, resoluciones, acuerdos o acontecimientos importantes\n\n"
         "CONTENIDO:\n{content}")
    ]).partial(format_instructions=parser.get_format_instructions())

    # 4️⃣ Crear cadena y ejecutar
    chain = prompt | llm

    print("🤖 Procesando con modelo local...")
    response = chain.invoke({"content": content})

    try:
        news = parser.parse(response.content)
    except Exception as parse_error:
        raise ValueError(
            "No se pudo interpretar la respuesta del modelo como JSON válido. \n"
            f"Respuesta recibida: {response.content}"
        ) from parse_error
    
    return news


if __name__ == "__main__":
    print("🚀 Iniciando extracción de noticias con LangChain\n")
    print("📦 Requisitos: pip install langchain langchain-community playwright")
    print("🔧 Ejecuta: playwright install chromium\n")
    
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

        # Guardar resultados
        output_path = Path("data.json")
        output_path.write_text(
            json.dumps(news.dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n💾 Resultados guardados en: {output_path.resolve()}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
