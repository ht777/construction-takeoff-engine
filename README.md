# Construction Quantity Takeoff Engine

İnşaat Metraj ve Maliyet Otomasyonu - Türkiye Pazarı için Profesyonel Backend Sistemi

## 🏗️ Özellikler

- **DWG/DXF Desteği**: ODA File Converter ile otomatik DWG dönüşümü
- **Akıllı Geometri İşleme**: DBSCAN ile çoklu blok tespiti, gap healing
- **Oda Tanıma**: Türkçe/İngilizce metin eşleştirme ile otomatik oda tipi belirleme
- **Malzeme Atama**: Oda tipine göre otomatik pose atama
- **ÇŞB Uyumlu**: 20 temel Türk inşaat pozu ile hazır veritabanı
- **Reçete Motoru**: Her poz için detaylı malzeme analizi

## 📁 Dosya Yapısı

```
construction-takeoff-engine/
├── config.py           # Konfigürasyon ve sabitler
├── database.py         # SQLAlchemy modelleri ve seed data
├── geometry_engine.py  # CAD işleme motoru
├── main.py            # FastAPI uygulaması
├── requirements.txt   # Python bağımlılıkları
└── .env.example       # Örnek environment dosyası
```

## 🚀 Kurulum

### 1. Veritabanı Kurulumu

```bash
# PostgreSQL kurulumu (Windows)
# https://www.postgresql.org/download/windows/

# Veritabanı oluşturma
psql -U postgres
CREATE DATABASE construction_takeoff;
\q
```

### 2. Python Ortamı

```bash
# Virtual environment oluştur
python -m venv venv
.\venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Bağımlılıkları yükle
pip install -r requirements.txt
```

### 3. Environment Ayarları

```bash
# .env dosyası oluştur
copy .env.example .env
# .env dosyasını düzenle ve DB_PASSWORD'u ayarla
```

### 4. Veritabanını Başlat

```bash
# Tabloları oluştur ve seed data'yı yükle
python database.py
```

### 5. Sunucuyu Başlat

```bash
# Development modu
uvicorn main:app --reload

# Production modu
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 📡 API Endpoints

### Ana Endpoint

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| `POST` | `/analyze` | DWG/DXF dosyası yükle ve analiz et |
| `GET` | `/poses` | Tüm referans pozları listele |
| `GET` | `/poses/{code}/recipes` | Bir pozun reçetesini al |
| `GET` | `/room-types` | Oda tipi ve malzeme eşleştirmelerini listele |
| `GET` | `/health` | Sistem sağlık kontrolü |

### Örnek Kullanım

```bash
# Dosya yükleme ve analiz
curl -X POST "http://localhost:8000/analyze" \
  -F "file=@proje.dxf" \
  -F "drawing_unit=cm" \
  -F "project_name=Test Proje" \
  -F "floor_height_cm=280"
```

### Örnek Yanıt

```json
{
  "project_id": "uuid-here",
  "project_name": "Test Proje",
  "calculated_at": "2026-02-06T20:00:00Z",
  "summary": {
    "total_area_m2": 125.5,
    "block_count": 1,
    "room_count": 5
  },
  "blocks": [
    {
      "name": "Ana Bina",
      "floors": [
        {
          "name": "Zemin Kat",
          "rooms": [
            {
              "name": "SALON",
              "room_type": "living",
              "area_m2": 28.5,
              "materials": [...]
            }
          ]
        }
      ]
    }
  ],
  "bom_summary": [
    {
      "pose_code": "26.006/1",
      "description": "Laminat Parke (8 mm, AC4)",
      "total_quantity": 85.3,
      "unit": "m²",
      "recipe_breakdown": [...]
    }
  ]
}
```

## 🧠 Algoritma Açıklamaları

### DBSCAN Kümeleme
- Ayrı binaları (adaları) otomatik tespit eder
- `eps = 10m`: Bloklar arası minimum mesafe
- `min_samples = 5`: Bir blok için minimum entity sayısı

### Gap Healing
- `< 15cm`: Çizim hatası → Otomatik kapat
- `70-250cm`: Kapı/Pencere açıklığı → Alan hesabında kapat, duvar hesabından çıkar
- `> 250cm`: Kapat

### Oda Tipi Tespiti
Keyword-based matching:
- `SALON, ODA, YATAK` → TYPE_LIVING → Laminat + Saten Boya
- `BANYO, WC, DUS` → TYPE_WET → Seramik + Su İzolasyonu
- `MUTFAK` → TYPE_KITCHEN → Seramik
- `BALKON, TERAS` → TYPE_OUTDOOR → Granit

## 🗄️ Veritabanı Şeması

```
projects ─────< quantities
    │              │
    │              └──> ref_poses ───< ref_recipes
    │
    └──> smart_mappings
```

## 📦 Seed Data (20 Poz)

| Kategori | Poz Sayısı |
|----------|------------|
| Beton | 3 (C25, C30, C35) |
| Demir/Kalıp | 3 |
| Duvar | 3 (Tuğla, Gazbeton, Briket) |
| Sıva/Boya | 4 |
| Kaplama | 4 (Parke, Seramik, Granit) |
| Doğrama | 2 (PVC, Çelik Kapı) |
| İzolasyon | 1 |

## ⚙️ DWG Desteği

DWG dosyaları için ODA File Converter gereklidir:

1. [ODA File Converter'ı indir](https://www.opendesign.com/guestfiles/oda_file_converter)
2. Kur ve path'i `.env` dosyasına ekle:
   ```
   ODA_CONVERTER_PATH=C:/Program Files/ODA/ODAFileConverter/ODAFileConverter.exe
   ```

## 🐳 Docker (İleride)

```dockerfile
# Dockerfile örneği eklenecek
```

## 📄 Lisans

MIT License

## 👨‍💻 Geliştirici

AI Solutions Architect - 2026
