import asyncio
import json
import logging
from typing import List, Set
from pathlib import Path
from datetime import datetime

from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama
from langchain_community.document_loaders import PlaywrightURLLoader
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskID
from rich.table import Table
from rich.panel import Panel
from rich.logging import RichHandler

# --- 1. Configuración y Logging ---
logging.basicConfig(
    level="INFO", format="%(message)s", datefmt="[%X]", handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("NewsExtractor")
console = Console()

class Config:
    """Configuración centralizada del pipeline."""
    MODEL_NAME: str = "gpt-oss:latest"  # Asegúrate de tener este modelo o usa "llama3"
    DEFAULT_URL: str = "https://gestornormativo.creg.gov.co/gestor/entorno/docs/resolucion_minminas_40505_2025.htm"
    CHUNK_SIZE: int = 3000
    CHUNK_OVERLAP: int = 200
    MAX_CONCURRENCY: int = 4  # Número de fragmentos a procesar en paralelo (ajustar según VRAM)

# --- 2. Modelos de Datos ---

class News(BaseModel):
    """Esquema para la extracción por fragmento."""
    companies: List[str] = Field(default_factory=list, description="Empresas u organizaciones mencionadas")
    persons: List[str] = Field(default_factory=list, description="Nombres de personas mencionadas")
    events: List[str] = Field(default_factory=list, description="Eventos o hechos clave")

class ConsolidatedNews(BaseModel):
    """Esquema para el resultado final limpio y fusionado."""
    summary: str = Field(description="Breve resumen de 2 líneas de la noticia completa")
    companies: List[str] = Field(description="Lista única y normalizada de empresas")
    persons: List[str] = Field(description="Lista única y normalizada de personas")
    events: List[str] = Field(description="Lista cronológica o lógica de eventos principales")

# --- 3. Lógica Principal (Clase Extractor) ---

class NewsExtractor:
    def __init__(self, config: Config):
        self.cfg = config
        self.llm = ChatOllama(
            model=self.cfg.MODEL_NAME,
            temperature=0,
            format="json",
            keep_alive="5m" # Mantiene el modelo en memoria para velocidad
        )
        # Parser para fragmentos
        self.chunk_parser = PydanticOutputParser(pydantic_object=News)
        # Parser para consolidación final
        self.final_parser = PydanticOutputParser(pydantic_object=ConsolidatedNews)

    def load_content(self, url: str) -> str:
        """Carga el contenido web usando Playwright (Síncrono por limitación de loader)."""
        console.print(f"[cyan]🌐 Cargando URL:[/cyan] {url}")
        loader = PlaywrightURLLoader(
            urls=[url],
            remove_selectors=["script", "style", "nav", "footer", "iframe", ".ad", ".cookie"]
        )
        docs = loader.load()
        return docs[0].page_content if docs else ""

    def split_text(self, text: str) -> List[str]:
        """Divide el texto inteligentemente respetando oraciones."""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.cfg.CHUNK_SIZE,
            chunk_overlap=self.cfg.CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        chunks = splitter.split_text(text)
        console.print(f"[green]📦 Contenido dividido en {len(chunks)} fragmentos semánticos.[/green]")
        return chunks

    async def process_chunk(self, chunk: str, chunk_id: int, semaphore: asyncio.Semaphore, progress: Progress, task_id: TaskID) -> News:
        """Procesa un fragmento individual con control de concurrencia."""
        async with semaphore:  # Limita cuantos corren a la vez
            prompt = ChatPromptTemplate.from_messages([
                ("system", 
                 "Eres un extractor de datos preciso. Extrae entidades del texto proporcionado. "
                 "Si no hay datos en una categoría, devuelve una lista vacía. "
                 "Responde SOLO con JSON válido.\n{format_instructions}"),
                ("human", "Texto a analizar:\n{content}")
            ]).partial(format_instructions=self.chunk_parser.get_format_instructions())

            chain = prompt | self.llm
            
            try:
                response = await chain.ainvoke({"content": chunk})
                parsed_data = self.chunk_parser.parse(response.content)
                progress.advance(task_id)
                return parsed_data
            except Exception as e:
                logger.error(f"Error en fragmento {chunk_id}: {e}")
                progress.advance(task_id)
                return News()

    async def consolidate_results(self, raw_results: List[News]) -> ConsolidatedNews:
        """
        Toma todos los resultados crudos y usa el LLM para fusionar duplicados y limpiar.
        Ej: 'Ecopetrol' + 'Ecopetrol S.A.' -> 'Ecopetrol S.A.'
        """
        console.print("\n[yellow]🧠 Iniciando consolidación inteligente y resolución de entidades...[/yellow]")
        
        # Aplanar listas
        all_companies = set(c for r in raw_results for c in r.companies)
        all_persons = set(p for r in raw_results for p in r.persons)
        all_events = set(e for r in raw_results for e in r.events)

        # Crear contexto para el LLM
        context_data = {
            "raw_companies": list(all_companies),
            "raw_persons": list(all_persons),
            "raw_events": list(all_events)
        }

        prompt = ChatPromptTemplate.from_messages([
            ("system", 
             "Eres un editor jefe experto. Tu trabajo es limpiar y consolidar datos extraídos de fragmentos de una noticia.\n"
             "1. Deduplica entidades (ej: 'Juan Pérez' y 'J. Pérez' son la misma persona).\n"
             "2. Normaliza nombres de empresas (ej: usa el nombre oficial).\n"
             "3. Selecciona los eventos más relevantes y elimina redundancias.\n"
             "4. Genera un breve resumen.\n"
             "Salida JSON requerida:\n{format_instructions}"),
            ("human", 
             "Aquí están los datos crudos extraídos:\n"
             "Empresas Crudas: {raw_companies}\n"
             "Personas Crudas: {raw_persons}\n"
             "Eventos Crudos: {raw_events}\n\n"
             "Por favor, consolida y limpia esta información.")
        ]).partial(format_instructions=self.final_parser.get_format_instructions())

        chain = prompt | self.llm
        response = await chain.ainvoke(context_data)
        return self.final_parser.parse(response.content)

    async def run(self, url: str):
        content = self.load_content(url)
        if not content:
            console.print("[red]❌ No se pudo cargar el contenido.[/red]")
            return

        chunks = self.split_text(content)
        
        # Configurar barra de progreso
        semaphore = asyncio.Semaphore(self.cfg.MAX_CONCURRENCY)
        
        raw_results: List[News] = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
        ) as progress:
            task_id = progress.add_task("[cyan]Analizando fragmentos...", total=len(chunks))
            
            # Crear tareas asíncronas
            tasks = [
                self.process_chunk(chunk, i, semaphore, progress, task_id) 
                for i, chunk in enumerate(chunks)
            ]
            
            # Ejecutar en paralelo
            raw_results = await asyncio.gather(*tasks)

        # Fase de Consolidación
        final_news = await self.consolidate_results(raw_results)
        self.display_results(final_news)
        self.save_results(final_news)

    def display_results(self, news: ConsolidatedNews):
        console.print(Panel(f"[bold italic]{news.summary}[/bold italic]", title="📝 Resumen Ejecutivo", border_style="green"))

        # Tabla Personas
        table_p = Table(title="👥 Personas Identificadas", show_header=False, box=None)
        for p in news.persons: table_p.add_row(f"• {p}")
        console.print(table_p)

        # Tabla Empresas
        table_c = Table(title="🏢 Empresas / Entidades", show_header=False, box=None)
        for c in news.companies: table_c.add_row(f"• {c}")
        console.print(table_c)

        # Tabla Eventos
        table_e = Table(title="📅 Eventos Clave", show_header=False, box=None)
        for e in news.events: table_e.add_row(f"• {e}")
        console.print(table_e)

    def save_results(self, news: ConsolidatedNews):
        output_path = Path("smart_news_data.json")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(news.model_dump_json(indent=2))
        console.print(f"\n[bold blue]💾 Resultados guardados en: {output_path.resolve()}[/bold blue]")

# --- 4. Entry Point ---

if __name__ == "__main__":
    config = Config()
    extractor = NewsExtractor(config)
    
    console.print("[bold magenta]🚀 Iniciando Extractor de Noticias IA v2.0[/bold magenta]")
    
    try:
        asyncio.run(extractor.run(config.DEFAULT_URL))
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ Proceso interrumpido por el usuario.[/yellow]")
    except Exception as e:
        console.print_exception()