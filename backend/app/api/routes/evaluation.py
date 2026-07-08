from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.evaluation_service import EvaluationService

router = APIRouter()


class RunEvaluationRequest(BaseModel):
    user_id: str = Field(default="default", min_length=1, max_length=128)
    dataset_id: str = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    retrieval_config: dict[str, Any] = Field(default_factory=dict, alias="model_config")


class GenerateEvaluationDatasetRequest(BaseModel):
    user_id: str = Field(default="default", min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=255)
    description: str = Field(default="", max_length=2000)
    count: int = Field(default=10, ge=1, le=100)
    candidate_chunk_count: int = Field(default=2, ge=0, le=7)
    llm_model_spec: str | None = Field(default=None, min_length=1, max_length=255)
    concurrency_count: int = Field(default=4, ge=1, le=10)


@router.post("/knowledge-bases/{knowledge_base_id}/evaluation/datasets/upload")
async def upload_evaluation_dataset(
    knowledge_base_id: int,
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    user_id: str = Form("default"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not (file.filename or "").lower().endswith(".jsonl"):
        raise HTTPException(status_code=400, detail="仅支持 JSONL 格式文件")
    try:
        data = await EvaluationService(db).upload_dataset(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            file_content=await file.read(),
            filename=file.filename or "",
            name=name,
            description=description,
        )
        return {"message": "success", "data": data}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/knowledge-bases/{knowledge_base_id}/evaluation/datasets/generate")
async def generate_evaluation_dataset(
    knowledge_base_id: int,
    payload: GenerateEvaluationDatasetRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        data = await EvaluationService(db).generate_dataset(
            knowledge_base_id=knowledge_base_id,
            user_id=payload.user_id,
            name=payload.name,
            description=payload.description,
            count=payload.count,
            context_count=payload.candidate_chunk_count + 1,
            concurrency_count=payload.concurrency_count,
            llm_model_spec=payload.llm_model_spec,
        )
        return {"message": "success", "data": data}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/knowledge-bases/{knowledge_base_id}/evaluation/datasets")
async def list_evaluation_datasets(
    knowledge_base_id: int,
    user_id: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        data = await EvaluationService(db).list_datasets(knowledge_base_id, user_id)
        return {"message": "success", "data": data}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/knowledge-bases/{knowledge_base_id}/evaluation/datasets/{dataset_id}")
async def get_evaluation_dataset(
    knowledge_base_id: int,
    dataset_id: str,
    user_id: str = Query(default="default"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        data = await EvaluationService(db).get_dataset_detail(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            dataset_id=dataset_id,
            page=page,
            page_size=page_size,
        )
        return {"message": "success", "data": data}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/evaluation/datasets/{dataset_id}")
async def delete_evaluation_dataset(
    dataset_id: str,
    user_id: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await EvaluationService(db).delete_dataset(dataset_id=dataset_id, user_id=user_id)
        return {"message": "success", "data": None}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/knowledge-bases/{knowledge_base_id}/evaluation/runs")
async def run_evaluation(
    knowledge_base_id: int,
    payload: RunEvaluationRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        data = await EvaluationService(db).run_evaluation(
            knowledge_base_id=knowledge_base_id,
            user_id=payload.user_id,
            dataset_id=payload.dataset_id,
            name=payload.name,
            model_config=payload.retrieval_config,
        )
        return {"message": "success", "data": data}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/knowledge-bases/{knowledge_base_id}/evaluation/runs")
async def list_evaluation_runs(
    knowledge_base_id: int,
    user_id: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        data = await EvaluationService(db).list_runs(knowledge_base_id, user_id)
        return {"message": "success", "data": data}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/knowledge-bases/{knowledge_base_id}/evaluation/runs/{run_id}")
async def get_evaluation_run_results(
    knowledge_base_id: int,
    run_id: str,
    user_id: str = Query(default="default"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    error_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        data = await EvaluationService(db).get_run_results(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            run_id=run_id,
            page=page,
            page_size=page_size,
            error_only=error_only,
        )
        return {"message": "success", "data": data}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/knowledge-bases/{knowledge_base_id}/evaluation/runs/{run_id}")
async def delete_evaluation_run(
    knowledge_base_id: int,
    run_id: str,
    user_id: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await EvaluationService(db).delete_run(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            run_id=run_id,
        )
        return {"message": "success", "data": None}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
