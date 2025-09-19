AI 论文修改平台 — Streamlit

内容:
- streamlit_app.py  : 主应用
- requirements.txt   : 运行依赖
- run.sh             : 简单启动脚本（Linux / macOS）
- 学生数据与 Zip 下载功能内置。

运行步骤 (本地):
1. 安装依赖: `pip install -r requirements.txt`
2. 设置环境变量:
   - `OPENAI_API_KEY` (必需)
   - `MODEL_STEP` (可选，若使用微调模型)
   - `MODEL_ERROR` (可选，若使用微调模型)
   - `PRESET_PROMPT` (可选)
3. 运行: `bash run.sh` 或 `streamlit run streamlit_app.py`

注意:
- 该程序期望你的微调模型在收到特定任务提示时能返回 JSON。若模型返回文本，请调整预设提示词以产生 JSON。
- 若使用 Windows, 可直接 `streamlit run streamlit_app.py`。
