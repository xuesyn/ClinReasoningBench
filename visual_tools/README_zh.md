# visual_tools

这个工具用于本地查看：

- `reference` 图谱
- `ground_truth` 标注数据
- `data` 模型输出数据
- `results` 汇总结果

## 1. 部署与启动

先安装依赖：

```bash
pip install fastapi uvicorn openpyxl
```

然后在 `HCC_LLM_Bench/visual_tools` 目录下启动：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 2027 --reload
```

启动后打开：

- `http://127.0.0.1:2027/reference`
- `http://127.0.0.1:2027/gt`
- `http://127.0.0.1:2027/data`
- `http://127.0.0.1:2027/results`

## 2. 数据来源与替换方式

这个工具默认直接读取 `visual_tools` 目录下的几个数据文件夹：

- `reference/`：参考图谱和 guidance
- `ground_truth/`：GT 标注文件
- `data/`：模型输出样本
- `results/results.xlsx`：最终汇总结果

如果要替换数据，直接替换这些目录中的文件即可，不需要改前端页面。

### `reference`

把新的 reference 子目录放到：

```text
visual_tools/reference/
```

页面会自动扫描可用 reference。

### `ground_truth`

把新的 GT 文件放到：

```text
visual_tools/ground_truth/
```

`gt` 页面会自动读取可选文件列表。

### `data`

把新的模型输出文件放到：

```text
visual_tools/data/
```

`data` 页面会自动读取可选文件列表。

### `results`

结果页默认读取：

```text
visual_tools/results/results.xlsx
```

如果要换结果，只需要直接替换这个 Excel 文件。
