import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking import get_chunk_preset_options
from app.db.session import get_db
from app.schemas import KnowledgeBaseCreate
from app.services.knowledge_service import (
    DuplicateKnowledgeDocumentError,
    KnowledgeBaseNotFoundError,
    KnowledgeService,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/knowledge-chunk-presets")
async def list_knowledge_chunk_presets() -> list[dict]:
    return get_chunk_preset_options()


@router.get("/knowledge-bases")
async def list_knowledge_bases(
    user_key: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    logger.info("Knowledge bases list requested: user_key=%s", user_key)
    items = await KnowledgeService(db).list_knowledge_bases(user_key)
    logger.info("Knowledge bases list completed: user_key=%s count=%s", user_key, len(items))
    return items


@router.post("/knowledge-bases")
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    logger.info(
        "Knowledge base create requested: user_key=%s name=%s",
        payload.user_key,
        payload.name,
    )
    try:
        item = await KnowledgeService(db).create_knowledge_base(
            name=payload.name,
            description=payload.description,
            user_key=payload.user_key,
            chunk_preset_id=payload.chunk_preset_id,
            chunk_parser_config=payload.chunk_parser_config,
        )
        logger.info(
            "Knowledge base created: user_key=%s knowledge_base_id=%s name=%s",
            payload.user_key,
            item.get("id"),
            item.get("name"),
        )
        return item
    except ValueError as error:
        logger.warning(
            "Knowledge base create rejected: user_key=%s name=%s error=%s",
            payload.user_key,
            payload.name,
            error,
        )
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception:
        logger.exception("Knowledge base create failed: user_key=%s name=%s", payload.user_key, payload.name)
        raise


@router.get("/knowledge-bases/{knowledge_base_id}/documents")
async def list_knowledge_documents(
    knowledge_base_id: int,
    user_key: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    logger.info(
        "Knowledge documents list requested: user_key=%s knowledge_base_id=%s",
        user_key,
        knowledge_base_id,
    )
    try:
        documents = await KnowledgeService(db).list_documents(
            knowledge_base_id=knowledge_base_id,
            user_key=user_key,
        )
        logger.info(
            "Knowledge documents list completed: user_key=%s knowledge_base_id=%s count=%s",
            user_key,
            knowledge_base_id,
            len(documents),
        )
        return documents
    except ValueError as error:
        logger.warning(
            "Knowledge documents list rejected: user_key=%s knowledge_base_id=%s error=%s",
            user_key,
            knowledge_base_id,
            error,
        )
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception:
        logger.exception("Knowledge documents list failed: user_key=%s knowledge_base_id=%s", user_key, knowledge_base_id)
        raise


@router.post("/knowledge-bases/{knowledge_base_id}/documents")
async def upload_knowledge_document(
    knowledge_base_id: int,
    user_key: str = Query(default="default"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    logger.info(
        "Knowledge document upload requested: user_key=%s knowledge_base_id=%s filename=%s content_type=%s",
        user_key,
        knowledge_base_id,
        file.filename,
        file.content_type,
    )
    try:
        document = await KnowledgeService(db).upload_document(
            knowledge_base_id=knowledge_base_id,
            user_key=user_key,
            file=file,
        )
        logger.info(
            "Knowledge document upload completed: user_key=%s knowledge_base_id=%s document_id=%s status=%s",
            user_key,
            knowledge_base_id,
            document.get("id"),
            document.get("status"),
        )
        return document
    except KnowledgeBaseNotFoundError as error:
        logger.warning(
            "Knowledge document upload target not found: user_key=%s knowledge_base_id=%s filename=%s",
            user_key,
            knowledge_base_id,
            file.filename,
        )
        raise HTTPException(status_code=404, detail=str(error)) from error
    except DuplicateKnowledgeDocumentError as error:
        logger.warning(
            "Knowledge document upload conflict: user_key=%s knowledge_base_id=%s filename=%s",
            user_key,
            knowledge_base_id,
            file.filename,
        )
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        logger.warning(
            "Knowledge document upload rejected: user_key=%s knowledge_base_id=%s filename=%s error=%s",
            user_key,
            knowledge_base_id,
            file.filename,
            error,
        )
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception:
        logger.exception(
            "Knowledge document upload failed: user_key=%s knowledge_base_id=%s filename=%s",
            user_key,
            knowledge_base_id,
            file.filename,
        )
        raise


@router.get("/knowledge-documents/{document_id}/chunks")
async def list_knowledge_chunks(
    document_id: int,
    user_key: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    logger.info(
        "Knowledge chunks list requested: user_key=%s document_id=%s",
        user_key,
        document_id,
    )
    try:
        chunks = await KnowledgeService(db).list_chunks(document_id=document_id, user_key=user_key)
        logger.info(
            "Knowledge chunks list completed: user_key=%s document_id=%s count=%s",
            user_key,
            document_id,
            len(chunks),
        )
        return chunks
    except ValueError as error:
        logger.warning(
            "Knowledge chunks list rejected: user_key=%s document_id=%s error=%s",
            user_key,
            document_id,
            error,
        )
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception:
        logger.exception("Knowledge chunks list failed: user_key=%s document_id=%s", user_key, document_id)
        raise
