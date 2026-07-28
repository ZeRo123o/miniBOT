"""知识图谱构建使用的纯函数。

数据转换和 Cypher 模板集中在这里，图服务只负责 I/O 与流程编排。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.storage.neo4j import safe_neo4j_label


def _stable_hash(value: str, length: int = 32) -> str:
    """生成固定长度的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[
        :length
    ]


def normalize_entity_name(text: str) -> str:
    """去除首尾空白、转为小写并压缩内部连续空白。"""
    return " ".join(text.strip().lower().split())


def compute_entity_id(kb_id: str, normalized_name: str, label: str) -> str:
    return _stable_hash(f"{kb_id}:{normalized_name}:{label}")


def compute_triple_id(
    kb_id: str,
    source_normalized_name: str,
    source_label: str,
    relation_type: str,
    target_normalized_name: str,
    target_label: str,
) -> str:
    return _stable_hash(
        f"{kb_id}:{source_normalized_name}:{source_label}:"
        f"{relation_type}:{target_normalized_name}:{target_label}"
    )


def graph_entity_collection_name(kb_id: str) -> str:
    return f"kb_{_safe_collection_fragment(kb_id)}_entity"


def graph_triple_collection_name(kb_id: str) -> str:
    return f"kb_{_safe_collection_fragment(kb_id)}_triple"


def _safe_collection_fragment(value: str) -> str:
    """把业务 ID 转换为 Milvus collection 可接受的名称片段。"""
    normalized = re.sub(r"[^0-9A-Za-z_]", "_", str(value)).strip("_")
    return normalized or "default"


def build_graph_payload(normalized_result: dict[str, Any]) -> dict[str, Any]:
    """把标准化抽取结果转换为 Neo4j 写入结构。

    相同名称和标签的实体只保留一份，重复实体的 attributes 取并集。
    关系两端使用本次 payload 内的局部实体 ID。
    """
    entities: list[dict[str, Any]] = []
    entity_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    def add_entity(entity: dict[str, Any]) -> str:
        key = (
            normalize_entity_name(entity["text"]),
            entity.get("label") or "Entity",
        )
        existing = entity_by_key.get(key)
        if existing is not None:
            known_attributes = {
                (attribute["text"], attribute["label"])
                for attribute in existing.get("attributes") or []
            }
            for attribute in entity.get("attributes") or []:
                attribute_key = (attribute["text"], attribute["label"])
                if attribute_key not in known_attributes:
                    existing.setdefault("attributes", []).append(attribute)
                    known_attributes.add(attribute_key)
            return existing["id"]

        graph_entity = {
            "id": f"e{len(entities) + 1}",
            "text": entity["text"],
            "label": entity.get("label") or "Entity",
            "attributes": list(entity.get("attributes") or []),
        }
        entities.append(graph_entity)
        entity_by_key[key] = graph_entity
        return graph_entity["id"]

    for entity in normalized_result["entities"]:
        add_entity(entity)

    relations = [
        {
            "source": add_entity(relation["source"]),
            "target": add_entity(relation["target"]),
            "text": relation["text"],
            "label": relation.get("label") or "RELATED_TO",
        }
        for relation in normalized_result["relations"]
    ]
    return {
        "entities": entities,
        "relations": relations,
        "metadata": normalized_result["metadata"],
    }


def cypher_merge_chunk(db_label: str) -> str:
    """生成写入 Chunk 节点及其元数据的 Cypher。"""
    db_label = safe_neo4j_label(db_label)
    return f"""
    MERGE (c:Chunk:MilvusKB:`{db_label}` {{chunk_id: $chunk_id}})
    SET c.file_id = $file_id,
        c.kb_id = $kb_id,
        c.chunk_index = $chunk_index,
        c.content_preview = $content_preview,
        c.start_char_pos = $start_char_pos,
        c.end_char_pos = $end_char_pos
    """


def cypher_merge_entity_mention(db_label: str) -> str:
    """生成实体写入及 Chunk 到 Entity 的 MENTIONS 关系 Cypher。"""
    db_label = safe_neo4j_label(db_label)
    return f"""
    MATCH (c:Chunk:MilvusKB:`{db_label}` {{chunk_id: $chunk_id}})
    MERGE (e:Entity:MilvusKB:`{db_label}` {{
        kb_id: $kb_id,
        normalized_name: $normalized_name,
        label: $entity_label
    }})
    SET e.entity_id = $entity_id,
        e.name = $name,
        e.attributes_json = $attributes_json
    MERGE (c)-[m:MENTIONS {{
        chunk_id: $chunk_id,
        file_id: $file_id,
        kb_id: $kb_id
    }}]->(e)
    """


def cypher_merge_relation(db_label: str) -> str:
    """生成两个 Entity 之间 RELATION 边的 Cypher。"""
    db_label = safe_neo4j_label(db_label)
    return f"""
    MATCH (source:Entity:MilvusKB:`{db_label}` {{
        kb_id: $kb_id,
        normalized_name: $source_name,
        label: $source_label
    }})
    MATCH (target:Entity:MilvusKB:`{db_label}` {{
        kb_id: $kb_id,
        normalized_name: $target_name,
        label: $target_label
    }})
    MERGE (source)-[r:RELATION {{
        kb_id: $kb_id,
        chunk_id: $chunk_id,
        source_name: $source_name,
        target_name: $target_name,
        type: $relation_type
    }}]->(target)
    SET r.triple_id = $triple_id,
        r.text = $text,
        r.file_id = $file_id,
        r.extractor_type = $extractor_type
    """
