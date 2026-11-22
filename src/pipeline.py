
from src.ingestion.fetcher import fetch_page
from src.ingestion.page_validator import validate_page
from src.extraction.parser import parse_page
from src.extraction.schemas import AnalysisRequest, AnalysisStatus
from src.extraction.llm_client import GroqClient
from src.storage.sqlite import (
    init_db,
    save_snapshot,
    get_latest_snapshot,
)


def run_pipeline(
    url: str,
    product_description: str,
    significance_criteria: list[str],
    previous_snapshot_override=None,
    *,
    fetcher=fetch_page,
    analyzer_factory=GroqClient,
    persist: bool = True,
) :
    """Fetch and analyze one product page.

    Fixture runners can provide a fetcher and disable persistence. A bad page
    or oversized context raises before the snapshot is changed.
    """
    if persist:
        init_db()

    # 1. Загружаем страницу
    html = fetcher(url)
    valid, reason = validate_page(html)
    if not valid:
        raise RuntimeError(f"Page validation failed: {reason}")
    parsed_data = parse_page(html)
    # The KT2 estimate is about 30k input tokens per page. At roughly four
    # characters per token, 100k characters leaves room for instructions,
    # metadata, and the previous snapshot. Refuse instead of silently losing
    # a price or availability field near the end of a long page.
    if len(parsed_data["text"]) > 100_000:
        raise RuntimeError("Page text exceeds the 100000-character context budget")

    # 2. Получаем предыдущий снимок
    if previous_snapshot_override is not None:
        previous_snapshot = previous_snapshot_override
    elif persist:
        previous_snapshot = get_latest_snapshot(url)
    else:
        previous_snapshot = None

    # 3. Формируем запрос к модели
    request = AnalysisRequest(
        source_url=url,
        product_description=product_description,
        page_title=parsed_data["title"],
        page_text=parsed_data["text"],
        previous_snapshot=previous_snapshot,
        significance_criteria=significance_criteria,
    )

    # 4. Анализируем страницу
    llm = analyzer_factory()
    
    result = llm.analyze(request)
    if previous_snapshot is None:
        if result.status != AnalysisStatus.INITIALIZED:
            raise ValueError("Expected INITIALIZED status for a new product")
    elif result.status == AnalysisStatus.INITIALIZED:
        raise ValueError("Unexpected INITIALIZED status for an existing product")
    # 5. Сохраняем новый снимок, если анализ не вызвал сомнений
    if (
        result.current_snapshot is not None
        and result.status != AnalysisStatus.UNCERTAIN
    ):
        if persist:
            save_snapshot(result.current_snapshot)

    return result
