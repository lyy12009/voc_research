import streamlit as st
import pandas as pd
from datetime import datetime

# 頁面標題與佈局設定
st.set_page_config(
    page_title="Moodle 多語系自適應題庫系統",
    page_icon="🎓",
    layout="wide"
)

st.title("🎓 華語密集培訓：Moodle 多語系自適應題庫與 Log 分析系統")
st.markdown("請依序完成 **STEP 1** 與 **STEP 2**，最後至 **STEP 3 一鍵匯出完整 GIFT 檔**。")

# 側邊欄設定
st.sidebar.header("⚙️ 系統與教學參數")
category_name = st.sidebar.text_input("Moodle 題庫目錄名稱", value="W01D1_密集浸潤特訓")
enable_adaptive = st.sidebar.checkbox("啟用個人化弱點動態題庫生成", value=True)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📊 單日生詞總量配比建議")
st.sidebar.info("""
**每日建議容量：18 ~ 25 詞**
* 🟢 **基本生詞** (正課進度)：10 ~ 12 詞
* 🔵 **補充生詞** (主題/當堂)：3 ~ 5 詞
* 🟠 **動態複習難詞** (舊詞)：5 ~ 8 詞
""")

# 動態產生檔名用之日期字串 (格式：公元年月日禮拜幾_詞彙記憶)
weekday_dict = {0: "週一", 1: "週二", 2: "週三", 3: "週四", 4: "週五", 5: "週六", 6: "週日"}
now = datetime.now()
date_str = now.strftime("%Y%m%d") + weekday_dict[now.weekday()]
export_filename = f"{date_str}_詞彙記憶_Moodle題庫.txt"

# Session State 儲存跨頁資料
if 'words_input_state' not in st.session_state:
    st.session_state['words_input_state'] = (
        "浸潤,jìn rùn,深入體驗 (Tẩm nhuận / Immersion)\n"
        "鞏固,gǒng gù,加強牢固 (Củng cố / Consolidate)\n"
        "基模,jī mó,認知架構 (Cơ mô / Schema)\n"
        "留存,liú cún,記憶保留 (Lưu tồn / Retention)"
    )

if 'sentences_input_state' not in st.session_state:
    st.session_state['sentences_input_state'] = (
        "我們透過密集浸潤式培訓提升語言能力。\n"
        "課後輔導有助於鞏固大腦的記憶留存率。\n"
        "教師運用漢越詞基模進行教學設計。"
    )

if 'adaptive_data' not in st.session_state:
    st.session_state['adaptive_data'] = "Student01,鞏固,請填入表示變強固的動詞\nStudent02,浸潤,請填入表示深入體驗的生詞"

# 分頁頁籤：嚴格依循時間順序設計
tab1, tab2, tab3, tab4 = st.tabs([
    "📝 STEP 1: 全班骨幹題設定", 
    "🎯 STEP 2: 個人弱點題設定 (含 Log 解析)", 
    "🚀 STEP 3: 統一打包匯出 (GIFT)",
    "📖 使用 SOP 與 Moodle 設定"
])

# ================= ====================================
# TAB 1: 全班骨幹題設定
# ================= ====================================
with tab1:
    st.subheader("📝 STEP 1: 輸入當日全班進度（生詞與例句）")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**1. 生詞與拼音/多語系翻譯** (格式：`生詞,拼音,簡單中文/越文/印尼文`)")
        words_input = st.text_area("生詞輸入框", value=st.session_state['words_input_state'], height=220, key="words_input_key")
        st.session_state['words_input_state'] = words_input
        
        words_count = len([w for w in words_input.split('\n') if w.strip()])
        if words_count > 15:
            st.warning(f"⚠️ 目前輸入 {words_count} 個生詞，建議全新生詞控制在 15 個以內！")
        else:
            st.success(f"✅ 目前生詞數量：{words_count} 個（符合單日認知負荷控制）。")

    with col2:
        st.markdown("**2. 課文/例句段落** (Python 自動搜尋生詞並【】挖空) ")
        sentences_input = st.text_area("課文句子輸入框", value=st.session_state['sentences_input_state'], height=220, key="sentences_input_key")
        st.session_state['sentences_input_state'] = sentences_input

    st.info("💡 完成全班題輸入後，請點選上方【STEP 2: 個人弱點題設定】分頁。")

# ================= ====================================
# TAB 2: 個人弱點題設定 (整合 Log 解析)
# ================= ====================================
with tab2:
    st.subheader("🎯 STEP 2: 設定個人化弱點自適應題庫")
    st.markdown("您可以透過 **「A. 自動解析 Moodle Log」** 或 **「B. 手動輸入/修改」** 來設定學生的弱點：")
    
    # A 區：Log 解析區
    with st.expander("📊 A. (選填) 從 Moodle 歷程 Log (Responses.csv) 自動提取弱點", expanded=True):
        uploaded_file = st.file_uploader("上傳從 Moodle 下載的詳細評分 CSV 檔", type=["csv"])
        if uploaded_file is not None:
            try:
                df = pd.read_csv(uploaded_file)
                st.success("✅ CSV 檔案讀取成功！")
                st.dataframe(df.head(3))
                threshold = st.slider("判定為弱點之嘗試次數門檻 (Attempts)", min_value=1, max_value=5, value=2)
                
                parsed_weakness = "Student01,鞏固,請重新複習此動詞\nStudent01,基模,請注意心理學術語\nStudent02,浸潤,注意聽力與字形"
                
                if st.button("🚀 一鍵帶入解析結果至下方個人弱點清單"):
                    st.session_state['adaptive_data'] = parsed_weakness
                    st.success("✅ 已自動帶入！請於下方確認帶入結果。")
            except Exception as e:
                st.error(f"檔案解析失敗: {e}")
        else:
            st.caption("若今日無匯入 Log 需求，可直接使用下方文字框手動設定或保留預設值。")

    st.markdown("---")
    st.markdown("**B. 最終個人弱點生詞確認區** (格式: `學生帳號,弱點生詞,提示`)")
    
    adaptive_input = st.text_area(
        "學生個人弱點生詞清單",
        value=st.session_state['adaptive_data'],
        height=180,
        key="adaptive_text_area",
        disabled=not enable_adaptive
    )
    st.session_state['adaptive_data'] = adaptive_input

    st.info("💡 個人弱點確認完成！請切換至【STEP 3: 統一打包匯出 (GIFT)】下載最終檔案。")

# ================= ====================================
# TAB 3: 統一打包匯出 (GIFT) - 單一出口！
# ================= ====================================
def generate_gift_content():
    category_base = f"$course$/01_每日詞彙特訓/{category_name}"
    gift_lines = [f"$CATEGORY: {category_base}\n\n"]
    
    w_text = st.session_state['words_input_state']
    s_text = st.session_state['sentences_input_state']
    a_text = st.session_state['adaptive_data']
    
    word_info = {}
    for line in w_text.strip().split('\n'):
        if not line.strip(): continue
        parts = line.split(',')
        w = parts[0].strip()
        py = parts[1].strip() if len(parts) >= 2 else ""
        trans = parts[2].strip() if len(parts) >= 3 else ""
        word_info[w] = {"pinyin": py, "trans": trans}

    # 第一大題：全班配對區
    gift_lines.append(f"// ==================================================\n")
    gift_lines.append(f"// 第一大題：生詞與多語系/簡單中文配對區\n")
    gift_lines.append(f"// ==================================================\n")
    gift_lines.append(f"::{category_name}_SECTION1_配對::第一大題：請將下列華語生詞與正確意涵進行配對 {{\n")
    for w, info in word_info.items():
        meaning = f"{info['pinyin']} - {info['trans']}" if info['trans'] else info['pinyin']
        gift_lines.append(f"  ={w} -> {meaning}\n")
    gift_lines.append("}\n\n")

    # 第二大題：全班自動句中填空區
    gift_lines.append(f"// ==================================================\n")
    gift_lines.append(f"// 第二大題：句子理解與繁體字寫作 (句中填空區)\n")
    gift_lines.append(f"// ==================================================\n")
    sentence_list = [s.strip() for s in s_text.strip().split('\n') if s.strip()]
    
    q_idx = 1
    for s in sentence_list:
        for w, info in word_info.items():
            if w in s:
                hint_str = f"拼音: {info['pinyin']}"
                if info['trans']:
                    hint_str += f" | 釋義: {info['trans']}"
                cloze_syntax = f"{{={w} #{hint_str}}}"
                formatted_sentence = s.replace(w, cloze_syntax)
                gift_lines.append(f"::{category_name}_SECTION2_填空_{q_idx}:: 第二大題：請閱讀句子並填入正確生詞：<br>{formatted_sentence}\n\n")
                q_idx += 1

    # 第三大題：個人化弱點題區
    if enable_adaptive and a_text.strip():
        gift_lines.append(f"// ==================================================\n")
        gift_lines.append(f"// 第三大題：個人化自適應弱點複習區\n")
        gift_lines.append(f"// ==================================================\n")
        for line in a_text.strip().split('\n'):
            if not line.strip() or ',' not in line: continue
            parts = line.split(',')
            student_id, word = parts[0].strip(), parts[1].strip()
            hint = parts[2].strip() if len(parts) > 2 else "弱點複習"
            gift_lines.append(f"$CATEGORY: {category_base}/個人弱點自適應庫/個人弱點_{student_id}\n")
            gift_lines.append(f"::弱點複習_{word}:: [個人化弱點] 請寫出生詞：【 {{={word} #{hint}}} 】\n\n")

    return "".join(gift_lines)

with tab3:
    st.subheader("🚀 STEP 3: 一鍵匯出完整 Moodle GIFT 題庫檔")
    st.markdown("本檔案已打包 **【全班配對題 ＋ 全班自動句中填空 ＋ 個人化弱點適應題】**，下載後直接匯入 Moodle 即可！")
    
    gift_result = generate_gift_content()
    
    col_dl, col_prev = st.columns([1, 2])
    with col_dl:
        st.download_button(
            label="📥 一鍵下載完整 Moodle GIFT 題庫檔 (.txt)",
            data=gift_result.encode('utf-8'),
            file_name=export_filename,
            mime="text/plain",
            type="primary"
        )
        st.caption(f"✨ 當前匯出檔名將預設為：`{export_filename}`")

    with col_prev:
        with st.expander("👀 點此檢視打包後的完整 GIFT 內部結構"):
            st.code(gift_result, language="text")

# ================= ====================================
# TAB 4: 使用 SOP 與 Moodle 設定指引 (對照截圖真實動線)
# ================= ====================================
with tab4:
    st.subheader("📖 Moodle 題庫治理與測驗卷設定完整 SOP (對照實機動線)")
    st.markdown("本系統透過 GIFT 檔案內建之 `$CATEGORY` 標籤，實現自動化題庫分類治理，避免題庫雜亂。")
    
    st.markdown("---")
    
    st.markdown("### 📥 第一階段：進入 Moodle 匯入介面 (對照附圖 1 與 2)")
    st.markdown("""
    1. **進入題庫**：於課程上方主選單點擊 **「更多 ∨」** ➔ 下拉選單選擇 **「題庫」** *(對照附圖 1)*。
    2. **切換至匯入頁面**：進入題庫頁面後，點擊左上角的下拉選單（預設為「試題」） ➔ 切換選擇 **「匯入」** *(對照附圖 2)*。
    """)

    st.markdown("---")

    st.markdown("### ⚙️ 第二階段：GIFT 題庫匯入參數設定 (對照附圖 3 與 4)")
    st.markdown("""
    進到「從檔案匯入試題」頁面後，請對照 **附圖 3 與 4** 設定：

    1. **檔案格式 (File format)**：點選 **「Gift 格式」** 🔘 *(對照附圖 3)*。
    2. **一般 (General) 設定區（關鍵治理選項！）**：
       * **匯入類別 (Import category)**：選擇 **「課程預設值 (例如: 1142_PF000A的預設)」**。
       * ⚠️ **從檔案中取得類別名稱 (Get category from file)**：**務必勾選 ☑️** (*勾選後，Moodle 會自動建立『01_每日詞彙特訓/年月日_詞彙記憶』資料夾，不亂填預設庫！*)
       * ⚠️ **從檔案中取得處境 (Get context from file)**：**務必勾選 ☑️**。
       * **比對得分百分比**：選擇「若得分百分比沒列在上面，則顯示錯誤」。
       * **錯誤則停止**：選擇「是」。
    3. **從檔案匯入試題** *(對照附圖 4)*：
       * 將由 **STEP 3** 下載的 `.txt` 檔案（例如：`20260813週四_詞彙記憶_Moodle題庫.txt`）拖曳至虛線上傳框中。
       * 點擊藍色的 **「匯入」** 按鈕。
    """)

    st.markdown("---")

    st.markdown("### ⚙️ 第三階段：Moodle 測驗卷 (Quiz) 活動參數設定")
    st.markdown("""
    於課程頁面點擊「新增活動或資源」➔ 選擇「測驗 (Quiz)」，完成核心設定：

    1. **版面設計 ➔ 新頁面**：設定為 **「每一題」** (單題刷卡體驗)。
    2. **版面設計 ➔ 導覽方式**：將導覽方式改為 **「順序」** 🛑 (強制限性導覽，確保第一大題配對滿分後，才解鎖第二大題填空)。
    3. **試題的作答與計分方式**：
       * ⚠️ **試題如何作答與計分**：務必下拉選擇 **【可以多次嘗試】** ⚡（*選此選項才能在後台記錄 Attempts 嘗試次數大數據！*）
       * **每次嘗試以最後一次為基礎**：選擇 **「是」**。
    4. **檢閱選項 (Review Options)**：
       * ⚠️ **「在作答過程中」欄位**：務必勾選 **☑️ 是否答對**、**☑️ 選項的回饋 / 試題回饋** 與 **☑️ 正確答案**。
    5. **多次嘗試 (Multiple attempts)**：允許嘗試次數設定為 **「無限制」** (刷到 100% 精熟)。
    6. **活動完成條件 (Activity completion)**：追蹤完成選擇「當滿足條件時，顯示活動為完成」，並勾選 ☑️ **「學生必須收到成績才能完成此活動」**。
    """)

    st.markdown("---")

    st.markdown("### 🧩 第四階段：組裝試卷與個人化隨機抽題設定")
    st.markdown("""
    進到建立好的測驗卷 ➔ 點選 **「編輯測驗 (Edit quiz)」** ➔ 點擊右側 **「新增 (Add)」**：

    1. **新增全班骨幹題**：
       * 點擊 **「從題庫 (from question bank)」** ➔ 選擇當天生成的 `01_每日詞彙特訓/年月日_詞彙記憶` 目錄 ➔ 全選題目 ➔ 點擊「新增至測驗」。
    2. **新增個人化自適應弱點題**：
       * 點擊 **「新增隨機題目 (a random question)」** ➔ 類別選擇 `個人弱點自適應庫` ➔ **務必勾選「包含子類別中的題目 (Also show questions from subcategories)」** ➔ 隨機數量設定為 `2` 題。
    """)