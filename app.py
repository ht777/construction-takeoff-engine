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

with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/building.png", width=80)
    st.title("🏗️ Metraj Ayarları")
    
    st.markdown("---")
    
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


# =============================================================================
# MAIN CONTENT
# =============================================================================

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
    
    # Warnings
    warnings = result.get("warnings", [])
    if warnings:
        with st.expander(f"⚠️ Uyarılar ({len(warnings)} adet)", expanded=False):
            for w in warnings:
                st.warning(f"**{w['type']}**: {w['message']}")
    
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
