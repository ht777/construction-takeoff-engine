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
DEFAULT_API_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")


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
            help="FastAPI backend adresi (Docker: http://backend:8000)"
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

# Set default values for non-calculator modes (prevents NameError)
if app_mode != "Metraj Hesaplayıcı":
    api_url = DEFAULT_API_URL
    drawing_unit = "cm"
    floor_height_cm = 280
    floor_multiplier = 1
    project_name = "Proje"
    uploaded_file = None
    analyze_button = False


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
# ANALYSIS LOGIC
# =============================================================================

def parse_bom_to_dataframe(bom_summary: list, floor_multiplier: int = 1) -> pd.DataFrame:
    """
    Convert BOM JSON to a formatted DataFrame for display and export.
    
    Columns:
    - Poz No: Pose code
    - Açıklama: Description  
    - Miktar: Quantity (multiplied by floor count)
    - Birim: Unit
    - Hesap Detayı: Recipe breakdown
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
# EXECUTE ANALYSIS
# =============================================================================

if app_mode == "Metraj Hesaplayıcı" and analyze_button and uploaded_file:
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


# =============================================================================
# DISPLAY RESULTS
# =============================================================================

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
    
    # v1.1: Floor Plan Visualization
    floor_plan_b64 = result.get("floor_plan_image")
    if floor_plan_b64:
        with st.expander("🗺️ Kat Planı Görselleştirmesi", expanded=True):
            try:
                # Decode base64 to bytes
                image_bytes = base64.b64decode(floor_plan_b64)
                st.image(
                    image_bytes,
                    caption="Tespit Edilen Odalar ve Alanlar",
                    use_container_width=True
                )
                st.markdown("""
                <div style="text-align: center; color: #888; font-size: 0.9em;">
                    💡 Renk kodları: Mavi=Salon, Yeşil=Yatak Odası, Turuncu=Mutfak, Mavi-Yeşil=Islak Hacim
                </div>
                """, unsafe_allow_html=True)
            except Exception as e:
                st.warning(f"Görsel yüklenemedi: {e}")
    
    # Warnings
    warnings = result.get("warnings", [])
    if warnings:
        with st.expander(f"⚠️ Uyarılar ({len(warnings)} adet)", expanded=False):
            for w in warnings:
                st.warning(f"**{w['type']}**: {w['message']}")
    
    # =========================================================================
    # v1.1: MATERIAL PREFERENCES SECTION
    # =========================================================================
    
    with st.expander("🛠️ Malzeme Tercihleri (v1.1)", expanded=False):
        st.markdown("""
        Bu bölümde her oda için otomatik atanan malzemeleri değiştirebilirsiniz.
        Değişiklik yaptıktan sonra **"Metrajı Güncelle"** butonuna tıklayın.
        """)
        
        # Get detected rooms from blocks
        blocks = result.get("blocks", [])
        analysis_id = result.get("project_id", "")
        
        # Fetch available poses by surface type from API
        try:
            floor_poses_resp = requests.get(f"{DEFAULT_API_URL}/poses/by-surface/floor", timeout=10)
            wall_poses_resp = requests.get(f"{DEFAULT_API_URL}/poses/by-surface/wall", timeout=10)
            ceiling_poses_resp = requests.get(f"{DEFAULT_API_URL}/poses/by-surface/ceiling", timeout=10)
            
            floor_poses = floor_poses_resp.json().get("poses", []) if floor_poses_resp.ok else []
            wall_poses = wall_poses_resp.json().get("poses", []) if wall_poses_resp.ok else []
            ceiling_poses = ceiling_poses_resp.json().get("poses", []) if ceiling_poses_resp.ok else []
        except:
            floor_poses = []
            wall_poses = []
            ceiling_poses = []
        
        # Initialize material overrides in session state
        if "material_overrides" not in st.session_state:
            st.session_state["material_overrides"] = {}
        
        # Show room-by-room material selection
        room_counter = 0
        for block in blocks:
            for floor in block.get("floors", []):
                for room in floor.get("rooms", []):
                    room_name = room.get("name", f"Oda {room_counter}")
                    room_type = room.get("room_type", "unknown")
                    room_area = room.get("area_m2", 0)
                    room_id = f"room_{hash(room_name) % 10000}"
                    
                    st.markdown(f"#### {room_name} ({room_area:.1f} m²)")
                    
                    # Get current materials from room
                    current_materials = room.get("materials", [])
                    current_floor = next((m for m in current_materials if "döşeme" in m.get("category", "").lower() or "floor" in m.get("category", "").lower()), None)
                    current_wall = next((m for m in current_materials if "duvar" in m.get("category", "").lower() or "wall" in m.get("category", "").lower()), None)
                    current_ceiling = next((m for m in current_materials if "tavan" in m.get("category", "").lower() or "ceiling" in m.get("category", "").lower()), None)
                    
                    col_f, col_w, col_c = st.columns(3)
                    
                    # Floor material selector
                    with col_f:
                        floor_options = ["Otomatik"] + [p["display"] for p in floor_poses]
                        floor_default = current_floor.get("pose_code", "Otomatik") if current_floor else "Otomatik"
                        selected_floor = st.selectbox(
                            "🪵 Döşeme",
                            options=floor_options,
                            key=f"floor_{room_id}",
                            help="Döşeme malzemesi seçin"
                        )
                        if selected_floor != "Otomatik":
                            st.session_state["material_overrides"][f"{room_id}_floor"] = selected_floor.split(" - ")[0]
                    
                    # Wall material selector
                    with col_w:
                        wall_options = ["Otomatik"] + [p["display"] for p in wall_poses]
                        wall_default = current_wall.get("pose_code", "Otomatik") if current_wall else "Otomatik"
                        selected_wall = st.selectbox(
                            "🧱 Duvar",
                            options=wall_options,
                            key=f"wall_{room_id}",
                            help="Duvar malzemesi seçin"
                        )
                        if selected_wall != "Otomatik":
                            st.session_state["material_overrides"][f"{room_id}_wall"] = selected_wall.split(" - ")[0]
                    
                    # Ceiling material selector
                    with col_c:
                        ceiling_options = ["Otomatik"] + [p["display"] for p in ceiling_poses]
                        ceiling_default = current_ceiling.get("pose_code", "Otomatik") if current_ceiling else "Otomatik"
                        selected_ceiling = st.selectbox(
                            "🔲 Tavan",
                            options=ceiling_options,
                            key=f"ceiling_{room_id}",
                            help="Tavan malzemesi seçin"
                        )
                        if selected_ceiling != "Otomatik":
                            st.session_state["material_overrides"][f"{room_id}_ceiling"] = selected_ceiling.split(" - ")[0]
                    
                    st.markdown("---")
                    room_counter += 1
        
        # Recalculate button
        if st.button("🔄 Metrajı Güncelle", type="primary", use_container_width=True):
            overrides = st.session_state.get("material_overrides", {})
            
            if not overrides:
                st.info("Değişiklik yapılmadı. Varsayılan malzemeler kullanılıyor.")
            else:
                # Build override list for API
                override_list = []
                for key, pose_code in overrides.items():
                    parts = key.rsplit("_", 1)
                    if len(parts) == 2:
                        room_id, surface_type = parts
                        override_list.append({
                            "room_id": room_id,
                            "surface_type": surface_type,
                            "new_pose_code": pose_code
                        })
                
                try:
                    recalc_response = requests.post(
                        f"{DEFAULT_API_URL}/recalculate",
                        json={
                            "analysis_id": analysis_id,
                            "overrides": override_list,
                            "floor_height_cm": int(summary.get("floor_height_m", 2.8) * 100)
                        },
                        timeout=60
                    )
                    
                    if recalc_response.ok:
                        recalc_result = recalc_response.json()
                        # Update BOM in session state
                        result["bom_summary"] = recalc_result.get("bom_summary", [])
                        st.session_state["analysis_result"] = result
                        st.success(f"✅ Metraj güncellendi! {recalc_result.get('overrides_applied', 0)} değişiklik uygulandı.")
                        st.rerun()
                    else:
                        st.error(f"❌ Güncelleme hatası: {recalc_response.text[:200]}")
                except Exception as e:
                    st.error(f"❌ Bağlantı hatası: {str(e)}")
    
    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["📋 Metraj (BOM)", "🏠 Oda Detayları", "📁 Ham JSON"])
    
    with tab1:
        st.subheader("📋 Malzeme Listesi (Bill of Materials)")
        
        bom_df = parse_bom_to_dataframe(result.get("bom_summary", []), floor_mult)
        
        if not bom_df.empty:
            # Display styled dataframe
            st.dataframe(
                bom_df,
                use_container_width=True,
                height=400,
                column_config={
                    "Poz No": st.column_config.TextColumn("Poz No", width="small"),
                    "Açıklama": st.column_config.TextColumn("Açıklama", width="medium"),
                    "Miktar": st.column_config.NumberColumn("Miktar", format="%.2f"),
                    "Birim": st.column_config.TextColumn("Birim", width="small"),
                    "Kategori": st.column_config.TextColumn("Kategori", width="small"),
                    "Hesap Detayı (Reçete)": st.column_config.TextColumn("Hesap Detayı", width="large"),
                }
            )
            
            # Category Summary
            st.markdown("#### 📊 Kategori Özeti")
            category_summary = bom_df.groupby("Kategori").agg({
                "Poz No": "count"
            }).rename(columns={"Poz No": "Poz Sayısı"})
            st.dataframe(category_summary, use_container_width=True)
            
            # Excel Download
            st.markdown("---")
            
            excel_data = create_excel_download(bom_df, proj_name, summary)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"{proj_name.replace(' ', '_')}_Metraj_{timestamp}.xlsx"
            
            st.download_button(
                label="📥 Excel İndir (.xlsx)",
                data=excel_data,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.info("BOM verisi bulunamadı.")
    
    with tab2:
        st.subheader("🏠 Oda Bazlı Detaylar")
        
        rooms_df = parse_rooms_to_dataframe(result.get("blocks", []), floor_mult)
        
        if not rooms_df.empty:
            st.dataframe(
                rooms_df,
                use_container_width=True,
                height=400,
                column_config={
                    "Alan (m²)": st.column_config.NumberColumn("Alan (m²)", format="%.2f"),
                    "Çevre (m)": st.column_config.NumberColumn("Çevre (m)", format="%.2f"),
                    "Duvar Alanı (m²)": st.column_config.NumberColumn("Duvar Alanı (m²)", format="%.2f"),
                }
            )
            
            # Room type distribution
            st.markdown("#### 📊 Oda Tipi Dağılımı")
            room_type_counts = rooms_df["Tip"].value_counts()
            st.bar_chart(room_type_counts)
        else:
            st.info("Oda verisi bulunamadı.")
    
    with tab3:
        st.subheader("📁 Ham JSON Yanıtı")
        
        st.json(result)
        
        # Download JSON
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
        🏗️ <strong>İnşaat Metraj Otomasyonu</strong> v1.0.0 | 
        Powered by FastAPI + Streamlit | 
        © 2026 AI Solutions
    </div>
    """,
    unsafe_allow_html=True
)
