


from llmlingua import PromptCompressor

# 初始化 LLMLingua-2（BERT 小模型，速度快）
llm_lingua = PromptCompressor(
    model_name="./llmlingua-2-bert-base-multilingual-cased",
    # model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
    use_llmlingua2=True,
    device_map="cuda"  # 有 GPU 可改为 "cuda"
)

long_text = """
近年来，人工智能技术发展迅速，其中大语言模型（Large Language Model，LLM）成为人工智能领域的重要研究方向。大语言模型通常基于 Transformer 架构，通过大量文本数据进行预训练，从而学习语言中的语法结构、语义关系和知识信息。

在模型训练过程中，首先需要将文本转换为 Token，然后通过 Embedding 层将 Token 映射为向量。接下来，模型利用多层 Transformer 结构对输入信息进行处理，其中 Attention 机制负责计算不同 Token 之间的关联程度，使模型能够根据上下文理解当前 Token 的含义。

模型完成预训练后，通常还需要经过指令微调，使模型能够更好地理解用户指令并按照要求生成回答。部分模型还会使用强化学习进一步优化输出结果，使模型的回答更加符合人类偏好。

然而，大语言模型也存在一些问题。例如，模型的上下文窗口虽然不断扩大，但处理大量文本仍然需要消耗较多的计算资源和显存。输入文本越长，模型推理所需的计算量通常也越大，尤其是在生成阶段，KV Cache 会随着上下文长度增加而占用更多显存。

为了降低长文本处理的成本，可以使用 Prompt Compression 技术对输入内容进行压缩。其核心思路是识别文本中的重要信息，删除重复、冗余或对当前任务帮助较小的内容，在尽可能保留原始语义的情况下减少 Token 数量。

例如，在 RAG 系统中，用户提出问题后，系统会从向量数据库中检索相关文档，再将检索结果与用户问题一起发送给大语言模型。如果检索到的文档数量较多，输入上下文可能包含大量重复信息。此时可以先对检索结果进行压缩，再交给大语言模型处理，从而减少输入 Token 数量和推理成本。

需要注意的是，文本压缩并不是删除越多越好。如果删除了关键事实、数字、条件或实体之间的关系，就可能导致模型无法正确理解原始内容。因此，实际应用中需要在压缩率、信息保留程度和下游任务准确率之间取得平衡。
"""


result = llm_lingua.compress_prompt(

    [long_text],

    target_token=200,              # 固定目标：压缩到约 200 个 token
    force_tokens=['\n', '?', '.']  # 强制保留换行、问号、句号（可选）

)

print(result["compressed_prompt"])   # 压缩后的文本
print(result["origin_tokens"])       # 原始 token 数
print(result["compressed_tokens"])   # 压缩后 token 数






