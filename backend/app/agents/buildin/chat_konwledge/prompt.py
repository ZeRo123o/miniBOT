KNOWLEDGE_EMPTY_REPLY_TEMPLATE = (
    "已切换到知识问答模式。\n\n"
    "当前还没有接入或命中企业知识库内容，所以我不会基于空知识库编造答案。"
    "下一步可以接入知识库上传、切片、向量索引和引用来源展示后，再回答这类问题。\n\n"
    "你的问题：{question}"
)

KNOWLEDGE_CONTEXT_REPLY_TEMPLATE = (
    "根据已检索到的企业知识片段，建议如下：\n\n"
    "{context}\n\n"
    "以上回答仅基于右侧引用来源中的企业知识片段。"
)
