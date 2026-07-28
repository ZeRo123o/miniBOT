import inspect
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError
from pymilvus import DataType

from app.db.models import Base, KnowledgeBase
from app.knowledge.backends.milvus import (
    MilvusKnowledgeBackend,
    get_default_query_params,
    get_query_params_config,
)
from app.knowledge.chunking.ragflow_like.dispatcher import chunk_markdown
from app.knowledge.chunking.ragflow_like.presets import get_default_chunk_parser_config
from app.knowledge.graphs.extractors import (
    GraphExtractorFactory,
    LLMGraphExtractor,
)
from app.knowledge.graphs.extractors.base import (
    GraphExtractor,
    normalize_extraction_result,
)
from app.knowledge.graphs.graph_utils import (
    build_graph_payload,
    compute_entity_id,
    compute_triple_id,
    cypher_merge_chunk,
    cypher_merge_entity_mention,
    cypher_merge_relation,
    graph_entity_collection_name,
    graph_triple_collection_name,
    normalize_entity_name,
)
from app.knowledge.graphs import milvus_graph_service as graph_service_module
from app.knowledge.graphs.milvus_graph_service import MilvusGraphService
from app.knowledge.graphs.milvus_graph_vector_store import MilvusGraphVectorStore
from app.schemas import KnowledgeBaseCreate, KnowledgeGraphConfigRequest
from app.services.knowledge_service import KnowledgeService
from app.storage.neo4j import Neo4jConnectionManager, safe_neo4j_label


class KnowledgeGraphArchitectureTests(unittest.TestCase):
    def test_knowledge_base_uses_explicit_metadata_columns(self):
        columns = Base.metadata.tables["knowledge_bases"].columns.keys()
        self.assertTrue(
            {
                "kb_id",
                "embedding_model_spec",
                "llm_model_spec",
                "query_params",
                "additional_params",
                "share_config",
                "mindmap",
                "mindmap_file_ids",
                "mindmap_metadata",
                "sample_questions",
                "created_by",
            }.issubset(columns)
        )
        self.assertNotIn("metadata", columns)

    def test_knowledge_base_runtime_config_maps_to_explicit_columns(self):
        knowledge_base = KnowledgeBase(
            name="kb",
            user_id="user",
            created_by="user",
            embedding_model_spec="provider:embedding",
            llm_model_spec="provider:chat",
            query_params={"options": {"final_top_k": 5}},
            additional_params={"chunk_preset_id": "general"},
        )

        self.assertEqual(
            knowledge_base.runtime_metadata(),
            {
                "chunk_preset_id": "general",
                "embedding_model_spec": "provider:embedding",
                "extraction_model_spec": "provider:chat",
                "query_params": {"options": {"final_top_k": 5}},
            },
        )
        knowledge_base.apply_runtime_metadata(
            {
                "embedding_model_spec": "provider:new-embedding",
                "extraction_model_spec": "provider:new-chat",
                "query_params": {"options": {"final_top_k": 8}},
                "parser_id": "auto",
            }
        )
        self.assertEqual(knowledge_base.embedding_model_spec, "provider:new-embedding")
        self.assertEqual(knowledge_base.llm_model_spec, "provider:new-chat")
        self.assertEqual(knowledge_base.query_params["options"]["final_top_k"], 8)
        self.assertEqual(knowledge_base.additional_params, {"parser_id": "auto"})

    def test_graph_extractor_base_keeps_options_and_validation_hook(self):
        class ExampleExtractor(GraphExtractor):
            extractor_type = "example"

            async def extract(self, text, *, chunk_metadata=None):
                return {}

        default_extractor = ExampleExtractor()
        configured_extractor = ExampleExtractor({"schema": "example"})
        self.assertEqual(default_extractor.options, {})
        self.assertEqual(configured_extractor.options, {"schema": "example"})
        self.assertIsNone(configured_extractor.validate_options())

    def test_graph_metadata_tables_are_registered(self):
        expected = {
            "knowledge_graph_entities",
            "knowledge_graph_entity_mentions",
            "knowledge_graph_triples",
            "knowledge_graph_triple_mentions",
        }
        self.assertTrue(expected.issubset(Base.metadata.tables))

    def test_llm_extractor_builds_fixed_prompt_with_optional_schema(self):
        extractor = LLMGraphExtractor(
            {
                "model_spec": "chat",
                "schema": "只抽取软件组件",
            }
        )
        prompt = extractor._build_prompt("Alpha 包含 Beta")
        self.assertIn('"relations"', prompt)
        self.assertIn("抽取 Schema 约束", prompt)
        self.assertIn("只抽取软件组件", prompt)
        self.assertTrue(prompt.endswith("文本：\nAlpha 包含 Beta"))

    def test_llm_extractor_validates_options(self):
        invalid_options = (
            {},
            {"model_spec": "chat", "prompt": "custom"},
            {"model_spec": "chat", "concurrency_count": 0},
            {"model_spec": "chat", "concurrency_count": "invalid"},
            {"model_spec": "chat", "model_params": []},
        )
        for options in invalid_options:
            with self.subTest(options=options), self.assertRaises(ValueError):
                LLMGraphExtractor(options).validate_options()
        self.assertEqual(GraphExtractorFactory.supported_types(), ["llm"])
        self.assertIsInstance(
            GraphExtractorFactory.create("llm", {"model_spec": "chat"}),
            LLMGraphExtractor,
        )

    def test_extraction_normalization_resolves_entity_references(self):
        normalized = normalize_extraction_result(
            {
                "entities": [
                    {"id": "a", "text": "Alpha", "label": "Project"},
                    {"id": "b", "text": "Beta", "label": "Component"},
                ],
                "relations": [
                    {
                        "source": "a",
                        "target": "Beta",
                        "text": "Alpha contains Beta",
                        "label": "CONTAINS",
                    },
                ],
            },
            "llm",
        )
        self.assertEqual([item["text"] for item in normalized["entities"]], ["Alpha", "Beta"])
        self.assertEqual(normalized["relations"][0]["source"]["text"], "Alpha")
        self.assertEqual(normalized["metadata"]["extractor_type"], "llm")

    def test_graph_utils_match_reference_contract(self):
        self.assertEqual(normalize_entity_name("  Foo\t BAR\n"), "foo bar")
        self.assertEqual(
            compute_entity_id("kb-1", "alpha", "Person"),
            "c40ad7025838e7b26db3a00fe9178350",
        )
        self.assertEqual(
            compute_triple_id(
                "kb-1",
                "alpha",
                "Person",
                "KNOWS",
                "beta",
                "Person",
            ),
            "6ac2b5d70e55d19b29ea6f58fb2692a4",
        )
        self.assertEqual(graph_entity_collection_name("kb-1"), "kb_kb_1_entity")
        self.assertEqual(graph_triple_collection_name("kb-1"), "kb_kb_1_triple")
        self.assertEqual(graph_entity_collection_name("1"), "kb_1_entity")

    def test_graph_payload_merges_attributes_and_inline_entities(self):
        alpha = {
            "text": "Alpha",
            "label": "Project",
            "attributes": [{"text": "first", "label": "Description"}],
        }
        payload = build_graph_payload(
            {
                "entities": [
                    alpha,
                    {
                        "text": " alpha ",
                        "label": "Project",
                        "attributes": [
                            {"text": "first", "label": "Description"},
                            {"text": "active", "label": "Status"},
                        ],
                    },
                ],
                "relations": [
                    {
                        "source": alpha,
                        "target": {
                            "text": "Beta",
                            "label": "Component",
                            "attributes": [],
                        },
                        "text": "contains",
                        "label": "CONTAINS",
                    }
                ],
                "metadata": {"schema_version": 1},
            }
        )
        self.assertEqual([item["id"] for item in payload["entities"]], ["e1", "e2"])
        self.assertEqual(len(payload["entities"][0]["attributes"]), 2)
        self.assertEqual(payload["relations"][0]["source"], "e1")
        self.assertEqual(payload["relations"][0]["target"], "e2")
        self.assertEqual(payload["metadata"], {"schema_version": 1})
    def test_graph_cypher_templates_keep_write_contract(self):
        self.assertIn("Chunk:MilvusKB:`kb_label`", cypher_merge_chunk("kb_label"))
        entity_query = cypher_merge_entity_mention("kb_label")
        self.assertIn("MENTIONS", entity_query)
        self.assertIn("e.attributes_json = $attributes_json", entity_query)
        relation_query = cypher_merge_relation("kb_label")
        self.assertIn("RELATION", relation_query)
        self.assertIn("r.extractor_type", relation_query)

    def test_rrf_fusion_deduplicates_chunks(self):
        fused = MilvusKnowledgeBackend._fuse_chunk_rankings(
            [{"metadata": {"chunk_id": "a"}, "score": 0.9}],
            [
                {
                    "metadata": {"chunk_id": "a"},
                    "score": 1.0,
                    "graph_score": 2,
                },
                {"metadata": {"chunk_id": "b"}, "score": 0.5},
            ],
            graph_weight=1.0,
        )
        self.assertEqual(
            [item["metadata"]["chunk_id"] for item in fused],
            ["a", "b"],
        )
        self.assertEqual(fused[0]["fusion_sources"], ["chunk", "graph"])

    def test_personalized_pagerank_returns_chunk_nodes(self):
        ranked = MilvusGraphService.rank_chunks_by_ppr(
            {
                "nodes": [
                    {"id": "e1", "labels": ["Entity"], "entity_id": "entity-1"},
                    {"id": "c1", "labels": ["Chunk"], "chunk_id": "chunk-1"},
                    {"id": "e2", "labels": ["Entity"], "entity_id": "entity-2"},
                    {"id": "c2", "labels": ["Chunk"], "chunk_id": "chunk-2"},
                ],
                "edges": [
                    {"source_id": "e1", "target_id": "c1"},
                    {"source_id": "e1", "target_id": "e2"},
                    {"source_id": "e2", "target_id": "c2"},
                ],
            },
            {"entity-1": 1.0},
            top_k=2,
            damping=0.85,
        )
        self.assertEqual([chunk_id for chunk_id, _ in ranked], ["chunk-1", "chunk-2"])
        self.assertGreater(ranked[0][1], ranked[1][1])

    def test_personalized_pagerank_respects_document_chunk_filter(self):
        ranked = MilvusGraphService.rank_chunks_by_ppr(
            {
                "nodes": [
                    {"id": "e1", "labels": ["Entity"], "entity_id": "entity-1"},
                    {"id": "c1", "labels": ["Chunk"], "chunk_id": "chunk-1"},
                    {"id": "c2", "labels": ["Chunk"], "chunk_id": "chunk-2"},
                ],
                "edges": [
                    {"source_id": "e1", "target_id": "c1"},
                    {"source_id": "e1", "target_id": "c2"},
                ],
            },
            {"entity-1": 1.0},
            top_k=2,
            damping=0.85,
            allowed_chunk_ids={"chunk-2"},
        )
        self.assertEqual([chunk_id for chunk_id, _ in ranked], ["chunk-2"])

    def test_unknown_create_field_is_rejected(self):
        with self.assertRaises(ValidationError):
            KnowledgeBaseCreate(
                name="test",
                embedding_model_spec="embedding",
                obsolete_backend="unused",
            )

    def test_knowledge_base_creation_does_not_require_graph_model(self):
        payload = KnowledgeBaseCreate(
            name="test",
            embedding_model_spec="embedding",
        )
        self.assertFalse(hasattr(payload, "extraction_model_spec"))

    def test_graph_configuration_is_confirmed_separately(self):
        payload = KnowledgeGraphConfigRequest(
            model_spec="provider:chat",
            concurrency_count=4,
        )
        self.assertEqual(payload.extractor_type, "llm")
        self.assertEqual(payload.model_spec, "provider:chat")
        process_source = inspect.getsource(KnowledgeService.process_document)
        self.assertNotIn("graph_metadata", process_source)
        self.assertNotIn("MilvusGraphService(self.base_repo.db).index_document", process_source)


class LLMGraphExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def test_extract_uses_model_options_and_repairs_json(self):
        class FakeResponse:
            content = "{relations: [{source: {text: Alpha}, target: {text: Beta}, text: contains}]}"

        class FakeModel:
            def bind(self, **kwargs):
                self.bound_params = kwargs
                return self

            async def ainvoke(self, messages):
                self.messages = messages
                return FakeResponse()

        model = FakeModel()
        extractor = LLMGraphExtractor(
            {
                "model_spec": "chat",
                "model_params": {"temperature": 0},
            }
        )
        with patch(
            "app.knowledge.graphs.extractors.llm.get_model_by_spec",
            return_value=model,
        ) as model_factory:
            result = await extractor.extract("Alpha contains Beta")

        model_factory.assert_called_once_with("chat")
        self.assertEqual(model.bound_params, {"temperature": 0})
        self.assertEqual(result["relations"][0]["source"]["text"], "Alpha")
        self.assertIn("文本：\nAlpha contains Beta", model.messages[0].content)


class KnowledgeGraphSeedTests(unittest.IsolatedAsyncioTestCase):
    async def test_chunk_graph_write_uses_plain_snapshot(self):
        service = object.__new__(MilvusGraphService)
        service._write_chunk_to_neo4j = AsyncMock()
        chunk = {
            "chunk_id": "4_chunk_0",
            "document_id": 4,
            "chunk_index": 0,
            "content": "Alpha contains Beta",
            "start_char_pos": 0,
            "end_char_pos": 19,
            "metadata": {},
        }
        normalized = normalize_extraction_result(
            {
                "relations": [
                    {
                        "source": {"text": "Alpha", "label": "Project"},
                        "target": {"text": "Beta", "label": "Component"},
                        "text": "contains",
                        "label": "CONTAINS",
                    }
                ]
            },
            "llm",
        )

        entities, triples = await service.write_chunk_graph("4", chunk, normalized)

        self.assertEqual(len(entities), 2)
        self.assertEqual(len(triples), 1)
        self.assertIs(
            service._write_chunk_to_neo4j.await_args.kwargs["chunk"],
            chunk,
        )

    async def test_seed_weights_combine_graph_hits_and_base_chunks(self):
        class FakeRepository:
            async def list_entity_ids_by_chunk_ids(self, chunk_ids):
                self.requested_chunk_ids = chunk_ids
                return {"chunk-1": ["base-entity"]}

        service = object.__new__(MilvusGraphService)
        service.repo = FakeRepository()
        weights = await service._build_seed_weights(
            base_chunks=[
                {
                    "metadata": {"chunk_id": "chunk-1"},
                    "score": 0.5,
                }
            ],
            entity_hits=[{"id": "entity-hit", "score": 0.9}],
            triple_hits=[
                {
                    "source_id": "source-hit",
                    "target_id": "target-hit",
                    "score": 0.5,
                }
            ],
        )

        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertAlmostEqual(
            weights["entity-hit"] / weights["source-hit"],
            0.9 / (0.5 * 0.8),
        )
        self.assertAlmostEqual(
            weights["base-entity"] / weights["source-hit"],
            (0.5 * 0.3) / (0.5 * 0.8),
        )

    async def test_primary_retrieval_finishes_before_graph_retrieval(self):
        call_order = []
        primary_results = [
            {
                "metadata": {"chunk_id": "chunk-1"},
                "score": 0.8,
            }
        ]

        async def primary_query(**kwargs):
            call_order.append("primary")
            return primary_results

        async def graph_query(**kwargs):
            self.assertEqual(call_order, ["primary"])
            self.assertIs(kwargs["base_chunks"], primary_results)
            self.assertEqual(kwargs["document_ids"], [1])
            call_order.append("graph")
            return []

        backend = MilvusKnowledgeBackend()
        backend._search_chunks = primary_query
        backend._retrieve_graph_chunks = graph_query
        await backend.query(
            knowledge_base_id=1,
            query_text="query",
            search_mode="keyword",
            final_top_k=10,
            recall_top_k=10,
            similarity_threshold=0.0,
            bm25_top_k=10,
            vector_weight=0.7,
            bm25_weight=0.3,
            bm25_drop_ratio_search=0.0,
            include_distances=True,
            document_ids=[1],
            use_graph_retrieval=True,
            graph_entity_top_k=10,
            graph_triple_top_k=10,
            graph_top_k=20,
            graph_max_nodes=10000,
            ppr_damping=0.85,
            graph_weight=1.0,
            db_session=Mock(),
        )

        self.assertEqual(call_order, ["primary", "graph"])

    async def test_entity_and_triple_retrieval_run_in_parallel(self):
        both_started = asyncio.Event()
        started: set[str] = set()

        async def mark_started(name: str, result: list[dict]):
            started.add(name)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)
            return result

        class FakeVectorStore:
            async def search_entities(self, **kwargs):
                return await mark_started(
                    "entity",
                    [{"id": "entity-1", "score": 1.0}],
                )

            async def search_triples(self, **kwargs):
                return await mark_started("triple", [])

        class FakeRepository:
            async def list_entity_ids_by_chunk_ids(self, chunk_ids):
                return {}

        class FakeChunkRepository:
            async def list_by_chunk_ids(self, chunk_ids):
                return []

        service = object.__new__(MilvusGraphService)
        service._graph_vector_store = FakeVectorStore()
        service.repo = FakeRepository()
        service.chunk_repo = FakeChunkRepository()
        service._query_seed_subgraph_from_neo4j = AsyncMock(
            return_value={"nodes": [], "edges": []}
        )

        await service.search(
            knowledge_base_id=1,
            query="问题",
            base_chunks=[],
            metadata={"embedding_model_spec": "embedding"},
            entity_top_k=10,
            triple_top_k=10,
            graph_top_k=20,
            graph_max_nodes=1000,
            ppr_damping=0.85,
        )

        self.assertEqual(started, {"entity", "triple"})


class MilvusKnowledgeBackendTests(unittest.IsolatedAsyncioTestCase):
    def test_query_config_has_one_authoritative_default_set(self):
        defaults = get_default_query_params()
        with patch(
            "app.knowledge.backends.milvus.model_cache.get_all_specs",
            return_value=[],
        ):
            config = get_query_params_config()

        self.assertEqual(defaults["search_mode"], "vector")
        self.assertFalse(defaults["use_graph_retrieval"])
        self.assertFalse(defaults["use_reranker"])
        self.assertEqual(
            {option["key"] for option in config["options"]},
            set(defaults),
        )

    async def test_keyword_query_does_not_call_embedding_service(self):
        backend = MilvusKnowledgeBackend()
        backend._search_chunks = AsyncMock(return_value=[])

        with patch(
            "app.knowledge.backends.milvus.get_embedding_service",
            side_effect=AssertionError("keyword search must not embed the query"),
        ):
            result = await backend.query(
                knowledge_base_id=1,
                query_text="关键词",
                search_mode="keyword",
                final_top_k=10,
                recall_top_k=50,
            )

        self.assertEqual(result, [])
        self.assertEqual(backend._search_chunks.await_count, 1)

    async def test_document_indexing_deletes_once_and_inserts_in_batches(self):
        backend = MilvusKnowledgeBackend()
        backend.delete_document_chunks = AsyncMock()
        chunks = [
            {
                "chunk_id": f"chunk-{index}",
                "chunk_index": index,
                "content": f"content-{index}",
            }
            for index in range(201)
        ]
        embedding_service = SimpleNamespace(
            model_name="embedding",
            dimension=3,
            embed_texts=AsyncMock(
                side_effect=lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
            ),
        )

        with (
            patch(
                "app.knowledge.backends.milvus.get_embedding_service",
                return_value=embedding_service,
            ),
            patch(
                "app.knowledge.backends.milvus.run_milvus_io",
                new=AsyncMock(),
            ) as milvus_io,
        ):
            result = await backend.index_document(
                knowledge_base_id=1,
                document_id=2,
                chunks=chunks,
                knowledge_base_metadata={"embedding_model_spec": "provider:model"},
            )

        backend.delete_document_chunks.assert_awaited_once()
        self.assertEqual(embedding_service.embed_texts.await_count, 2)
        self.assertEqual(milvus_io.await_count, 2)
        self.assertEqual(result["embedding_count"], 201)

    def test_collection_compatibility_checks_model_dimension_and_bm25(self):
        backend = MilvusKnowledgeBackend()
        backend._client = SimpleNamespace(
            describe_collection=Mock(
                return_value={
                    "description": (
                        "miniBOT knowledge base 1; embedding_model=embedding-a; "
                        "schema=single_chunk_v1"
                    ),
                    "fields": [
                        {
                            "name": "content",
                            "params": {"enable_analyzer": True},
                        },
                        {"name": "content_sparse", "params": {}},
                        {"name": "embedding", "params": {"dim": 1024}},
                    ],
                }
            )
        )

        self.assertTrue(
            backend._collection_is_compatible(
                "kb_1",
                dimension=1024,
                embedding_model="embedding-a",
            )
        )
        self.assertFalse(
            backend._collection_is_compatible(
                "kb_1",
                dimension=768,
                embedding_model="embedding-a",
            )
        )
        self.assertFalse(
            backend._collection_is_compatible(
                "kb_1",
                dimension=1024,
                embedding_model="embedding-b",
            )
        )


class Neo4jStorageTests(unittest.IsolatedAsyncioTestCase):
    def test_safe_label_accepts_identifiers_and_rejects_cypher_fragments(self):
        self.assertEqual(safe_neo4j_label("kb_123"), "kb_123")
        with self.assertRaises(ValueError):
            safe_neo4j_label("kb_1`) MATCH (n) DETACH DELETE n")

    async def test_connection_manager_creates_verifies_and_closes_driver(self):
        fake_driver = SimpleNamespace(
            verify_connectivity=AsyncMock(),
            close=AsyncMock(),
        )
        manager = Neo4jConnectionManager(
            uri="bolt://example:7687",
            username="neo4j",
            password="secret",
        )

        with patch(
            "app.storage.neo4j.manager.AsyncGraphDatabase.driver",
            return_value=fake_driver,
        ) as create_driver:
            self.assertEqual(manager.status, "closed")
            self.assertIs(await manager.connect(), fake_driver)
            create_driver.assert_called_once_with(
                "bolt://example:7687",
                auth=("neo4j", "secret"),
            )
            fake_driver.verify_connectivity.assert_awaited_once()
            self.assertTrue(manager.is_running())
            await manager.close()

        fake_driver.close.assert_awaited_once()
        self.assertEqual(manager.status, "closed")


class MilvusGraphServiceContractTests(unittest.IsolatedAsyncioTestCase):
    def test_service_owns_neo4j_operations_without_extra_store_layer(self):
        module_source = inspect.getsource(graph_service_module)

        self.assertNotIn("class _Neo4jGraphStore", module_source)
        self.assertNotIn("self.neo4j", module_source)
        self.assertIn("neo4j_connection", inspect.signature(MilvusGraphService).parameters)

    def test_service_exposes_graph_build_and_browse_contract(self):
        expected_methods = {
            "get_status",
            "configure",
            "build_pending_chunks",
            "write_chunk_graph",
            "reset",
            "delete_graph",
            "delete_file_graph",
            "query_nodes",
            "query_seed_subgraph",
            "query_and_rank_chunks_by_ppr",
            "get_labels",
            "get_stats",
        }
        self.assertTrue(
            expected_methods.issubset(
                {
                    name
                    for name, value in inspect.getmembers(
                        MilvusGraphService,
                        predicate=callable,
                    )
                }
            )
        )

    def test_chunk_model_contains_persistent_graph_build_state(self):
        chunk_table = Base.metadata.tables["knowledge_chunks"]
        self.assertTrue(
            {"graph_indexed", "ent_ids", "extraction_result"}.issubset(
                chunk_table.columns.keys()
            )
        )
        self.assertNotIn("chunk_type", chunk_table.columns)
        self.assertNotIn("parent_chunk_id", chunk_table.columns)

    def test_markdown_chunking_produces_single_level_chunks(self):
        markdown = "# 标题\n\n第一段内容。\n\n第二段内容。"
        chunks = chunk_markdown(
            markdown,
            file_id="doc-1",
            filename="demo.md",
            preset_id="general",
            parser_config={"chunk_token_num": 8, "overlapped_percent": 0},
        )

        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(
            [chunk["chunk_id"] for chunk in chunks],
            [f"doc-1_chunk_{index}" for index in range(len(chunks))],
        )
        self.assertTrue(all("chunk_type" not in chunk for chunk in chunks))
        self.assertTrue(all("parent_chunk_id" not in chunk for chunk in chunks))

    def test_non_qa_chunk_presets_default_to_512_tokens(self):
        """非问答预设统一使用 512 个近似 token 作为目标块大小。"""
        for preset_id in ("general", "book", "laws", "separator"):
            config = get_default_chunk_parser_config(preset_id)
            self.assertEqual(config["chunk_token_num"], 512)
            self.assertEqual(config["overlapped_percent"], 0)

    async def test_get_status_combines_config_chunk_and_graph_counts(self):
        knowledge_base = SimpleNamespace(
            additional_params={
                "graph_build_config": {
                    "locked": True,
                    "extractor_type": "llm",
                    "extractor_options": {"model_spec": "chat"},
                },
                "graph_build_task": {
                    "task_id": "graph_test",
                    "status": "running",
                    "progress": 42,
                    "message": "图谱构建 3/10",
                },
            },
        )
        knowledge_base.runtime_metadata = lambda: dict(knowledge_base.additional_params)

        class FakeKnowledgeBaseRepository:
            async def get(self, knowledge_base_id):
                return knowledge_base

        class FakeChunkRepository:
            async def count_by_knowledge_base(self, knowledge_base_id):
                return 10

            async def count_graph_pending_by_knowledge_base(self, knowledge_base_id):
                return 3

            async def count_graph_indexed_by_knowledge_base(self, knowledge_base_id):
                return 7

        class FakeGraphRepository:
            async def count_by_knowledge_base(self, knowledge_base_id):
                return 5, 4

        service = object.__new__(MilvusGraphService)
        service.kb_repo = FakeKnowledgeBaseRepository()
        service.chunk_repo = FakeChunkRepository()
        service.repo = FakeGraphRepository()
        status = await service.get_status("1")
        self.assertTrue(status["configured"])
        self.assertTrue(status["locked"])
        self.assertEqual(status["total_chunks"], 10)
        self.assertEqual(status["pending_chunks"], 3)
        self.assertEqual(status["entity_count"], 5)
        self.assertEqual(status["relationship_count"], 4)
        self.assertEqual(status["build_task_status"], "running")
        self.assertEqual(status["build_task_progress"], 42)

    async def test_configure_locks_extractor_type_and_allows_option_updates(self):
        knowledge_base = SimpleNamespace(additional_params={})
        knowledge_base.runtime_metadata = lambda: dict(knowledge_base.additional_params)

        class FakeKnowledgeBaseRepository:
            async def get(self, knowledge_base_id):
                return knowledge_base

            async def update_metadata(self, item, metadata):
                item.additional_params = metadata

        service = object.__new__(MilvusGraphService)
        service.kb_repo = FakeKnowledgeBaseRepository()
        config = await service.configure(
            "1",
            "llm",
            {"model_spec": "chat", "concurrency_count": 2},
            "tester",
        )
        self.assertTrue(config["locked"])
        self.assertEqual(config["created_by"], "tester")
        updated = await service.configure(
            "1",
            "llm",
            {"model_spec": "another-chat"},
            "tester",
        )
        self.assertEqual(
            updated["extractor_options"]["model_spec"],
            "another-chat",
        )
        with self.assertRaises(ValueError):
            await service.configure(
                "1",
                "another",
                {"model_spec": "chat"},
                "tester",
            )

    def test_worker_count_and_public_config_hide_custom_prompt(self):
        config = {
            "locked": True,
            "extractor_type": "llm",
            "extractor_options": {
                "model_spec": "chat",
                "concurrency_count": 5000,
                "prompt": "not public",
            },
        }
        service = object.__new__(MilvusGraphService)
        self.assertEqual(service._get_worker_count(config), 1000)
        public = service._public_config(config)
        self.assertNotIn("prompt", public["extractor_options"])


class MilvusGraphVectorStoreTests(unittest.IsolatedAsyncioTestCase):
    def test_public_method_contract_matches_incremental_store(self):
        insert_parameters = inspect.signature(
            MilvusGraphVectorStore.insert_missing_graph_records
        ).parameters
        self.assertEqual(
            list(insert_parameters),
            [
                "self",
                "kb_id",
                "embedding_model_spec",
                "entities",
                "triples",
            ],
        )
        search_parameters = inspect.signature(
            MilvusGraphVectorStore.search_entities
        ).parameters
        self.assertEqual(
            list(search_parameters),
            [
                "self",
                "kb_id",
                "query_text",
                "embedding_model_spec",
                "top_k",
            ],
        )

    def test_entity_collection_schema_and_indexes_match_contract(self):
        store = object.__new__(MilvusGraphVectorStore)
        client = Mock()
        client.has_collection.return_value = False
        store._connect = Mock(return_value=client)
        schema = Mock()
        indexes = Mock()
        with (
            patch(
                "app.knowledge.graphs.milvus_graph_vector_store."
                "MilvusClient.create_schema",
                return_value=schema,
            ),
            patch(
                "app.knowledge.graphs.milvus_graph_vector_store."
                "MilvusClient.prepare_index_params",
                return_value=indexes,
            ),
        ):
            collection_name = store._get_or_create_entity_collection(
                "kb-1",
                1024,
                "embedding-model",
            )

        self.assertEqual(collection_name, "kb_kb_1_entity")
        field_names = [
            call.kwargs["field_name"] for call in schema.add_field.call_args_list
        ]
        self.assertEqual(
            field_names,
            ["id", "content", "embedding", "content_sparse"],
        )
        id_call = schema.add_field.call_args_list[0].kwargs
        self.assertEqual(id_call["datatype"], DataType.VARCHAR)
        self.assertEqual(id_call["max_length"], 100)
        self.assertTrue(id_call["is_primary"])
        content_call = schema.add_field.call_args_list[1].kwargs
        self.assertTrue(content_call["enable_analyzer"])
        self.assertEqual(content_call["analyzer_params"], {"type": "chinese"})
        schema.add_function.assert_called_once()
        dense_index = indexes.add_index.call_args_list[0].kwargs
        sparse_index = indexes.add_index.call_args_list[1].kwargs
        self.assertEqual(dense_index["params"], {"nlist": 1024})
        self.assertEqual(sparse_index["metric_type"], "BM25")

    async def test_non_positive_top_k_does_not_embed(self):
        store = object.__new__(MilvusGraphVectorStore)
        store._has_collection = Mock(return_value=True)
        with patch(
            "app.knowledge.graphs.milvus_graph_vector_store.get_embedding_service"
        ) as embedding_factory:
            results = await store.search_entities(
                kb_id="kb-1",
                query_text="query",
                embedding_model_spec="embedding",
                top_k=0,
            )
        self.assertEqual(results, [])
        embedding_factory.assert_not_called()

    async def test_missing_collection_returns_without_embedding(self):
        store = object.__new__(MilvusGraphVectorStore)
        store._has_collection = Mock(return_value=False)
        with patch(
            "app.knowledge.graphs.milvus_graph_vector_store.get_embedding_service"
        ) as embedding_factory:
            results = await store.search_triples(
                kb_id="kb-1",
                query_text="query",
                embedding_model_spec="unavailable",
                top_k=10,
            )
        self.assertEqual(results, [])
        embedding_factory.assert_not_called()

    async def test_empty_insert_does_not_resolve_embedding_model(self):
        store = object.__new__(MilvusGraphVectorStore)
        with patch(
            "app.knowledge.graphs.milvus_graph_vector_store.get_embedding_service"
        ) as embedding_factory:
            await store.insert_missing_graph_records(
                kb_id="kb-1",
                embedding_model_spec="embedding",
                entities=[],
                triples=[],
            )
        embedding_factory.assert_not_called()
if __name__ == "__main__":
    unittest.main()
