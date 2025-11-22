from __future__ import annotations

import json
from pathlib import Path
from typing import List

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
MODEL_NAME = "gpt-oss:latest"
DEFAULT_URL = "https://gestornormativo.creg.gov.co/gestor/entorno/docs/resolucion_minminas_40505_2025.htm"
CHUNK_SIZE = 2000  # Caracteres por fragmento (ajusta según tu RAM)
CHUNK_OVERLAP = 100  # Solapamiento para no perder contexto entre fragmentos


def split_text_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """
    Divide el texto en fragmentos manejables con solapamiento.
    
    Args:
        text: Texto completo a dividir
        chunk_size: Tamaño máximo de cada fragmento
        overlap: Caracteres de solapamiento entre fragmentos
        
    Returns:
        Lista de fragmentos de texto
    """
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap  # Retroceder para crear solapamiento
    
    return chunks


def extract_from_chunk(llm: ChatOllama, parser: PydanticOutputParser, chunk: str, chunk_num: int) -> News:
    """
    Extrae información de un fragmento específico.
    
    Args:
        llm: Modelo de lenguaje configurado
        parser: Parser de Pydantic
        chunk: Fragmento de texto a analizar
        chunk_num: Número del fragmento (para logging)
        
    Returns:
        News: Información extraída del fragmento
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "Eres un analista experto que extrae información estructurada de documentos. "
         "Identifica personas (nombres completos), empresas (razones sociales) y eventos relevantes. "
         "Debes responder exclusivamente con JSON válido que siga el siguiente esquema:\n{format_instructions}"),
        ("human",
         "Analiza el siguiente fragmento y extrae:\n"
         "- Personas: nombres de individuos mencionados\n"
         "- Empresas: organizaciones, compañías o entidades\n"
         "- Eventos: hechos, resoluciones, acuerdos o acontecimientos importantes\n\n"
         "FRAGMENTO:\n{content}")
    ]).partial(format_instructions=parser.get_format_instructions())

    chain = prompt | llm
    
    print(f"   Procesando fragmento {chunk_num}... ({len(chunk)} caracteres)")
    response = chain.invoke({"content": chunk})

    try:
        news = parser.parse(response.content)
    except Exception as parse_error:
        print(f"   ⚠️  Advertencia: Error parseando fragmento {chunk_num}, usando valores vacíos")
        news = News(companies=[], persons=[], events=[])
    
    return news


def merge_news_results(results: List[News]) -> News:
    """
    Combina múltiples resultados eliminando duplicados.
    
    Args:
        results: Lista de objetos News extraídos
        
    Returns:
        News: Resultado consolidado sin duplicados
    """
    all_companies = []
    all_persons = []
    all_events = []
    
    for result in results:
        all_companies.extend(result.companies)
        all_persons.extend(result.persons)
        all_events.extend(result.events)
    
    # Eliminar duplicados preservando orden y normalizando
    def deduplicate(items: List[str]) -> List[str]:
        seen = set()
        unique = []
        for item in items:
            item_normalized = item.strip().lower()
            if item_normalized and item_normalized not in seen:
                seen.add(item_normalized)
                unique.append(item.strip())
        return unique
    
    return News(
        companies=deduplicate(all_companies),
        persons=deduplicate(all_persons),
        events=deduplicate(all_events)
    )


def run_news_extraction(url: str = DEFAULT_URL) -> News:
    """
    Extrae información estructurada de una URL usando procesamiento por fragmentos.
    
    Args:
        url: URL del documento a analizar
        
    Returns:
        News: Objeto con personas, empresas y eventos extraídos
    """
    print(f"🌐 Cargando contenido de: {url}")
    
    # 1️⃣ Cargar contenido web
    loader = PlaywrightURLLoader(
        urls=[url],
        remove_selectors=["script", "style", "nav", "header", "footer", "aside", "iframe"]
    )
    docs = loader.load()
    content = docs[0].page_content if docs else ""
    
    print(f"✅ Contenido cargado: {len(content):,} caracteres")
    
    # 2️⃣ Dividir en fragmentos
    chunks = split_text_into_chunks(content)
    print(f"📦 Documento dividido en {len(chunks)} fragmentos de ~{CHUNK_SIZE:,} caracteres")
    
    # 3️⃣ Configurar modelo
    llm = ChatOllama(
        model=MODEL_NAME,
        temperature=0,
        format="json"
    )
    parser = PydanticOutputParser(pydantic_object=News)
    
    # 4️⃣ Procesar cada fragmento
    print("\n🤖 Procesando fragmentos...")
    results = []
    
    for i, chunk in enumerate(chunks, 1):
        try:
            news = extract_from_chunk(llm, parser, chunk, i)
            results.append(news)
        except Exception as e:
            print(f"   ❌ Error en fragmento {i}: {e}")
            # Continuar con los demás fragmentos
            continue
    
    # 5️⃣ Unificar resultados
    print(f"\n🔄 Unificando resultados de {len(results)} fragmentos...")
    final_news = merge_news_results(results)
    
    return final_news


if __name__ == "__main__":
    print("🚀 Iniciando extracción de noticias con procesamiento por fragmentos\n")
    print("📦 Requisitos: pip install langchain langchain-community playwright")
    print("🔧 Ejecuta: playwright install chromium\n")
    
    try:
        news = run_news_extraction()
        
        print("\n" + "="*60)
        print("📊 RESULTADOS CONSOLIDADOS")
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
