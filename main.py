import streamlit as st
import datetime
import re
import html
import random
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- 設定 ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
INITIAL_DISPLAY_COUNT = 30
LOAD_MORE_COUNT = 30
CACHE_TTL = 3600

# --- UI構築（最初に宣言） ---
st.set_page_config(page_title="たいやきDB", layout="wide", page_icon="🐟")

# --- 🔐 パスワード認証機能 ---
def check_password():
    """パスワード認証が成功したらTrueを返す"""
    if st.session_state.get('password_correct', False):
        return True

    st.title("🔒 認証が必要です")
    password_input = st.text_input("合言葉を入力してください", type="password")
    
    if st.button("ログイン"):
        # Secretsにパスワードが設定されているか確認
        if "APP_PASSWORD" not in st.secrets:
            st.error("エラー: Secretsに 'APP_PASSWORD' が設定されていません。管理者に連絡してください。")
            return False
            
        if password_input == st.secrets["APP_PASSWORD"]:
            st.session_state['password_correct'] = True
            st.rerun()  # 画面を再読み込みしてメイン画面へ
        else:
            st.error("パスワードが違います 🙅‍♂️")
            
    return False

# ⚠️ ここで認証チェック！通らなければ処理をストップ
if not check_password():
    st.stop()

# ==========================================
# 👇 ここから下は、認証成功後にだけ実行されます
# ==========================================

st.title('たいやき画像データベース(º-º э)З')

# --- 認証関数 ---
@st.cache_resource
def get_drive_service():
    if "service_account" in st.secrets:
        try:
            key_dict = st.secrets["service_account"]
            creds = service_account.Credentials.from_service_account_info(
                key_dict, scopes=SCOPES
            )
            return build('drive', 'v3', credentials=creds)
        except Exception as e:
            st.error(f"認証エラー: Secretsの設定を確認してください。\n詳細: {e}")
            return None
    else:
        st.error("Secretsに [service_account] の設定が見つかりません。")
        return None

# --- 日付解析ロジック ---
def parse_date_from_filename(filename, fallback_iso_date):
    current_year = datetime.datetime.now().year
    try:
        match_bracket = re.search(r'\[(\d{2})-(\d{2})-(\d{2})\]', filename)
        if match_bracket:
            year = 2000 + int(match_bracket.group(1))
            if year > current_year: year -= 100
            month = int(match_bracket.group(2))
            day = int(match_bracket.group(3))
            return datetime.datetime(year, month, day)

        match_timestamp = re.search(r'(20\d{2})(\d{2})(\d{2})_(\d{4,})', filename)
        if match_timestamp:
            year = int(match_timestamp.group(1))
            month = int(match_timestamp.group(2))
            day = int(match_timestamp.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return datetime.datetime(year, month, day)
    except ValueError:
        pass 
    if fallback_iso_date:
        return datetime.datetime.fromisoformat(fallback_iso_date.replace('Z', '+00:00'))
    return None

# --- 高画質サムネイルURL生成 ---
def get_high_res_url(original_url):
    if not original_url: return None
    return re.sub(r'=[a-zA-Z0-9\-_]+$', '=s600', original_url)

# --- データ取得関数 ---
@st.cache_data(ttl=CACHE_TTL)
def fetch_all_images_recursively(_service, folder_id):
    found_images = []
    visited_folders = set()

    def _recursive_search(current_folder_id):
        if current_folder_id in visited_folders: return
        visited_folders.add(current_folder_id)

        page_token = None
        while True:
            try:
                results = _service.files().list(
                    q=f"'{current_folder_id}' in parents and (mimeType contains 'image/' or mimeType = 'application/vnd.google-apps.folder') and trashed = false",
                    pageSize=1000,
                    fields="nextPageToken, files(id, name, mimeType, thumbnailLink, webViewLink, createdTime)",
                    pageToken=page_token
                ).execute()
                items = results.get('files', [])
                for item in items:
                    if item['mimeType'] == 'application/vnd.google-apps.folder':
                        _recursive_search(item['id'])
                    else:
                        fallback_date = item.get('createdTime')
                        dt = parse_date_from_filename(item['name'], fallback_date)
                        if dt and dt.tzinfo: dt = dt.replace(tzinfo=None)
                        item['_dt'] = dt
                        found_images.append(item)
                page_token = results.get('nextPageToken')
                if not page_token: break
            except Exception as e:
                break
    
    if _service:
        _recursive_search(folder_id)
    return found_images

# --- 季節判定 ---
def is_same_season(img_dt, range_days=30):
    if not img_dt: return False
    today = datetime.datetime.now()
    try:
        img_date_this_year = img_dt.replace(year=today.year)
    except ValueError:
        img_date_this_year = img_dt.replace(year=today.year, month=2, day=28)
    diff = (img_date_this_year - today).days
    if diff > 300: diff -= 365
    elif diff < -300: diff += 365
    return abs(diff) <= range_days

# --- コールバック関数 ---
def change_mode_to_date(year, month, day):
    st.session_state.mode_selection = '📅 日付指定検索'
    st.session_state.sel_year = year
    st.session_state.sel_month = month
    st.session_state.sel_day = day

# --- アプリ状態初期化 ---
defaults = {'display_limit': INITIAL_DISPLAY_COUNT, 'shuffled_indices': [], 'last_mode': None, 'last_filter_key': None, 'sel_year': "すべて", 'sel_month': "すべて", 'sel_day': "すべて"}
for key, val in defaults.items():
    if key not in st.session_state: st.session_state[key] = val

# サイドバー設定
st.sidebar.header("設定")
default_id = ""
try:
    if "FOLDER_ID" in st.secrets:
        default_id = st.secrets["FOLDER_ID"]
        st.sidebar.caption("✅ 自動入力成功")
except Exception:
    pass
folder_id_input = st.sidebar.text_input("親フォルダID", value=default_id)

st.sidebar.subheader("表示モード")
mode = st.sidebar.radio(
    "探索方法:",
    ('🎲 完全ランダム', '🗓️ 今の季節のイラスト', '📅 日付指定検索'),
    index=0,
    key="mode_selection"
)

col_num = st.sidebar.slider("列数", min_value=2, max_value=8, value=4)

# メイン処理
if folder_id_input:
    service = get_drive_service()
    
    if service is None:
        st.warning("準備中... Secretsの設定を確認してください。")
    else:
        with st.spinner('データベースを解析中...'):
            all_images = fetch_all_images_recursively(service, folder_id_input)
        
        if not all_images:
            st.error("画像が見つかりませんでした。フォルダの共有設定を忘れていませんか？")
        else:
            filtered_images = []
            is_random_sort = True
            years = sorted(list(set([img['_dt'].year for img in all_images if img['_dt']])))
            years_options = ["すべて"] + years

            if mode == '📅 日付指定検索':
                is_random_sort = False
                st.sidebar.markdown("---")
                st.sidebar.write("📅 **日付条件**")
                
                selected_year = st.sidebar.selectbox("年", years_options, key="sel_year")
                selected_month = st.sidebar.selectbox("月", ["すべて"] + list(range(1, 13)), key="sel_month")
                selected_day = st.sidebar.selectbox("日", ["すべて"] + list(range(1, 32)), key="sel_day")
                
                for img in all_images:
                    dt = img['_dt']
                    if not dt: continue
                    if selected_year != "すべて" and dt.year != selected_year: continue
                    if selected_month != "すべて" and dt.month != selected_month: continue
                    if selected_day != "すべて" and dt.day != selected_day: continue
                    filtered_images.append(img)
                
                filtered_images.sort(key=lambda x: x.get('createdTime', ''))
                filter_key = f"{mode}-{selected_year}-{selected_month}-{selected_day}"
                if filtered_images:
                    st.info(f"📅 指定期間: {len(filtered_images)} 枚 （ドライブ登録順）")

            elif mode == '🗓️ 今の季節のイラスト':
                filtered_images = [img for img in all_images if is_same_season(img['_dt'])]
                st.info(f"今の時期（前後1ヶ月）の画像: {len(filtered_images)} 枚")
                filter_key = mode
            
            else: 
                filtered_images = all_images
                st.caption(f"全 {len(all_images)} 枚からランダム表示")
                filter_key = mode

            if st.session_state.last_filter_key != filter_key:
                st.session_state.display_limit = INITIAL_DISPLAY_COUNT
                st.session_state.shuffled_indices = []
                st.session_state.last_filter_key = filter_key
            
            if not filtered_images:
                st.warning("条件に合う画像がありませんでした。")
            else:
                if is_random_sort:
                    if len(st.session_state.shuffled_indices) != len(filtered_images):
                        indices = list(range(len(filtered_images)))
                        random.shuffle(indices)
                        st.session_state.shuffled_indices = indices
                    display_indices = st.session_state.shuffled_indices
                else:
                    display_indices = list(range(len(filtered_images)))

                current_limit = st.session_state.display_limit
                indices_to_show = display_indices[:current_limit]
                
                cols = st.columns(col_num)
                for i, idx in enumerate(indices_to_show):
                    img = filtered_images[idx]
                    with cols[i % col_num]:
                        if 'thumbnailLink' in img:
                            thumb_url = get_high_res_url(img['thumbnailLink'])
                            safe_name = html.escape(img['name'])
                            html_code = f"""
                                <div style="text-align:center; margin-bottom:5px;">
                                    <a href="{img['webViewLink']}" target="_blank">
                                        <img src="{thumb_url}" 
                                             style="width:100%; border-radius:5px; object-fit:contain;" 
                                             referrerpolicy="no-referrer" 
                                             alt="{safe_name}">
                                    </a>
                                </div>
                            """
                            st.markdown(html_code, unsafe_allow_html=True)
                            
                            dt = img.get('_dt')
                            if dt:
                                date_str = dt.strftime('%Y/%m/%d')
                                st.caption(f"[{safe_name}]") 
                                st.caption(f"📅 {date_str}")
                                st.button("🔍 この日の全画像", key=f"btn_{img['id']}", on_click=change_mode_to_date, args=(dt.year, dt.month, dt.day))
                            else:
                                st.caption(f"[{safe_name}]")
                                st.caption("📅 日付不明")

                if current_limit < len(filtered_images):
                    if st.button("👇 もっと見る", use_container_width=True):
                        st.session_state.display_limit += LOAD_MORE_COUNT
                        st.rerun()
                elif len(filtered_images) > 0:
                    st.success("すべての画像を表示しました！")
else:
    st.info("👈 左のサイドバーにフォルダIDを入力してください。")

st.sidebar.markdown("---")
if st.sidebar.button("キャッシュクリア & 再読込"):
    st.cache_data.clear()
    st.session_state.last_filter_key = None
    st.rerun()