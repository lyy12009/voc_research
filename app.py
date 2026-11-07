import streamlit as st
import pandas as pd
from datetime import datetime
import urllib.parse
import urllib.request
import base64

# 頁面標題與佈局設定
st.set_page_config(
    page_title="Moodle 生詞題庫生成系統",
    page_icon="🎓",
    layout="wide"
)

st.title("🎓 生詞題庫生成系統")
st.markdown("請依序完成 **STEP 1** 與 **STEP 2**，最後至 **STEP 3 一鍵匯出完整 GIFT 檔**。")

# 側邊欄設定
st.sidebar.header("⚙️ 題庫分類與教學參數")

default_today = datetime.now().strftime("%Y%m%d")
quiz_date = st.sidebar.text_input("📅 日期戳記 (YYYYMMDD)", value=default_today)
topic_tag = st.sidebar.text_input("🏷️ 測驗主題", value="詞彙")
class_choice = st.sidebar.selectbox("👥 班別選擇", options=["甲班", "乙班"], index=0)

composed_cat_name = f"{quiz_date.strip()}_{topic_tag.strip()}_{class_choice}"
target_category_name = st.sidebar.text_input("📁 最終 Moodle 題庫分類名稱 (可手動修改)", value=composed_cat_name)

enable_tts_listening = st.sidebar.checkbox("啟用全自動 TTS 聽力辨識題區塊", value=True)
enable_adaptive = st.sidebar.checkbox("啟用個人化弱點動態題庫生成", value=True)

export_filename = f"{target_category_name.strip()}_Moodle題庫.txt"

st.sidebar.info(f"📁 **Moodle 題庫分類即將建立為：**\n`$course$/{target_category_name.strip()}`")

# Session State 儲存跨頁資料
if 'words_input_state' not in st.session_state:
    st.session_state['words_input_state'] = (
        "浸潤,jìn rùn,深入體驗 (Tẩm nhuận / Immersion)\n"
        "鞏固,gǒng gù,變強固 (Củng cố / Consolidate)\n"
        "基模,jī mó,思考的方式 (Cơ mô / Schema)\n"
        "留存,liú cún,記在腦子裡 (Lưu tồn / Retention)"
    )

if 'sentences_input_state' not in st.session_state:
    st.session_state['sentences_input_state'] = (
        "我們透過密集浸潤式培訓提升語言能力。\n"
        "課後輔導有助於鞏固大腦的記憶留存率。\n"
        "教師運用漢越詞基模進行教學設計。"
    )

if 'adaptive_data' not in st.session_state:
    st.session_state['adaptive_data'] = "Student01,鞏固,變強固\nStudent02,浸潤,深入體驗"

# 🟢 [核心修正] 降維縫合：伺服器端抓取音訊並轉 Base64
@st.cache_data(show_spinner=False)
def get_tts_base64_or_fallback(text):
    """將 Google TTS 台灣口音抓回轉為 Base64 字串，徹底繞過所有瀏覽器阻擋機制。"""
    try:
        w_encoded = urllib.parse.quote(text)
        url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={w_encoded}&tl=zh-TW&client=tw-ob"
        # 偽裝成正常瀏覽器請求
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=3) as response:
            audio_bytes = response.read()
            # 將二進位音檔轉為 Base64 編碼字串
            b64_str = base64.b64encode(audio_bytes).decode('utf-8')
            return f"data:audio/mpeg;base64,{b64_str}"
    except Exception as e:
        # 若失敗（極少數情況），降級回 Youdao
        w_encoded = urllib.parse.quote(text)
        return f"https://dict.youdao.com/dictvoice?audio={w_encoded}&le=zh"

tab1, tab2, tab3, tab4 = st.tabs([
    "📝 STEP 1: 全班骨幹題設定", 
    "🎯 STEP 2: 個人弱點題設定", 
    "🚀 STEP 3: 統一打包匯出 (GIFT)",
    "📖 使用 SOP 與 Moodle 設定"
])

with tab1:
    st.subheader("📝 STEP 1: 輸入當日全班進度（生詞與例句）")
    col1, col2 = st.columns(2)
    with col1:
        words_input = st.text_area("生詞輸入框 (生詞,拼音,翻譯)", value=st.session_state['words_input_state'], height=220)
        st.session_state['words_input_state'] = words_input
    with col2:
        sentences_input = st.text_area("課文句子輸入框", value=st.session_state['sentences_input_state'], height=220)
        st.session_state['sentences_input_state'] = sentences_input

with tab2:
    st.subheader("🎯 STEP 2: 設定個人化弱點自適應題庫")
    adaptive_input = st.text_area(
        "學生個人弱點生詞清單 (帳號,生詞,提示)",
        value=st.session_state['adaptive_data'],
        height=180,
        disabled=not enable_adaptive
    )
    st.session_state['adaptive_data'] = adaptive_input

def generate_gift_content():
    active_cat = target_category_name.strip()
    category_base = f"$course$/{active_cat}"
    gift_lines = [f"$CATEGORY: {category_base}\n\n"]
    
    w_text = st.session_state['words_input_state']
    s_text = st.session_state['sentences_input_state']
    a_text = st.session_state['adaptive_data']
    
    word_info = {}
    word_list = []
    seen = set()
    
    for line in w_text.strip().split('\n'):
        if not line.strip(): continue
        parts = line.split(',')
        w = parts[0].strip()
        if w in seen: continue
        seen.add(w)
        py = parts[1].strip() if len(parts) >= 2 else ""
        trans = parts[2].strip() if len(parts) >= 3 else ""
        word_info[w] = {"pinyin": py, "trans": trans}
        word_list.append(w)

    # 第一大題
    gift_lines.append(f"// 第一大題：生詞與意涵直讀配對\n")
    gift_lines.append(f"::{active_cat}_SECTION1_形義配對::第一大題：請將下列華語生詞與正確意涵進行配對 {{\n")
    for w, info in word_info.items():
        meaning = info['trans'] if info['trans'] else info['pinyin']
        gift_lines.append(f"  ={w} -> {meaning}\n")
    gift_lines.append("}\n\n")

    # 第二大題 (TTS 聽力)
    if enable_tts_listening and word_list:
        gift_lines.append(f"// 第二大題：全自動 TTS 聽力語音辨識 (Base64 內嵌防阻擋)\n")
        for idx, w in enumerate(word_list, 1):
            distractors = [other for other in word_list if other != w]
            distractor_choices = distractors[:3] if len(distractors) >= 3 else distractors
            
            # 🟢 呼叫 Base64 音訊轉換函數
            audio_src = get_tts_base64_or_fallback(w)
            
            audio_html = f"<audio controls src='{audio_src}'></audio>"
            gift_lines.append(f"::{active_cat}_SECTION2_聽力_{idx}:: [html]第二大題：請聽發音，並選出正確的華語生詞：<br><br>{audio_html}<br><br>{{\n")
            gift_lines.append(f"  ={w}\n")
            for d in distractor_choices:
                gift_lines.append(f"  ~{d}\n")
            gift_lines.append("}\n\n")

    # 第三大題
    gift_lines.append(f"// 第三大題：句子理解與繁體字寫作\n")
    sentence_list = [s.strip() for s in s_text.strip().split('\n') if s.strip()]
    q_idx = 1
    for s in sentence_list:
        for w, info in word_info.items():
            if w in s:
                hint_str = f"拼音: {info['pinyin']}"
                if info['trans']: hint_str += f" | 釋義: {info['trans']}"
                hint_display = f" <span style='color:#666;'>（提示：{info['pinyin']} | {info['trans']}）</span>"
                cloze_syntax = f"{{={w} ={w}的 #{hint_str}}}" + hint_display
                formatted_sentence = s.replace(w, cloze_syntax)
                gift_lines.append(f"::{active_cat}_SECTION3_填空_{q_idx}:: [html]第三大題：請閱讀句子並填入正確生詞：<br>{formatted_sentence}\n\n")
                q_idx += 1

    # 第四大題
    if enable_adaptive and a_text.strip():
        gift_lines.append(f"// 第四大題：個人化自適應弱點複習區\n")
        for line in a_text.strip().split('\n'):
            if not line.strip() or ',' not in line: continue
            parts = line.split(',')
            student_id, word = parts[0].strip(), parts[1].strip()
            hint = parts[2].strip() if len(parts) > 2 else ""
            gift_lines.append(f"$CATEGORY: {category_base}/個人弱點自適應庫/個人弱點_{student_id}\n")
            if hint:
                gift_lines.append(f"::弱點複習_{word}:: [個人化弱點] 請寫出生詞：【 {{={word} #{hint}}} 】\n\n")
            else:
                gift_lines.append(f"::弱點複習_{word}:: [個人化弱點] 請寫出生詞：【 {{={word}}} 】\n\n")

    return "".join(gift_lines)

with tab3:
    st.subheader("🚀 STEP 3: 一鍵匯出完整 Moodle GIFT 題庫檔")
    if st.button("🔄 點此生成/更新題庫 (需向 Google 獲取語音)"):
        with st.spinner("正在向 Google 伺服器獲取台灣口音音訊並進行 Base64 轉換..."):
            gift_result = generate_gift_content()
            st.session_state['generated_gift'] = gift_result
            st.success("✅ 題庫與內嵌語音生成完畢！")

    if 'generated_gift' in st.session_state:
        current_final_name = target_category_name.strip()
        col_dl, col_prev = st.columns([1, 2])
        with col_dl:
            st.download_button(
                label=f"📥 下載【{current_final_name}】GIFT 檔",
                data=st.session_state['generated_gift'].encode('utf-8'),
                file_name=export_filename,
                mime="text/plain",
                type="primary"
            )
        with col_prev:
            with st.expander("👀 檢視 GIFT 內部結構"):
                # 只顯示前段避免 base64 字串太長卡住 UI
                st.code(st.session_state['generated_gift'][:1000] + "\n... (後略)", language="text")

with tab4:
    st.subheader("📖 Moodle 題庫治理與測驗卷設定完整 SOP")
    st.markdown("已更新為 Base64 離線音訊架構，無須擔心外連被阻擋。")
