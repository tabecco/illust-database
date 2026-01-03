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

# ==========================================
# 👇 ここから下を書き換えてください
# ==========================================

st.title('たいやき画像データベース(º-º э)З')

# --- 📱 スマホ用CSS注入 (案2の実装) ---
# スマホ(幅640px以下)のとき、カラムを強制的に横並び(50%幅)にする
st.markdown("""
<style>
@media (max-width: 640px) {
    div[data-testid="column"] {
        width: 50% !important;
        flex: 0 0 50% !important;
        min-width: 50% !important;
    }
}
</style>
""", unsafe_allow_html=True)

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

# --- サイドバー (フォルダIDなどの技術設定のみ残す) ---
st.sidebar.header("🔧 システム設定")
default_id = ""
try:
    if "FOLDER_ID" in st.secrets:
        default_id = st.secrets["FOLDER_ID"]
except Exception:
    pass
folder_id_input = st.sidebar.text_input("親フォルダID", value=default_id)

if st.sidebar.button("キャッシュクリア & 再読込"):
    st.cache_data.clear()
    st.session_state.last_filter_key = None
    st.rerun()

# --- メイン設定エリア (案1の実装: Expanderへの移動) ---
# ここで列数やモードを操作できるように変更
with st.expander("⚙️ 表示設定・検索フィルター", expanded=True):
    col1, col2 = st.columns([1, 1])
    with col1:
        # モード選択
        mode = st.radio(
            "探索方法:",
            ('🎲 完全ランダム', '🗓️ 今の季節のイラスト', '📅 日付指定検索'),
            index=0,
            key="mode_selection"
        )
    with col2:
        # 列数スライダー (スマホではCSSで無視されるがPCでは有効)
        col_num = st.slider("画像の列数 (PC用)", min_value=2, max_value=8, value=4)

    # 日付検索用のセレクタもExpander内に移動
    selected_year = "すべて"
    selected_month = "すべて"
    selected_day = "すべて"
    
    if mode == '📅 日付指定検索':
        st.markdown("---")
        # サービス取得前でもUIパーツは表示できるように変数は仮置きで処理したいが、
        # ここでは後続処理のためにコンテナを分ける
        d_col1, d_col2, d_col3 = st.columns(3)
        # 実際の選択肢は画像ロード後に生成する必要があるため、ここではプレースホルダーのみ
        # ※ロジックの簡略化のため、ドロップダウンの中身は後ほど設定

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

            # 日付指定ロジックのUI配置 (Expander内への配置変え)
            if mode == '📅 日付指定検索':
                is_random_sort = False
                # Expander内の日付セレクタを表示
                with d_col1:
                    selected_year = st.selectbox("年", years_options, key="sel_year")
                with d_col2:
                    selected_month = st.selectbox("月", ["すべて"] + list(range(1, 13)), key="sel_month")
                with d_col3:
                    selected_day = st.selectbox("日", ["すべて"] + list(range(1, 32)), key="sel_day")
                
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
                    st.info(f"📅 指定期間: {len(filtered_images)} 枚")

            elif mode == '🗓️ 今の季節のイラスト':
                filtered_images = [img for img in all_images if is_same_season(img['_dt'])]
                st.info(f"今の時期（前後1ヶ月）の画像: {len(filtered_images)} 枚")
                filter_key = mode
            
            else: 
                filtered_images = all_images
                # ランダムモード時の情報表示も少し控えめに
                st.caption(f"全 {len(all_images)} 枚からランダム表示中")
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
                
                # 画像表示ループ
                cols = st.columns(col_num)
                for i, idx in enumerate(indices_to_show):
                    img = filtered_images[idx]
                    # スマホではCSSが効いて強制的に2列になるが、
                    # col_numでの割り振りロジック自体は維持する必要がある
                    with cols[i % col_num]:
                        if 'thumbnailLink' in img:
                            thumb_url = get_high_res_url(img['thumbnailLink'])
                            safe_name = html.escape(img['name'])
                            
                            # 画像表示用HTML
                            # スマホで見やすいようにマージンを少し調整
                            html_code = f"""
                                <div style="text-align:center; margin-bottom:10px;">
                                    <a href="{img['webViewLink']}" target="_blank">
                                        <img src="{thumb_url}" 
                                             style="width:100%; border-radius:8px; object-fit:contain; box-shadow: 0 2px 4px rgba(0,0,0,0.1);" 
                                             referrerpolicy="no-referrer" 
                                             alt="{safe_name}">
                                    </a>
                                </div>
                            """
                            st.markdown(html_code, unsafe_allow_html=True)
                            
                            dt = img.get('_dt')
                            if dt:
                                date_str = dt.strftime('%Y/%m/%d')
                                st.caption(f"📅 {date_str}")
                                # ボタンも少しコンパクトに
                                if st.button("🔍この日", key=f"btn_{img['id']}", on_click=change_mode_to_date, args=(dt.year, dt.month, dt.day)):
                                    pass
                            else:
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

