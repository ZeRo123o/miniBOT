import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.chunking import get_chunk_preset_options
from app.knowledge.parser import get_parser_health, get_parser_options
from app.db.session import AsyncSessionLocal, get_db
from app.schemas import KnowledgeBaseCreate, KnowledgeQueryConfigRequest, KnowledgeQueryTestRequest
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
from app.services.knowledge_service import (
    DuplicateKnowledgeDocumentError,
    KnowledgeBaseNotFoundError,
    KnowledgeResourceBusyError,
    KnowledgeService,
)
from app.storage.base import StorageUnavailableError

router = APIRouter()
logger = logging.getLogger(__name__)

DEFAULT_QUERY_PARAMS = {
    "search_mode": "hybrid",
    "final_top_k": 10,
    "recall_top_k": 50,
    "similarity_threshold": 0.0,
    "bm25_top_k": 50,
    "vector_weight": 0.7,
    "bm25_weight": 0.3,
    "bm25_drop_ratio_search": 0.0,
    "use_reranker": False,
    "reranker_model": None,
}


def _extract_query_options(metadata: dict | None) -> dict:
    query_params = (metadata or {}).get("query_params") or {}
    options = query_params.get("options") if isinstance(query_params, dict) else {}
    return options if isinstance(options, dict) else {}


async def process_knowledge_document(document_id: int) -> None:
    """Run document parsing and indexing after the upload response is sent."""
    async with AsyncSessionLocal() as db:
        await KnowledgeService(db).process_document(document_id)


@router.get("/knowledge-chunk-presets")
async def list_knowledge_chunk_presets() -> list[dict]:
    return get_chunk_preset_options()


@router.get("/knowledge-parsers")
async def list_knowledge_parsers() -> list[dict]:
    """Expose trusted parser metadata for knowledge-base configuration UIs."""

    return get_parser_options()


@router.get("/knowledge-parsers/{parser_id}/health")
async def check_knowledge_parser_health(parser_id: str) -> dict:
    """Check an external parser without parsing or storing a document."""

    try:
        return await get_parser_health(parser_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/knowledge-bases")
async def list_knowledge_bases(
    user_id: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    logger.info("Knowledge bases list requested: user_id=%s", user_id)
    items = await KnowledgeService(db).list_knowledge_bases(user_id)
    logger.info("Knowledge bases list completed: user_id=%s count=%s", user_id, len(items))
    return items


@router.post("/knowledge-bases")
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    logger.info(
        "Knowledge base create requested: user_id=%s name=%s",
        payload.user_id,
        payload.name,
    )
    try:
        item = await KnowledgeService(db).create_knowledge_base(
            name=payload.name,
            description=payload.description,
            user_id=payload.user_id,
            kb_type=payload.kb_type,
            chunk_preset_id=payload.chunk_preset_id,
            chunk_parser_config=payload.chunk_parser_config,
            parser_id=payload.parser_id,
            parser_config=payload.parser_config,
            embedding_model_spec=payload.embedding_model_spec,
            extraction_model_spec=payload.extraction_model_spec,
        )
        logger.info(
            "Knowledge base created: user_id=%s knowledge_base_id=%s name=%s",
            payload.user_id,
            item.get("id"),
            item.get("name"),
        )
        return item
    except ValueError as error:
        logger.warning(
            "Knowledge base create rejected: user_id=%s name=%s error=%s",
            payload.user_id,
            payload.name,
            error,
        )
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception:
        logger.exception("Knowledge base create failed: user_id=%s name=%s", payload.user_id, payload.name)
        raise


@router.delete("/knowledge-bases/{knowledge_base_id}")
async def delete_knowledge_base(
    knowledge_base_id: int,
    user_id: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a knowledge base only when none of its documents are processing."""
    try:
        await KnowledgeService(db).delete_knowledge_base(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
        )
        return {"message": "知识库删除成功"}
    except KnowledgeBaseNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except KnowledgeResourceBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/knowledge-bases/{knowledge_base_id}/documents")
async def list_knowledge_documents(
    knowledge_base_id: int,
    user_id: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    logger.info(
        "Knowledge documents list requested: user_id=%s knowledge_base_id=%s",
        user_id,
        knowledge_base_id,
    )
    try:
        documents = await KnowledgeService(db).list_documents(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
        )
        logger.info(
            "Knowledge documents list completed: user_id=%s knowledge_base_id=%s count=%s",
            user_id,
            knowledge_base_id,
            len(documents),
        )
        return documents
    except ValueError as error:
        logger.warning(
            "Knowledge documents list rejected: user_id=%s knowledge_base_id=%s error=%s",
            user_id,
            knowledge_base_id,
            error,
        )
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception:
        logger.exception("Knowledge documents list failed: user_id=%s knowledge_base_id=%s", user_id, knowledge_base_id)
        raise


@router.get("/knowledge-bases/{knowledge_base_id}/query-params")
async def get_knowledge_base_query_params(
    knowledge_base_id: int,
    user_id: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    knowledge_base = await KnowledgeService(db).base_repo.get(knowledge_base_id, user_id=user_id)
    if knowledge_base is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found.")
    options = {
        **DEFAULT_QUERY_PARAMS,
        **_extract_query_options(knowledge_base.metadata_),
    }
    return {"message": "success", "data": options}


@router.put("/knowledge-bases/{knowledge_base_id}/query-params")
async def update_knowledge_base_query_params(
    knowledge_base_id: int,
    payload: KnowledgeQueryConfigRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    knowledge_base = await KnowledgeService(db).base_repo.get(knowledge_base_id, user_id=payload.user_id)
    if knowledge_base is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found.")

    options = payload.model_dump(exclude={"user_id"})
    if not options.get("use_reranker"):
        options["reranker_model"] = None
    elif options.get("reranker_model") is not None:
        options["reranker_model"] = str(options["reranker_model"]).strip() or None

    metadata = dict(knowledge_base.metadata_ or {})
    query_params = dict(metadata.get("query_params") or {})
    query_params["options"] = {
        **(query_params.get("options") or {}),
        **options,
    }
    metadata["query_params"] = query_params
    await KnowledgeService(db).base_repo.update_metadata(knowledge_base, metadata)
    return {"message": "success", "data": query_params["options"]}


@router.post("/knowledge-bases/{knowledge_base_id}/query-test")
async def query_knowledge_base(
    knowledge_base_id: int,
    payload: KnowledgeQueryTestRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run an interactive retrieval test against one knowledge base."""
    logger.info(
        "Knowledge query test requested: user_id=%s knowledge_base_id=%s mode=%s final_top_k=%s",
        payload.user_id,
        knowledge_base_id,
        payload.search_mode,
        payload.final_top_k,
    )
    try:
        return await KnowledgeRetrievalService(db).query(
            user_id=payload.user_id,
            query=payload.query,
            knowledge_base_ids=[knowledge_base_id],
            search_mode=payload.search_mode,
            final_top_k=payload.final_top_k,
            recall_top_k=payload.recall_top_k,
            similarity_threshold=payload.similarity_threshold,
            bm25_top_k=payload.bm25_top_k,
            vector_weight=payload.vector_weight,
            bm25_weight=payload.bm25_weight,
            bm25_drop_ratio_search=payload.bm25_drop_ratio_search,
            include_distances=payload.include_distances,
            file_name=payload.file_name,
            use_reranker=payload.use_reranker,
            reranker_model=payload.reranker_model,
        )
    except ValueError as error:
        logger.warning(
            "Knowledge query test rejected: user_id=%s knowledge_base_id=%s error=%s",
            payload.user_id,
            knowledge_base_id,
            error,
        )
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/knowledge-bases/{knowledge_base_id}/documents")
async def upload_knowledge_document(
    knowledge_base_id: int,
    background_tasks: BackgroundTasks,
    user_id: str = Query(default="default"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    logger.info(
        "Knowledge document upload requested: user_id=%s knowledge_base_id=%s filename=%s content_type=%s",
        user_id,
        knowledge_base_id,
        file.filename,
        file.content_type,
    )
    try:
        document = await KnowledgeService(db).upload_document(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            file=file,
        )
        background_tasks.add_task(process_knowledge_document, document["id"])
        logger.info(
            "Knowledge document upload accepted: user_id=%s knowledge_base_id=%s document_id=%s status=%s",
            user_id,
            knowledge_base_id,
            document.get("id"),
            document.get("status"),
        )
        return document
    except KnowledgeBaseNotFoundError as error:
        logger.warning(
            "Knowledge document upload target not found: user_id=%s knowledge_base_id=%s filename=%s",
            user_id,
            knowledge_base_id,
            file.filename,
        )
        raise HTTPException(status_code=404, detail=str(error)) from error
    except DuplicateKnowledgeDocumentError as error:
        logger.warning(
            "Knowledge document upload conflict: user_id=%s knowledge_base_id=%s filename=%s",
            user_id,
            knowledge_base_id,
            file.filename,
        )
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        logger.warning(
            "Knowledge document upload rejected: user_id=%s knowledge_base_id=%s filename=%s error=%s",
            user_id,
            knowledge_base_id,
            file.filename,
            error,
        )
        raise HTTPException(status_code=422, detail=str(error)) from error
    except StorageUnavailableError as error:
        logger.warning(
            "Knowledge document upload storage unavailable: user_id=%s knowledge_base_id=%s filename=%s error=%s",
            user_id,
            knowledge_base_id,
            file.filename,
            error,
        )
        raise HTTPException(
            status_code=503,
            detail="Object storage is unavailable. Please start MinIO and retry the upload.",
        ) from error
    except Exception:
        logger.exception(
            "Knowledge document upload failed: user_id=%s knowledge_base_id=%s filename=%s",
            user_id,
            knowledge_base_id,
            file.filename,
        )
        raise


@router.get("/knowledge-documents/{document_id}/chunks")
async def list_knowledge_chunks(
    document_id: int,
    user_id: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    logger.info(
        "Knowledge chunks list requested: user_id=%s document_id=%s",
        user_id,
        document_id,
    )
    try:
        chunks = await KnowledgeService(db).list_chunks(document_id=document_id, user_id=user_id)
        logger.info(
            "Knowledge chunks list completed: user_id=%s document_id=%s count=%s",
            user_id,
            document_id,
            len(chunks),
        )
        return chunks
    except ValueError as error:
        logger.warning(
            "Knowledge chunks list rejected: user_id=%s document_id=%s error=%s",
            user_id,
            document_id,
            error,
        )
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception:
        logger.exception("Knowledge chunks list failed: user_id=%s document_id=%s", user_id, document_id)
        raise


@router.delete("/knowledge-documents/{document_id}")
async def delete_knowledge_document(
    document_id: int,
    user_id: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除文档元数据及其对应知识库后端索引。"""
    try:
        await KnowledgeService(db).delete_document(document_id=document_id, user_id=user_id)
        return {"message": "删除成功"}
    except KnowledgeResourceBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except StorageUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
