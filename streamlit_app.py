
import streamlit as st
import time, io, os, json, zipfile, difflib
from pathlib import Path
from datetime import datetime
import openai

# Optional imports for file parsing
try:
    import docx
except Exception:
    docx = None
try:
    import PyPDF2
except Exception:
    PyPDF2 = None

# ---------- Configuration ----------
# Set your OpenAI API key as environment variable OPENAI_API_KEY before running.
# Example: export OPENAI_API_KEY="sk-..."
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", None)
MODEL_STEP = os.environ.get("MODEL_STEP", "your-finetuned-model-1")
MODEL_ERROR = os.environ.get("MODEL_ERROR", "your-finetuned-model-2")
PRESET_PROMPT = os.environ.get("PRESET_PROMPT", "You are an academic writing assistant. Help split the introduction into labeled steps and provide error analysis when asked. Respond in JSON where requested.")

openai.api_key = OPENAI_API_KEY

DATA_DIR = Path("student_data")
DATA_DIR.mkdir(exist_ok=True)

st.set_page_config(page_title="AI 论文修改平台", layout="wide")

st.title("📑 AI 论文修改平台（Streamlit）")
st.markdown("""
**说明**：
- 请在运行前在环境变量中设置 `OPENAI_API_KEY`、`MODEL_STEP`、`MODEL_ERROR`（若使用微调模型填模型名）。
- 支持上传 txt/docx/pdf（需安装相关库）。应用会：  
  1. 在论文前添加预设提示词并发送到微调模型1（分step）。  
  2. 模型1输出送给微调模型2进行 19 项错误检测（期望 JSON 输出）。  
  3. 学生在平台内逐项修改，平台记录用时与修改差异并可导出全部日志。
""")

# ---------- Helpers ----------
def read_uploaded(file):
    fname = file.name.lower()
    raw = None
    if fname.endswith(".txt"):
        raw = file.read().decode("utf-8", errors="ignore")
    elif fname.endswith(".docx"):
        if docx is None:
            st.error("需要 python-docx 来解析 .docx 文件。请在 requirements.txt 中安装并重启。")
            return ""
        tmp_path = Path("temp_uploaded.docx")
        tmp_path.write_bytes(file.read())
        doc = docx.Document(str(tmp_path))
        raw = "\n".join(p.text for p in doc.paragraphs)
        tmp_path.unlink(missing_ok=True)
    elif fname.endswith(".pdf"):
        if PyPDF2 is None:
            st.error("需要 PyPDF2 来解析 .pdf 文件。请在 requirements.txt 中安装并重启。")
            return ""
        tmp_path = Path("temp_uploaded.pdf")
        tmp_path.write_bytes(file.read())
        with open(tmp_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            pages = []
            for p in reader.pages:
                try:
                    pages.append(p.extract_text() or "")
                except Exception:
                    pages.append("")
            raw = "\n".join(pages)
        tmp_path.unlink(missing_ok=True)
    else:
        st.error("仅支持 txt/docx/pdf 三种格式。")
        raw = ""
    return raw or ""

def call_model_chat(model, system_prompt, user_text, max_tokens=2048, temperature=0.0):
    if openai.api_key is None:
        raise RuntimeError("OpenAI API key not set. Set OPENAI_API_KEY environment variable.")
    # Use ChatCompletion; adjust if you use different API
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text}
    ]
    resp = openai.ChatCompletion.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature
    )
    return resp.choices[0].message["content"]

def safe_parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        # Try to extract JSON-like substring
        import re
        m = re.search(r"\{.*\}|\[.*\]", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None

def diff_stats(old, new):
    # token-based (word) diff
    old_words = old.split()
    new_words = new.split()
    diff = list(difflib.ndiff(old_words, new_words))
    inserts = sum(1 for d in diff if d.startswith("+ "))
    deletes = sum(1 for d in diff if d.startswith("- "))
    replaces = min(inserts, deletes)
    return {"insert": inserts, "delete": deletes, "replace": replaces}

def timestamp():
    return datetime.utcnow().isoformat() + "Z"

# ---------- UI: Upload & initial processing ----------
with st.sidebar:
    st.header("学生信息")
    student_name = st.text_input("姓名", key="name")
    student_id = st.text_input("学号", key="sid")
    st.markdown("---")
    st.caption("运行设置")
    st.text_input("模型1（分step）", value=MODEL_STEP, key="conf_model_step")
    st.text_input("模型2（错误检测）", value=MODEL_ERROR, key="conf_model_error")
    st.text_area("预设提示词（PRESET_PROMPT）", value=PRESET_PROMPT, height=120, key="conf_preset")

uploaded = st.file_uploader("上传论文 (.txt .docx .pdf)", type=["txt","docx","pdf"])
if uploaded:
    raw_text = read_uploaded(uploaded)
    st.session_state["original_text"] = raw_text
    st.success("文件读取完成（已存入会话）")
else:
    raw_text = st.session_state.get("original_text", "")

if raw_text:
    st.subheader("论文预览（前 2000 字）")
    st.code(raw_text[:2000] + ("\n..." if len(raw_text)>2000 else ""))

    if st.button("一键分析（调用模型1和模型2）"):
        try:
            st.info("正在调用模型1（分step）... 这一步将提交带预设提示词的全文给模型1。")
            model1 = st.session_state.get("conf_model_step", MODEL_STEP)
            preset = st.session_state.get("conf_preset", PRESET_PROMPT)
            model1_input = preset + "\n\nTASK: split the following text into labelled steps and return a JSON with the fields 'steps' (list of {label, text}).\n\nTEXT:\n" + raw_text
            step_out = call_model_chat(model1, preset, model1_input)
            st.session_state["step_result_raw"] = step_out
            st.success("模型1完成，结果已保存。")

            st.info("正在调用模型2（错误检测）... 请让模型返回 JSON 格式的 19 项错误检测结果（name, status, location, excerpt, explanation, suggestion）")
            model2 = st.session_state.get("conf_model_error", MODEL_ERROR)
            # Build prompt for model2
            model2_input = preset + "\n\nTASK: Given the following steps (JSON or plain) identify 19 possible writing errors. "
            model2_input += "Return a JSON array of 19 objects, each with keys: name (string), status ('yes' or 'no'), location (string or indices), excerpt (text snippet), explanation (why this is an error in this student's writing), suggestion (concrete edit suggestion). Use [] if none.\n\nINPUT_STEPS:\n" + step_out
            error_out = call_model_chat(model2, preset, model2_input)
            st.session_state["error_result_raw"] = error_out
            parsed = safe_parse_json(error_out)
            if parsed is None:
                st.warning("模型2返回无法解析为 JSON。已将原始文本保存到会话，请检查模型输出或修改提示词以让其返回 JSON。")
                st.session_state["error_data"] = []
            else:
                st.session_state["error_data"] = parsed
                st.success("模型2完成并解析为 JSON。")
        except Exception as e:
            st.exception(e)

# ---------- Display steps and errors ----------
error_data = st.session_state.get("error_data", None)
step_raw = st.session_state.get("step_result_raw", "")

if step_raw:
    with st.expander("查看模型1（分step）输出（原始）", expanded=False):
        st.code(step_raw[:4000] + ("\n..." if len(step_raw)>4000 else ""))

if error_data is not None:
    st.subheader("19 项错误检测结果")
    if not error_data:
        st.info("当前没有可解析的错误数据（模型2没有返回 JSON）。可以手动添加或调整提示词让模型返回标准 JSON。")
    else:
        # Initialize logs storage
        if "edit_logs" not in st.session_state:
            st.session_state["edit_logs"] = []
        for idx, err in enumerate(error_data):
            name = err.get("name", f"Error {idx+1}")
            status = err.get("status", "no")
            header = f"{idx+1}. {name} — {status}"
            exp = st.expander(header, expanded=False)
            with exp:
                st.markdown(f"**位置:** {err.get('location','-')}")
                st.markdown("**摘录（excerpt）:**")
                excerpt = err.get("excerpt", "")
                st.text_area(f"原始摘录（只读）", value=excerpt, key=f"excerpt_{idx}", height=120)
                st.markdown("**个性化解释:**")
                st.write(err.get("explanation","-"))
                st.markdown("**AI 修改建议:**")
                st.write(err.get("suggestion","-"))

                # Start / abandon / submit buttons and timer management
                started_key = f"started_{idx}"
                starttime_key = f"starttime_{idx}"
                editing_key = f"edittext_{idx}"
                if started_key not in st.session_state:
                    st.session_state[started_key] = False
                if st.button("开始修改（计时）", key=f"start_{idx}"):
                    st.session_state[started_key] = True
                    st.session_state[starttime_key] = time.time()
                    st.session_state[editing_key] = excerpt

                if st.session_state.get(started_key):
                    st.markdown("**在下方编辑并提交（提交后 AI 将检查是否修正）**")
                    new_text = st.text_area("编辑区", value=st.session_state.get(editing_key, excerpt), key=f"area_{idx}", height=160)
                    if st.button("放弃修改（记录并停止计时）", key=f"abandon_{idx}"):
                        st.session_state[started_key] = False
                        st_time = st.session_state.pop(starttime_key, None)
                        elapsed = None
                        if st_time:
                            elapsed = round(time.time() - st_time, 2)
                        log = {
                            "error_index": idx,
                            "error_name": name,
                            "action": "abandon",
                            "excerpt_old": excerpt,
                            "excerpt_new": new_text,
                            "time_used_s": elapsed,
                            "diff": diff_stats(excerpt, new_text),
                            "timestamp": timestamp()
                        }
                        st.session_state["edit_logs"].append(log)
                        st.success(f"放弃记录已保存（用时: {elapsed}s）")
                    if st.button("提交修改并由 AI 检查", key=f"submit_{idx}"):
                        st_time = st.session_state.pop(starttime_key, None)
                        elapsed = None
                        if st_time:
                            elapsed = round(time.time() - st_time, 2)
                        # Call model2 to check this specific excerpt modification
                        try:
                            check_prompt = PRESET_PROMPT + "\n\nTASK: Judge whether the following revised excerpt fixes the target error. Return JSON with {fixed: 'yes'/'no', comment: string}.\n\nORIGINAL_EXCERPT:\n" + excerpt + "\n\nREVISED_EXCERPT:\n" + new_text + "\n\nERROR_NAME:\n" + name
                            check_out = call_model_chat(st.session_state.get("conf_model_error", MODEL_ERROR), PRESET_PROMPT, check_prompt)
                            parsed_check = safe_parse_json(check_out) or {"fixed":"unknown","comment": check_out}
                        except Exception as e:
                            parsed_check = {"fixed":"error","comment": str(e)}
                        log = {
                            "error_index": idx,
                            "error_name": name,
                            "action": "submit",
                            "excerpt_old": excerpt,
                            "excerpt_new": new_text,
                            "time_used_s": elapsed,
                            "diff": diff_stats(excerpt, new_text),
                            "ai_check": parsed_check,
                            "timestamp": timestamp()
                        }
                        st.session_state["edit_logs"].append(log)
                        st.session_state[started_key] = False
                        st.success(f"提交完成。用时: {elapsed}s；AI 检查结果: {parsed_check.get('fixed','-')}")

# ---------- Download / Save ----------
st.markdown("---")
col1, col2 = st.columns([1,3])
with col1:
    if st.button("保存会话到磁盘（用于离线分析）"):
        sid = student_id or "noid"
        name = student_name or "noname"
        out_folder = DATA_DIR / f"{name}_{sid}_{int(time.time())}"
        out_folder.mkdir(parents=True, exist_ok=True)
        # Save files
        orig = st.session_state.get("original_text","")
        (out_folder / "original.txt").write_text(orig, encoding="utf-8")
        (out_folder / "step_result_raw.txt").write_text(st.session_state.get("step_result_raw",""), encoding="utf-8")
        (out_folder / "error_result_raw.txt").write_text(st.session_state.get("error_result_raw",""), encoding="utf-8")
        (out_folder / "error_data.json").write_text(json.dumps(st.session_state.get("error_data",[]), ensure_ascii=False, indent=2), encoding="utf-8")
        (out_folder / "edit_logs.json").write_text(json.dumps(st.session_state.get("edit_logs",[]), ensure_ascii=False, indent=2), encoding="utf-8")
        st.success(f"已保存到：{out_folder}")
with col2:
    if st.button("生成并下载 ZIP（包含全部数据）"):
        sid = student_id or "noid"
        name = student_name or "noname"
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as z:
            z.writestr(f"{name}_{sid}/original.txt", st.session_state.get("original_text",""))
            z.writestr(f"{name}_{sid}/step_result_raw.txt", st.session_state.get("step_result_raw",""))
            z.writestr(f"{name}_{sid}/error_result_raw.txt", st.session_state.get("error_result_raw",""))
            z.writestr(f"{name}_{sid}/error_data.json", json.dumps(st.session_state.get("error_data",[]), ensure_ascii=False, indent=2))
            z.writestr(f"{name}_{sid}/edit_logs.json", json.dumps(st.session_state.get("edit_logs",[]), ensure_ascii=False, indent=2))
        bio.seek(0)
        st.download_button("下载 ZIP 文件", data=bio.getvalue(), file_name=f"{name}_{sid}_session_results.zip")
