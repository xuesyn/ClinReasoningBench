from sentence_transformers import SentenceTransformer

# 1. 指定在线模型名称
model_name = 'BAAI/bge-large-zh-v1.5'

# 2. 加载模型（此时会联网下载）
model = SentenceTransformer(model_name)

# 3. 将模型保存到本地文件夹
save_path = 'ckpt/bge-large-zh-v1.5'
model.save(save_path)

print(f"模型已成功保存至: {save_path}")