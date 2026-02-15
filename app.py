"""
Streamlit Frontend for Construction Quantity Takeoff Engine
============================================================

Modern web interface for:
- DWG/DXF file upload
- Real-time BOM calculation
- Excel export functionality
- Multi-floor/block visualization

2026 Design: Glassmorphism UI with Turkish localization

Author: AI Solutions Architect
Version: 1.0.0 (MVP)
"""

import streamlit as st
import pandas as pd
import requests
import json
import os
import base64
from io import BytesIO
from datetime import datetime
from typing import Optional, Any

# Get backend URL from environment variable (Docker) or default (local)
DEFAULT_API_URL = os.environ.get("BACKEND_URL", "http://localhost:8088")


# =============================================================================
# PAGE CONFIGURATION
# =============================================================================

st.set_page_config(
    page_title="İnşaat Metraj Otomasyonu",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================================================================
# CUSTOM CSS (Glassmorphism + Dark Theme)
# =============================================================================

st.markdown("""
<style>
    /* Import Google Font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    /* Global Styles */
    .stApp {
        font-family: 'Inter', sans-serif;
    }
    
    /* Glassmorphism Card */
    .glass-card {
        background: rgba(255, 255, 255, 0.05);
        backdrop-filter: blur(10px);
        border-radius: 16px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 24px;
        margin-bottom: 16px;
    }
    
    /* Metric Card */
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        color: white;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
    }
    
    .metric-value {
        font-size: 2.5rem;
        font-weight: 700;
        margin: 0;
    }
    
    .metric-label {
        font-size: 0.9rem;
        opacity: 0.9;
        margin-top: 4px;
    }
    
    /* Success/Warning Cards */
    .success-card {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        border-radius: 12px;
        padding: 16px 24px;
        color: white;
        margin-bottom: 16px;
    }
    
    .warning-card {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        border-radius: 12px;
        padding: 16px 24px;
        color: white;
        margin-bottom: 16px;
    }
    
    /* Table Styling */
    .dataframe {
        border-radius: 8px !important;
        overflow: hidden;
    }
    
    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    }
    
    [data-testid="stSidebar"] .stMarkdown {
        color: #e0e0e0;
    }
    
    /* File Uploader */
    [data-testid="stFileUploader"] {
        border: 2px dashed rgba(102, 126, 234, 0.5);
        border-radius: 12px;
        padding: 20px;
    }
    
    /* Button Styling */
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 8px;
        padding: 12px 24px;
        font-weight: 600;
        border: none;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
    }
    
    /* Download Button */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        color: white;
        border-radius: 8px;
        font-weight: 600;
        border: none;
    }
    
    /* Headers */
    h1, h2, h3 {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    
    /* Expander */
    .streamlit-expanderHeader {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# SIDEBAR CONFIGURATION
# =============================================================================

# Admin password from environment
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/building.png", width=80)
    st.title("🏗️ Metraj Sistemi")
    
    st.markdown("---")
    
    # MODE SELECTION (New Feature)
    st.subheader("🎯 Mod Seçimi")
    app_mode = st.radio(
        "Çalışma Modu",
        options=["Metraj Hesaplayıcı", "📂 Proje Geçmişi", "Admin Paneli"],
        index=0,
        help="Admin paneli için şifre gerekir"
    )
    
    st.markdown("---")
    
    # Show calculator options only in Calculator mode
    if app_mode == "Metraj Hesaplayıcı":
        # API Configuration
        st.subheader("🔗 API Bağlantısı")
        api_url = st.text_input(
            "API URL",
            value=DEFAULT_API_URL,
            help="FastAPI backend adresi (varsayılan: http://localhost:8088)"
        )
        
        st.markdown("---")
        
        # Drawing Parameters
        st.subheader("📐 Çizim Parametreleri")
        
        drawing_unit = st.selectbox(
            "Birim",
            options=["cm", "mm", "m"],
            index=0,
            help="CAD çiziminin birimi"
        )
        
        floor_height_cm = st.number_input(
            "Kat Yüksekliği (cm)",
            min_value=200,
            max_value=500,
            value=280,
            step=10,
            help="Duvar alanı hesabı için kat yüksekliği"
        )
        
        floor_multiplier = st.number_input(
            "Kat Adedi / Çarpanı",
            min_value=1,
            max_value=50,
            value=1,
            step=1,
            help="Hesaplanan miktarlar bu sayı ile çarpılır"
        )
        
        st.markdown("---")
        
        # Project Info
        st.subheader("📋 Proje Bilgisi")
        project_name = st.text_input(
            "Proje Adı",
            value="Yeni Proje",
            help="Excel dosyası adı için kullanılır"
        )
        
        st.markdown("---")
        
        # Health Check
        st.subheader("🔌 Sistem Durumu")
        if st.button("🔄 Bağlantıyı Test Et"):
            try:
                response = requests.get(f"{api_url}/health", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    st.success(f"✅ Bağlantı başarılı!")
                    st.info(f"📦 Versiyon: {data.get('version', 'N/A')}")
                    st.info(f"🗄️ Veritabanı: {data.get('database', 'N/A')}")
                    st.info(f"📁 ODA: {data.get('oda_converter', 'N/A')}")
                else:
                    st.error(f"❌ API hatası: {response.status_code}")
            except Exception as e:
                st.error(f"❌ Bağlantı hatası: {str(e)[:50]}")
    
    else:
        # ADMIN MODE - Show login
        st.subheader("🔐 Admin Girişi")
        admin_password_input = st.text_input(
            "Şifre",
            type="password",
            help="Admin paneline erişim için şifre girin"
        )
        
        if admin_password_input:
            if admin_password_input == ADMIN_PASSWORD:
                st.session_state["admin_authenticated"] = True
                st.success("✅ Giriş başarılı!")
            else:
                st.session_state["admin_authenticated"] = False
                st.error("❌ Hatalı şifre!")
        
        st.markdown("---")
        st.caption("💡 Varsayılan şifre: admin123")
        st.caption("🔧 Değiştirmek için: ADMIN_PASSWORD env var")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def parse_bom_to_dataframe(bom_summary: list, floor_multiplier: int = 1) -> pd.DataFrame:
    """
    Convert BOM JSON to a formatted DataFrame for display and export.
    """
    rows = []
    
    for item in bom_summary:
        # Format recipe breakdown
        recipe_details = []
        for mat in item.get("recipe_breakdown", []):
            qty = mat["quantity"] * floor_multiplier
            recipe_details.append(f"{mat['material']}: {qty:.2f} {mat['unit']}")
        
        recipe_str = " | ".join(recipe_details) if recipe_details else "-"
        
        rows.append({
            "Poz No": item["pose_code"],
            "Açıklama": item["description"],
            "Miktar": round(item["total_quantity"] * floor_multiplier, 2),
            "Birim": item["unit"],
            "Kategori": item["category"].upper(),
            "Hesap Detayı (Reçete)": recipe_str
        })
    
    df = pd.DataFrame(rows)
    
    # Sort by category then pose code
    if not df.empty:
        category_order = {"FLOOR": 0, "WALL": 1, "CEILING": 2, "ADDITIONAL": 3}
        df["_sort"] = df["Kategori"].map(category_order)
        df = df.sort_values(["_sort", "Poz No"]).drop("_sort", axis=1)
        df = df.reset_index(drop=True)
    
    return df


def create_excel_download(df: pd.DataFrame, project_name: str, summary: dict) -> bytes:
    """
    Create a formatted Excel file with BOM and summary.
    """
    buffer = BytesIO()
    
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        # Summary sheet
        summary_df = pd.DataFrame([
            {"Parametre": "Proje Adı", "Değer": project_name},
            {"Parametre": "Toplam Alan (m²)", "Değer": summary.get("total_area_m2", 0)},
            {"Parametre": "Blok Sayısı", "Değer": summary.get("block_count", 0)},
            {"Parametre": "Oda Sayısı", "Değer": summary.get("room_count", 0)},
            {"Parametre": "Kat Yüksekliği (m)", "Değer": summary.get("floor_height_m", 2.8)},
            {"Parametre": "Oluşturulma Tarihi", "Değer": datetime.now().strftime("%Y-%m-%d %H:%M")},
        ])
        summary_df.to_excel(writer, sheet_name="Özet", index=False)
        
        # BOM sheet
        df.to_excel(writer, sheet_name="Metraj (BOM)", index=False)
        
        # Auto-adjust column widths
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width
    
    return buffer.getvalue()


def parse_rooms_to_dataframe(blocks: list, floor_multiplier: int = 1) -> pd.DataFrame:
    """
    Create a detailed rooms breakdown dataframe.
    """
    rows = []
    
    for block in blocks:
        block_name = block["name"]
        for floor in block.get("floors", []):
            floor_name = floor["name"]
            for room in floor.get("rooms", []):
                rows.append({
                    "Blok": block_name,
                    "Kat": floor_name,
                    "Oda": room["name"],
                    "Tip": room["room_type"].upper(),
                    "Alan (m²)": round(room["area_m2"] * floor_multiplier, 2),
                    "Çevre (m)": round(room["perimeter_m"], 2),
                    "Duvar Alanı (m²)": round(room["wall_area_m2"] * floor_multiplier, 2),
                    "Açıklık Sayısı": room["opening_count"],
                })
    
    return pd.DataFrame(rows)


# =============================================================================
# MAIN CONTENT - MODE BASED
# =============================================================================

if app_mode == "Metraj Hesaplayıcı":
    # ==========================================================================
    # CALCULATOR MODE (Original UI)
    # ==========================================================================
    st.title("🏗️ İnşaat Metraj Otomasyonu")
    st.markdown("**DWG/DXF** dosyanızı yükleyin, otomatik metraj çıktısı alın.")

    st.markdown("---")

    # File Upload Section
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("📂 Dosya Yükleme")
    
    uploaded_file = st.file_uploader(
        "DWG veya DXF dosyası seçin",
        type=["dwg", "dxf"],
        help="AutoCAD formatında mimari çizim dosyası"
    )
    
    if uploaded_file:
        st.success(f"✅ Dosya yüklendi: **{uploaded_file.name}** ({uploaded_file.size / 1024:.1f} KB)")

    with col2:
        st.subheader("⚡ İşlem")
        
        analyze_button = st.button(
            "🚀 Analiz Başlat",
            disabled=not uploaded_file,
            use_container_width=True
        )

    # =============================================================================
    # ANALYSIS LOGIC & RESULTS DISPLAY
    # =============================================================================

    if analyze_button and uploaded_file:
        with st.spinner("🔄 Dosya işleniyor..."):
            try:
                # Prepare request
                files = {
                    "file": (uploaded_file.name, uploaded_file.getvalue(), "application/octet-stream")
                }
                data = {
                    "drawing_unit": drawing_unit,
                    "project_name": project_name,
                    "floor_height_cm": floor_height_cm
                }
                
                # Send to API
                response = requests.post(
                    f"{api_url}/analyze",
                    files=files,
                    data=data,
                    timeout=120
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # Store in session state
                    st.session_state["analysis_result"] = result
                    st.session_state["floor_multiplier"] = floor_multiplier
                    st.session_state["project_name"] = project_name
                    # Persist project_id in URL for F5 survival
                    if result.get("project_id"):
                        st.query_params["pid"] = result["project_id"]
                    
                    st.success("✅ Analiz tamamlandı!")
                    
                elif response.status_code == 422:
                    error = response.json()
                    st.error(f"❌ İşleme hatası: {error.get('detail', {}).get('message', 'Bilinmeyen hata')}")
                    
                    # Show warnings if any
                    warnings = error.get("detail", {}).get("warnings", [])
                    if warnings:
                        with st.expander("⚠️ Uyarılar"):
                            for w in warnings:
                                st.warning(f"{w['type']}: {w['message']}")
                else:
                    st.error(f"❌ API hatası: {response.status_code} - {response.text[:200]}")
                    
            except requests.exceptions.Timeout:
                st.error("❌ Zaman aşımı: İşlem 120 saniyeden uzun sürdü.")
            except requests.exceptions.ConnectionError:
                st.error("❌ Bağlantı hatası: API'ye ulaşılamıyor. Sunucunun çalıştığından emin olun.")
            except Exception as e:
                st.error(f"❌ Beklenmeyen hata: {str(e)}")

    # AUTO-RESTORE: If session is empty but project_id in URL (F5 survival)
    if "analysis_result" not in st.session_state and "pid" in st.query_params:
        _pid = st.query_params["pid"]
        try:
            _resp = requests.get(f"{api_url}/projects/{_pid}", timeout=15)
            if _resp.status_code == 200:
                _data = _resp.json()
                st.session_state["analysis_result"] = _data
                st.session_state["floor_multiplier"] = 1
                st.session_state["project_name"] = _data.get("project_name", "Yüklenen Proje")
        except Exception:
            pass  # Silently fail — user can re-upload

    # DISPLAY RESULTS SECTION (Moved inside the same if app_mode block)
    if "analysis_result" in st.session_state:
        result = st.session_state["analysis_result"]
        floor_mult = st.session_state.get("floor_multiplier", 1)
        proj_name = st.session_state.get("project_name", "Proje")
        
        st.markdown("---")
        st.subheader("📊 Analiz Sonuçları")
        
        # Summary Cards
        summary = result.get("summary", {})
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
            <div class="metric-card">
                <p class="metric-value">{summary.get('total_area_m2', 0):.1f}</p>
                <p class="metric-label">Toplam Alan (m²)</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="metric-card">
                <p class="metric-value">{summary.get('block_count', 0)}</p>
                <p class="metric-label">Blok Sayısı</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="metric-card">
                <p class="metric-value">{summary.get('room_count', 0)}</p>
                <p class="metric-label">Oda Sayısı</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            if floor_mult > 1:
                multiplied_area = summary.get('total_area_m2', 0) * floor_mult
                st.markdown(f"""
                <div class="metric-card" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);">
                    <p class="metric-value">{multiplied_area:.1f}</p>
                    <p class="metric-label">Çarpanlı Alan ({floor_mult}x)</p>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="metric-card">
                    <p class="metric-value">{summary.get('floor_height_m', 2.8)}</p>
                    <p class="metric-label">Kat Yüksekliği (m)</p>
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Floor Plan Visualization — always regenerate from current data
        # so Inspector edits (added openings, changed room types) are reflected
        floor_plan_b64 = None
        try:
            from visualization import generate_floor_plan_from_data
            blocks_data = result.get("blocks", [])
            if blocks_data:
                floor_plan_b64 = generate_floor_plan_from_data(
                    blocks_data,
                    title=f"Kat Planı — {result.get('project_name', proj_name)}",
                    dark_mode=True
                )
        except Exception as e:
            # Fallback to stored image if renderer fails
            floor_plan_b64 = result.get("floor_plan_image")
            if not floor_plan_b64:
                st.warning(f"Kat planı üretilemedi: {e}")
        
        if floor_plan_b64:
            with st.expander("🗺️ Kat Planı Görselleştirmesi", expanded=True):
                try:
                    image_bytes = base64.b64decode(floor_plan_b64)
                    st.image(
                        image_bytes,
                        caption="Tespit Edilen Odalar ve Açıklıklar (Kapı: kesikli sarı, Pencere: cam göbeği)",
                        use_container_width=True
                    )
                except Exception as e:
                    st.warning(f"Görsel yüklenemedi: {e}")
        
        # Warnings
        warnings = result.get("warnings", [])
        if warnings:
            with st.expander(f"⚠️ Uyarılar ({len(warnings)} adet)", expanded=False):
                for w in warnings:
                    st.warning(f"**{w['type']}**: {w['message']}")

        # v1.2: MATERIAL PREFERENCES — Redesigned
        with st.expander("🎨 Malzeme Tercihleri", expanded=False):
            st.caption("Her oda için zemin, duvar ve tavan malzemesini seçin.")
            
            # Material catalog with Turkish descriptions
            FLOOR_MATERIALS = {
                "26.006/1": "🟫 Seramik Karo (30×30)",
                "26.011/1": "🪵 Laminat Parke",
                "26.021/1": "🏔️ Doğal Mermer",
                "25.116.1100": "🔲 Granit Karo (60×60)",
            }
            WALL_MATERIALS = {
                "25.048/1": "🎨 Saten Boya (İç Cephe)",
                "25.034/2": "🧱 Seramik Fayans (Duvar)",
                "27.581/1": "🪟 Alçı Panel (Alçıpan)",
                "26.012/1": "🏔️ Mermer Kaplama",
            }
            CEIL_MATERIALS = {
                "25.048/1": "🎨 Saten Boya (Tavan)",
                "27.535/1": "🔳 Asma Tavan (60×60 Panel)",
                "18.461/1": "💧 Su Bazlı Boya",
            }
            
            blocks = result.get("blocks", [])
            
            # Collect all rooms
            all_rooms_mat = []
            for block in blocks:
                bn = block.get("name", "Blok")
                for floor in block.get("floors", []):
                    for room in floor.get("rooms", []):
                        rn = room.get("name", "Oda")
                        all_rooms_mat.append({"block": bn, "room": rn, "ref": room})
            
            if not all_rooms_mat:
                st.info("Henüz oda verisi yok.")
            else:
                # Room selector
                room_labels = [f"{r['room']} ({r['block']})" for r in all_rooms_mat]
                selected_mat_room_idx = st.selectbox(
                    "📍 Oda Seçin", range(len(room_labels)),
                    format_func=lambda i: room_labels[i],
                    key="mat_room_selector"
                )
                
                sel_r = all_rooms_mat[selected_mat_room_idx]
                room_key = f"{sel_r['block']}_{sel_r['room']}"
                
                # Initialize defaults
                if "material_overrides" not in st.session_state:
                    st.session_state["material_overrides"] = {}
                if room_key not in st.session_state["material_overrides"]:
                    st.session_state["material_overrides"][room_key] = {
                        "floor": "26.006/1", "wall": "25.048/1", "ceiling": "25.048/1"
                    }
                
                overrides = st.session_state["material_overrides"][room_key]
                
                st.markdown("---")
                
                # --- FLOOR ---
                st.markdown("##### 🟫 Zemin Malzemesi")
                floor_codes = list(FLOOR_MATERIALS.keys())
                floor_labels = list(FLOOR_MATERIALS.values())
                f_idx = floor_codes.index(overrides["floor"]) if overrides["floor"] in floor_codes else 0
                new_floor_idx = st.radio(
                    "Zemin seçin", range(len(floor_labels)),
                    format_func=lambda i: floor_labels[i],
                    index=f_idx, horizontal=True,
                    key=f"matf_{room_key}", label_visibility="collapsed"
                )
                overrides["floor"] = floor_codes[new_floor_idx]
                
                # --- WALL ---
                st.markdown("##### 🧱 Duvar Malzemesi")
                wall_codes = list(WALL_MATERIALS.keys())
                wall_labels = list(WALL_MATERIALS.values())
                w_idx = wall_codes.index(overrides["wall"]) if overrides["wall"] in wall_codes else 0
                new_wall_idx = st.radio(
                    "Duvar seçin", range(len(wall_labels)),
                    format_func=lambda i: wall_labels[i],
                    index=w_idx, horizontal=True,
                    key=f"matw_{room_key}", label_visibility="collapsed"
                )
                overrides["wall"] = wall_codes[new_wall_idx]
                
                # --- CEILING ---
                st.markdown("##### 💡 Tavan Malzemesi")
                ceil_codes = list(CEIL_MATERIALS.keys())
                ceil_labels = list(CEIL_MATERIALS.values())
                c_idx = ceil_codes.index(overrides["ceiling"]) if overrides["ceiling"] in ceil_codes else 0
                new_ceil_idx = st.radio(
                    "Tavan seçin", range(len(ceil_labels)),
                    format_func=lambda i: ceil_labels[i],
                    index=c_idx, horizontal=True,
                    key=f"matc_{room_key}", label_visibility="collapsed"
                )
                overrides["ceiling"] = ceil_codes[new_ceil_idx]
                
                # Summary card
                st.markdown("---")
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, rgba(102,126,234,0.15), rgba(118,75,162,0.15)); 
                            border-radius: 12px; padding: 16px; border: 1px solid rgba(255,255,255,0.1);">
                    <p style="margin:0 0 8px; font-weight:600; color:#ccc;">📋 Seçim Özeti — {sel_r['room']}</p>
                    <table style="width:100%; color:#eee; font-size:14px;">
                        <tr><td>🟫 Zemin</td><td><b>{FLOOR_MATERIALS.get(overrides['floor'], overrides['floor'])}</b></td><td style="color:#888">{overrides['floor']}</td></tr>
                        <tr><td>🧱 Duvar</td><td><b>{WALL_MATERIALS.get(overrides['wall'], overrides['wall'])}</b></td><td style="color:#888">{overrides['wall']}</td></tr>
                        <tr><td>💡 Tavan</td><td><b>{CEIL_MATERIALS.get(overrides['ceiling'], overrides['ceiling'])}</b></td><td style="color:#888">{overrides['ceiling']}</td></tr>
                    </table>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("")
                
                col_save, col_all = st.columns(2)
                with col_save:
                    if st.button("💾 Bu Odayı Kaydet", use_container_width=True, key="save_mat_single"):
                        st.success(f"✅ {sel_r['room']} malzemeleri kaydedildi!")
                
                with col_all:
                    if st.button("📋 Tümüne Uygula", use_container_width=True, key="save_mat_all",
                                 help="Bu seçimleri tüm odalara uygular"):
                        for r in all_rooms_mat:
                            rk = f"{r['block']}_{r['room']}"
                            st.session_state["material_overrides"][rk] = {
                                "floor": overrides["floor"],
                                "wall": overrides["wall"],
                                "ceiling": overrides["ceiling"]
                            }
                        st.success(f"✅ {len(all_rooms_mat)} odanın tamamına uygulandı!")
                        st.rerun()
        
        # Tabs for different views
        tab1, tab2, tab3 = st.tabs(["📋 Metraj (BOM)", "🕵️ Müfettiş", "📁 Ham JSON"])
        
        with tab1:
            st.subheader("📋 Malzeme Listesi (Bill of Materials)")
            bom_df = parse_bom_to_dataframe(result.get("bom_summary", []), floor_mult)
            if not bom_df.empty:
                st.dataframe(bom_df, use_container_width=True, height=400)
                
                # Excel Download
                excel_data = create_excel_download(bom_df, proj_name, summary)
                st.download_button(
                    label="📥 Excel İndir (.xlsx)",
                    data=excel_data,
                    file_name=f"{proj_name}_Metraj.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
        
        with tab2:
            st.subheader("🕵️ Müfettiş (Oda Düzenleyici)")
            st.info("Bu bölümde odaların tipini değiştirebilir ve kapı/pencere açıklıklarını düzenleyebilirsiniz.")
            
            # --- Selectors ---
            blocks = result.get("blocks", [])
            col_sel1, col_sel2 = st.columns(2)
            
            with col_sel1:
                block_names = [b["name"] for b in blocks]
                # Default to first block if not set
                idx = 0
                if "insp_block_sel" in st.session_state:
                     try:
                         idx = block_names.index(st.session_state["insp_block_sel"])
                     except:
                         idx = 0
                selected_block_name = st.selectbox("Blok Seçin", block_names, index=idx, key="insp_block_sel")
                selected_block = next((b for b in blocks if b["name"] == selected_block_name), None)
            
            with col_sel2:
                if selected_block:
                    all_rooms = []
                    for f in selected_block.get("floors", []):
                        all_rooms.extend(f.get("rooms", []))
                    room_names = [r["name"] for r in all_rooms]
                    
                    # Default to first room
                    r_idx = 0
                    if "insp_room_sel" in st.session_state:
                        try:
                            # Handle potential error if room detected room list changed
                            if st.session_state["insp_room_sel"] in room_names:
                                r_idx = room_names.index(st.session_state["insp_room_sel"])
                        except:
                            r_idx = 0
                            
                    selected_room_name = st.selectbox("Oda Seçin", room_names, index=r_idx, key="insp_room_sel")
                    selected_room = next((r for r in all_rooms if r["name"] == selected_room_name), None)
                else:
                    selected_room = None

            if selected_room:
                st.divider()
                
                # --- Room Type Map (Turkish labels) ---
                ROOM_TYPE_TR = {
                    "living": "🏠 Yaşam Alanı (Salon/Yatak Odası)",
                    "wet": "🚿 Islak Hacim (Banyo/WC)",
                    "kitchen": "🍳 Mutfak",
                    "hallway": "🚪 Koridor / Hol",
                    "stairs": "🪜 Merdiven",
                    "elevator": "🛗 Asansör / Şaft",
                    "entrance": "🏢 Bina Girişi",
                    "outdoor": "🌿 Balkon / Teras",
                    "storage": "📦 Depo / Kiler",
                    "unknown": "❓ Bilinmeyen",
                }
                room_types_list = list(ROOM_TYPE_TR.keys())
                room_types_labels = list(ROOM_TYPE_TR.values())
                
                # --- Title + Room Type (side by side) ---
                col_title, col_type, col_save_type = st.columns([2, 2, 1])
                
                with col_title:
                    st.markdown(f"### ✏️ {selected_room['name']}")
                
                with col_type:
                    current_type = selected_room.get("room_type", "living")
                    # Normalize old values
                    if current_type == "bedroom": current_type = "living"
                    if current_type == "balcony": current_type = "outdoor"
                    
                    try:
                        type_idx = room_types_list.index(current_type)
                    except ValueError:
                        type_idx = 0
                    
                    new_type_label = st.selectbox(
                        "Oda Tipi",
                        room_types_labels,
                        index=type_idx,
                        key=f"type_sel_{selected_room['name']}"
                    )
                    new_type = room_types_list[room_types_labels.index(new_type_label)]
                
                with col_save_type:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if new_type != current_type:
                        if st.button("⚡ Tipi Kaydet", type="primary", use_container_width=True, key=f"quick_type_{selected_room['name']}"):
                            try:
                                project_id = result.get("project_id")
                                payload = {
                                    "block_name": selected_block_name,
                                    "room_name": selected_room_name,
                                    "update_data": {
                                        "room_type": new_type,
                                        "openings": selected_room.get("openings", [])
                                    }
                                }
                                res = requests.post(f"{api_url}/projects/{project_id}/rooms/update", json=payload)
                                if res.status_code == 200:
                                    selected_room["room_type"] = new_type
                                    st.success(f"✅ Tip güncellendi: {new_type_label}")
                                    st.rerun()
                                else:
                                    st.error(f"Hata: {res.text}")
                            except Exception as e:
                                st.error(f"Hata: {e}")
                
                # --- Metrics Row ---
                m1, m2, m3 = st.columns(3)
                m1.info(f"**Alan:** {selected_room.get('area_m2')} m²")
                m2.info(f"**Çevre:** {selected_room.get('perimeter_m')} m")
                m3.info(f"**Duvar Alanı:** {selected_room.get('wall_area_m2', 0)} m²")
                
                # Openings Editor
                st.markdown("#### Açıklıklar (Kapı/Pencere)")
                
                openings = selected_room.get("openings", [])
                df_openings = pd.DataFrame(openings)
                if df_openings.empty:
                    df_openings = pd.DataFrame(columns=["width_m", "height_m", "type"])
                
                # Standardize column names for display if coming from API
                if "opening_type" in df_openings.columns:
                    df_openings = df_openings.rename(columns={"opening_type": "type"})
                
                # Default height if missing
                if "height_m" not in df_openings.columns:
                    df_openings["height_m"] = 2.1
                
                column_config = {
                    "width_m": st.column_config.NumberColumn("Genişlik (m)", min_value=0.1, max_value=10.0, step=0.1, format="%.2f"),
                    "height_m": st.column_config.NumberColumn("Yükseklik (m)", min_value=0.1, max_value=4.0, step=0.1, format="%.2f"),
                    "type": st.column_config.SelectboxColumn("Tip", options=["door", "window", "opening"], required=True),
                    "location": None 
                }
                
                edited_openings = st.data_editor(
                    df_openings,
                    column_config=column_config,
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    key=f"editor_{selected_room['name']}_{len(openings)}"
                )
                
                col_btn1, col_btn2 = st.columns([1, 1])
                with col_btn1:
                    if st.button("💾 Güncelle ve Hesapla", type="primary", use_container_width=True, key=f"save_{selected_room['name']}"):
                        # Save Logic
                        new_openings_list = []
                        for _, row in edited_openings.iterrows():
                            if row.get("width_m", 0) > 0:
                                new_openings_list.append({
                                    "width_m": float(row["width_m"]),
                                    "height_m": float(row.get("height_m", 2.1)),
                                    "type": row["type"]
                                })
                        
                        payload = {
                            "block_name": selected_block_name,
                            "room_name": selected_room_name,
                            "update_data": {
                                "room_type": new_type,
                                "openings": new_openings_list
                            }
                        }
                        
                        try:
                            project_id = result.get("project_id")
                            res = requests.post(f"{api_url}/projects/{project_id}/rooms/update", json=payload)
                            
                            if res.status_code == 200:
                                st.success("✅ Güncellendi! Veriler yenileniyor...")
                                
                                # RE-FETCH ANALYSIS to ensure sync
                                # We can't easily re-fetch the full file analysis without the file.
                                # BUT, for now let's update the local state manually which is faster.
                                selected_room["room_type"] = new_type
                                selected_room["openings"] = new_openings_list
                                
                                # Better: If we had a GET /projects/{id} endpoint that returned the full analysis json, we could call that.
                                # But we only have GET /projects/{id} which returns DB model, not the full AnalysisResponse format we use here.
                                # So patching is the best MVP approach.
                                
                                st.rerun()
                            else:
                                st.error(f"Hata: {res.text}")
                        except Exception as e:
                            st.error(f"Hata: {e}")

                with col_btn2:
                    if st.button("🗑️ Odayı Sil", type="secondary", use_container_width=True, key=f"del_{selected_room['name']}"):
                        try:
                            project_id = result.get("project_id")
                            res = requests.delete(
                                f"{api_url}/projects/{project_id}/rooms",
                                params={"block_name": selected_block_name, "room_name": selected_room_name}
                            )
                            
                            if res.status_code == 200:
                                st.success("✅ Silindi!")
                                if selected_block:
                                    for f in selected_block.get("floors", []):
                                        f["rooms"] = [r for r in f["rooms"] if r["name"] != selected_room_name]
                                st.rerun()
                            else:
                                st.error(f"Hata: {res.text}")
                        except Exception as e:
                            st.error(f"Hata: {e}")

                # --- v1.2: Bulk Action UI ---
                st.divider()
                st.markdown("#### 🚀 Toplu Pencere/Kapı Kopyala")
                st.caption(f"'{selected_room['name']}' odasındaki açılışları seçilen diğer odalara kopyalar.")
                
                other_room_names = [rn for rn in room_names if rn != selected_room_name]
                target_rooms = st.multiselect("Hedef Odaları Seçin", other_room_names, key=f"bulk_target_{selected_room['name']}")
                
                if st.button("📋 Seçilenlere Kopyala", use_container_width=True, key=f"bulk_btn_{selected_room['name']}"):
                    if not target_rooms:
                        st.warning("Lütfen en az bir hedef oda seçin.")
                    else:
                        payload = {
                            "source_block": selected_block_name,
                            "source_room": selected_room_name,
                            "target_block": selected_block_name,
                            "target_rooms": target_rooms
                        }
                        try:
                            project_id = result.get("project_id")
                            res = requests.post(f"{api_url}/projects/{project_id}/rooms/bulk-copy", json=payload)
                            if res.status_code == 200:
                                st.success(f"✅ {len(target_rooms)} odaya başarıyla kopyalandı!")
                                # Force re-fetch of analysis would be ideal here if possible
                                st.rerun()
                            else:
                                st.error(f"Toplu kopyalama hatası: {res.text}")
                        except Exception as e:
                            st.error(f"İletişim hatası: {e}")

            # --- Restore Original Rooms Table ---
            st.markdown("---")
            with st.expander("📊 Tüm Odaların Listesi (Özet)", expanded=False):
                rooms_df = parse_rooms_to_dataframe(result.get("blocks", []), floor_mult)
                if not rooms_df.empty:
                    st.dataframe(rooms_df, use_container_width=True, height=300)
            
            # --- v1.2: Multi-Block Room Comparison ---
            if len(blocks) > 1:
                st.divider()
                st.subheader("🔀 Bloklar Arası Oda Karşılaştırma")
                st.caption("Aynı isimdeki odaların bloklar arasındaki farklarını gösterir. Alan farkı >%10 olan odalar farklı tip olarak etiketlenir.")
                
                # Collect all rooms per block
                room_variants = {}  # room_name -> [(block_name, area, perimeter, room_type)]
                for block in blocks:
                    b_name = block.get("name", "?")
                    for floor in block.get("floors", []):
                        for room in floor.get("rooms", []):
                            r_name = room.get("name", "?")
                            if r_name not in room_variants:
                                room_variants[r_name] = []
                            room_variants[r_name].append({
                                "blok": b_name,
                                "alan": room.get("area_m2", 0),
                                "cevre": room.get("perimeter_m", 0),
                                "tip": room.get("room_type", "unknown"),
                            })
                
                # Build comparison table
                comparison_rows = []
                for r_name, variants in room_variants.items():
                    if len(variants) < 2:
                        continue
                    
                    # Group by area (>10% difference = different type)
                    areas = [v["alan"] for v in variants]
                    unique_types = []
                    type_map = {}  # area -> type_label
                    
                    for area in sorted(set(areas)):
                        matched = False
                        for ref_area, label in unique_types:
                            if abs(area - ref_area) / max(ref_area, 0.01) < 0.10:
                                type_map[area] = label
                                matched = True
                                break
                        if not matched:
                            label = f"Tip {len(unique_types) + 1}"
                            unique_types.append((area, label))
                            type_map[area] = label
                    
                    for v in variants:
                        tip_label = type_map.get(v["alan"], "?")
                        if len(unique_types) <= 1:
                            tip_label = "Standart"
                        comparison_rows.append({
                            "Oda": r_name,
                            "Blok": v["blok"],
                            "Alt Tip": tip_label,
                            "Alan (m²)": round(v["alan"], 1),
                            "Çevre (m)": round(v["cevre"], 1),
                            "Oda Tipi": v["tip"],
                        })
                
                if comparison_rows:
                    comp_df = pd.DataFrame(comparison_rows)
                    
                    # Highlight different types
                    has_variants = comp_df[comp_df["Alt Tip"] != "Standart"]
                    if not has_variants.empty:
                        st.warning(f"⚠️ {len(has_variants['Oda'].unique())} oda farklı bloklarda farklı boyutlara sahip")
                    
                    st.dataframe(comp_df, use_container_width=True, hide_index=True, height=300)
                else:
                    st.success("✅ Tüm odalar tüm bloklarda aynı boyutlara sahip.")
        
        with tab3:
            st.subheader("📁 Ham JSON Yanıtı")
            st.json(result)
            json_str = json.dumps(result, indent=2, ensure_ascii=False)
            st.download_button(
                label="📥 JSON İndir",
                data=json_str,
                file_name=f"{proj_name}_raw.json",
                mime="application/json"
            )
elif app_mode == "📂 Proje Geçmişi":
    # ==========================================================================
    # PROJECT HISTORY MODE (v1.1)
    # ==========================================================================
    st.title("📂 Proje Geçmişi")
    st.markdown("Kaydedilmiş projeleri görüntüleyin ve yükleyin.")
    
    st.markdown("---")
    
    # Search box
    col_search, col_refresh = st.columns([3, 1])
    with col_search:
        search_term = st.text_input(
            "🔍 Proje Ara",
            placeholder="Proje adı ile arayın...",
            key="project_search"
        )
    with col_refresh:
        st.markdown("<br>", unsafe_allow_html=True)
        refresh_clicked = st.button("🔄 Yenile", use_container_width=True)
    
    # Fetch projects from API
    try:
        params = {"limit": 20, "offset": 0}
        if search_term:
            params["search"] = search_term
        
        response = requests.get(f"{DEFAULT_API_URL}/projects", params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            projects = data.get("projects", [])
            total = data.get("total", 0)
            
            if projects:
                st.success(f"📊 Toplam {total} proje bulundu")
                
                # Display projects as cards
                for project in projects:
                    with st.container():
                        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                        
                        with col1:
                            st.markdown(f"**{project['name']}**")
                            # Format date nicely
                            created = project.get("created_at", "")
                            if created:
                                try:
                                    from datetime import datetime as dt
                                    date_obj = dt.fromisoformat(created.replace("Z", "+00:00"))
                                    date_str = date_obj.strftime("%d.%m.%Y %H:%M")
                                except:
                                    date_str = created[:16]
                                st.caption(f"📅 {date_str}")
                        
                        with col2:
                            area = project.get("total_area_m2", 0)
                            st.metric("Alan", f"{area:.1f} m²" if area else "-")
                        
                        with col3:
                            room_count = project.get("room_count", 0)
                            st.metric("Oda", str(room_count) if room_count else "-")
                        
                        with col4:
                            # Load button
                            if st.button("📂 Yükle", key=f"load_{project['id']}", use_container_width=True):
                                # Load project from API
                                with st.spinner("Proje yükleniyor..."):
                                    load_response = requests.get(
                                        f"{DEFAULT_API_URL}/projects/{project['id']}",
                                        timeout=30
                                    )
                                    if load_response.status_code == 200:
                                        loaded_data = load_response.json()
                                        st.session_state["analysis_result"] = loaded_data
                                        st.session_state["floor_multiplier"] = 1
                                        st.session_state["project_name"] = loaded_data.get("project_name", "Yüklenen Proje")
                                        # Persist project_id in URL for F5 survival
                                        if loaded_data.get("project_id"):
                                            st.query_params["pid"] = loaded_data["project_id"]
                                        st.success("✅ Proje yüklendi! Metraj Hesaplayıcı moduna geçin.")
                                        st.rerun()
                                    else:
                                        st.error("❌ Proje yüklenemedi!")
                        
                        # Delete button (expandable)
                        with st.expander("⚠️ Tehlikeli İşlemler", expanded=False):
                            if st.button("🗑️ Projeyi Sil", key=f"delete_{project['id']}", type="secondary"):
                                delete_response = requests.delete(
                                    f"{DEFAULT_API_URL}/projects/{project['id']}",
                                    timeout=10
                                )
                                if delete_response.status_code == 200:
                                    st.success("✅ Proje silindi!")
                                    # Clear the session state if the deleted project was the one currently loaded
                                    if st.session_state.get("analysis_result", {}).get("project_id") == project['id']:
                                        del st.session_state["analysis_result"]
                                        if "project_name" in st.session_state:
                                            del st.session_state["project_name"]
                                        if "floor_multiplier" in st.session_state:
                                            del st.session_state["floor_multiplier"]
                                    st.rerun()
                                else:
                                    st.error("❌ Silme işlemi başarısız!")
                        
                        st.markdown("---")
            else:
                st.info("📭 Henüz kayıtlı proje bulunmuyor.")
                st.markdown("""
                **Proje kaydetmek için:**
                1. **Metraj Hesaplayıcı** moduna geçin
                2. Bir DXF/DWG dosyası yükleyin
                3. Analiz yapın - proje otomatik kaydedilecek
                """)
        else:
            st.error(f"❌ API hatası: {response.status_code}")
    except requests.exceptions.ConnectionError:
        st.error("❌ API'ye bağlanılamadı. Backend'in çalıştığından emin olun.")
    except Exception as e:
        st.error(f"❌ Hata: {str(e)}")

else:
    # ==========================================================================
    # ADMIN PANEL MODE
    # ==========================================================================
    st.title("🔧 Admin Paneli - Poz Veri Yönetimi")
    st.markdown("Excel dosyasından toplu poz yükleyin veya mevcut pozları görüntüleyin.")
    
    # Check authentication
    if not st.session_state.get("admin_authenticated", False):
        st.warning("⚠️ Admin paneline erişmek için sol panelden şifre girin.")
        st.info("💡 Varsayılan şifre: **admin123**")
        st.stop()
    
    st.markdown("---")
    
    # Admin Tabs
    admin_tab1, admin_tab2, admin_tab3 = st.tabs(["📤 Toplu Yükleme", "📋 Mevcut Pozlar", "📊 İstatistikler"])
    
    with admin_tab1:
        st.subheader("📤 Excel'den Toplu Poz Yükleme")
        
        st.markdown("""
        **Kullanım Adımları:**
        1. Aşağıdan **boş şablon** indirin
        2. Excel'i doldurun (Poz No zorunlu)
        3. Doldurulmuş dosyayı yükleyin
        4. **Upsert** işlemi: Varsa günceller, yoksa ekler
        """)
        
        col_template, col_upload = st.columns(2)
        
        with col_template:
            st.markdown("#### 📥 Şablon İndir")
            
            # Create template DataFrame
            template_df = pd.DataFrame({
                "Poz No": ["16.001/1", "ÖRNEK-001"],
                "Tanım": ["C25 Beton Dökümü", "Örnek açıklama yazın"],
                "Birim": ["m³", "m²"],
                "Kategori": ["Beton", "Diğer"],
                "Birim Fiyat (TRY)": [3500.00, 0]
            })
            
            # Convert to Excel bytes
            from io import BytesIO
            template_buffer = BytesIO()
            with pd.ExcelWriter(template_buffer, engine='openpyxl') as writer:
                template_df.to_excel(writer, index=False, sheet_name='Pozlar')
            template_buffer.seek(0)
            
            st.download_button(
                label="📄 Boş Şablon İndir (.xlsx)",
                data=template_buffer,
                file_name="poz_sablonu.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            
            st.caption("Şablon: Poz No, Tanım, Birim, Kategori, Birim Fiyat")
        
        with col_upload:
            st.markdown("#### 📤 Dosya Yükle")
            
            uploaded_excel = st.file_uploader(
                "Excel dosyası seçin (.xlsx)",
                type=["xlsx"],
                help="Şablona uygun formatta Excel"
            )
            
            if uploaded_excel:
                st.success(f"✅ {uploaded_excel.name} yüklendi")
        
        st.markdown("---")
        
        # Import Button
        if uploaded_excel:
            st.subheader("🚀 İçe Aktarım")
            
            # Preview data
            try:
                preview_df = pd.read_excel(uploaded_excel)
                st.markdown(f"**Önizleme:** {len(preview_df)} satır bulundu")
                st.dataframe(preview_df.head(10), use_container_width=True)
                
                # DEBUG: Show column info
                with st.expander("🔍 Debug: Sütun Bilgileri", expanded=False):
                    st.write("**Excel Sütunları:**", list(preview_df.columns))
                    if len(preview_df) > 0:
                        st.write("**İlk satır değerleri:**")
                        for col in preview_df.columns:
                            val = preview_df.iloc[0][col]
                            st.write(f"  - `{col}`: `{val}` (type: {type(val).__name__})")
                
                # Column mapping (handle both "Birim Fiyat" and "BirimFiyat" variants)
                col_mapping = {
                    "Poz No": "code",
                    "Tanım": "description", 
                    "Birim": "unit",
                    "Kategori": "category",
                    "Birim Fiyat (TRY)": "default_unit_price",
                    "BirimFiyat (TRY)": "default_unit_price",  # Alternative without space
                    "Birim Fiyat": "default_unit_price",       # Without currency
                    "BirimFiyat": "default_unit_price",        # Without space and currency
                    "Fiyat": "default_unit_price",             # Short form
                    "Fiyat (TRY)": "default_unit_price",       # Short with currency
                }
                
                if st.button("🔄 İçe Aktarmayı Başlat", type="primary", use_container_width=True):
                    # Reset file position
                    uploaded_excel.seek(0)
                    import_df = pd.read_excel(uploaded_excel)
                    
                    # Rename columns
                    import_df = import_df.rename(columns=col_mapping)
                    
                    # DEBUG: Show mapped data
                    st.info(f"🔍 Mapped columns: {list(import_df.columns)}")
                    if len(import_df) > 0:
                        first_row = import_df.iloc[0].to_dict()
                        price_val = first_row.get('default_unit_price', 'NOT FOUND')
                        st.info(f"🔍 First row price: {price_val} (type: {type(price_val).__name__})")
                    
                    # Convert to list of dicts
                    poses_data = import_df.to_dict('records')
                    
                    # Progress bar
                    progress_bar = st.progress(0, text="İçe aktarılıyor...")
                    status_text = st.empty()
                    
                    def update_progress(current, total):
                        progress_bar.progress(current / total, text=f"İşleniyor: {current}/{total}")
                    
                    # Import using database function
                    try:
                        from database import bulk_upsert_poses
                        
                        results = bulk_upsert_poses(
                            poses_data=poses_data,
                            batch_size=100,
                            progress_callback=update_progress
                        )
                        
                        progress_bar.progress(1.0, text="Tamamlandı!")
                        
                        # Show results
                        st.success(f"""
                        ✅ **İçe Aktarım Tamamlandı!**
                        - 🆕 Eklenen: **{results['inserted']}** poz
                        - 🔄 Güncellenen: **{results['updated']}** poz  
                        - ❌ Hata: **{len(results['errors'])}** satır
                        """)
                        
                        if results['errors']:
                            with st.expander("⚠️ Hatalar", expanded=False):
                                for err in results['errors'][:20]:
                                    st.error(err)
                                if len(results['errors']) > 20:
                                    st.warning(f"... ve {len(results['errors']) - 20} hata daha")
                                    
                    except Exception as e:
                        st.error(f"❌ İçe aktarım hatası: {str(e)}")
                        
            except Exception as e:
                st.error(f"❌ Excel okuma hatası: {str(e)}")
    
    with admin_tab2:
        st.subheader("📋 Mevcut Pozlar")
        
        try:
            from database import get_all_poses_for_export
            
            poses = get_all_poses_for_export()
            
            if poses:
                poses_df = pd.DataFrame(poses)
                
                # Filter
                search_query = st.text_input("🔍 Ara (Poz No veya Tanım)", "")
                
                if search_query:
                    mask = (
                        poses_df["Poz No"].str.contains(search_query, case=False, na=False) |
                        poses_df["Tanım"].str.contains(search_query, case=False, na=False)
                    )
                    filtered_df = poses_df[mask]
                else:
                    filtered_df = poses_df
                
                st.info(f"📊 Toplam: **{len(poses_df)}** poz | Gösterilen: **{len(filtered_df)}**")
                
                st.dataframe(
                    filtered_df,
                    use_container_width=True,
                    height=500,
                    column_config={
                        "Birim Fiyat (TRY)": st.column_config.NumberColumn(
                            "Birim Fiyat (TRY)",
                            format="%.2f ₺"
                        )
                    }
                )
                
                # Export button
                export_buffer = BytesIO()
                with pd.ExcelWriter(export_buffer, engine='openpyxl') as writer:
                    poses_df.to_excel(writer, index=False, sheet_name='Tüm Pozlar')
                export_buffer.seek(0)
                
                st.download_button(
                    label="📥 Tüm Pozları İndir (.xlsx)",
                    data=export_buffer,
                    file_name=f"tum_pozlar_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("Henüz poz kaydı bulunamadı.")
                
        except Exception as e:
            st.error(f"Veritabanı hatası: {str(e)}")
    
    with admin_tab3:
        st.subheader("📊 Veritabanı İstatistikleri")
        
        try:
            from database import get_all_poses_for_export
            
            poses = get_all_poses_for_export()
            
            if poses:
                poses_df = pd.DataFrame(poses)
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Toplam Poz", len(poses_df))
                
                with col2:
                    kategori_sayisi = poses_df["Kategori"].nunique()
                    st.metric("Kategori Sayısı", kategori_sayisi)
                
                with col3:
                    fiyatli = (poses_df["Birim Fiyat (TRY)"] > 0).sum()
                    st.metric("Fiyatlı Poz", fiyatli)
                
                st.markdown("---")
                
                st.markdown("#### 📈 Kategori Dağılımı")
                kategori_counts = poses_df["Kategori"].value_counts()
                st.bar_chart(kategori_counts)
                
                st.markdown("#### 📋 Birim Dağılımı")
                birim_counts = poses_df["Birim"].value_counts()
                st.bar_chart(birim_counts)
            else:
                st.info("İstatistik için veri bulunamadı.")
                
        except Exception as e:
            st.error(f"İstatistik hatası: {str(e)}")


# =============================================================================
# FOOTER
# =============================================================================

st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: #666; font-size: 0.85rem;">
        🏗️ <strong>İnşaat Metraj Otomasyonu</strong> v1.2.0 (Faz 3) | 
        Powered by FastAPI + Streamlit | 
        © 2026 AI Solutions
    </div>
    """,
    unsafe_allow_html=True
)
