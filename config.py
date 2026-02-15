"""
Configuration Module for Construction Quantity Takeoff Engine
==============================================================

2026 Architecture Notes:
- Environment-based configuration for cloud-native deployment
- Fallback paths for ODA File Converter (Docker/Windows/Linux)
- All geometric calculations normalized to METERS

Author: AI Solutions Architect
Version: 1.0.0 (MVP)
"""

import os
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


# =============================================================================
# ENVIRONMENT CONFIGURATION
# =============================================================================

class Environment(Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


CURRENT_ENV = Environment(os.getenv("APP_ENV", "development"))


# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================

@dataclass
class DatabaseConfig:
    """PostgreSQL connection settings with JSONB optimization."""
    host: str = os.getenv("DB_HOST", "localhost")
    port: int = int(os.getenv("DB_PORT", "5432"))
    database: str = os.getenv("DB_NAME", "construction_takeoff")
    username: str = os.getenv("DB_USER", "postgres")
    password: str = os.getenv("DB_PASSWORD", "securepassword123")
    
    # Connection pool settings for high-load scenarios
    pool_size: int = int(os.getenv("DB_POOL_SIZE", "10"))
    max_overflow: int = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    pool_timeout: int = 30
    
    @property
    def async_url(self) -> str:
        """Async PostgreSQL URL for SQLAlchemy 2.0+"""
        return f"postgresql+asyncpg://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"
    
    @property
    def sync_url(self) -> str:
        """Sync PostgreSQL URL for migrations and seeding"""
        return f"postgresql+psycopg2://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"


DATABASE = DatabaseConfig()


# =============================================================================
# ODA FILE CONVERTER CONFIGURATION
# =============================================================================

@dataclass
class ODAConverterConfig:
    """
    ODA File Converter paths with intelligent fallback.
    
    Priority:
    1. Environment variable (for custom installations)
    2. Docker/Linux standard path
    3. Windows default installation path
    """
    
    @staticmethod
    def get_converter_path() -> Optional[Path]:
        """
        Resolve ODA File Converter executable path.
        Returns None if not found (will trigger graceful degradation).
        """
        # Priority 1: Environment variable
        env_path = os.getenv("ODA_CONVERTER_PATH")
        if env_path and Path(env_path).exists():
            return Path(env_path)
        
        # Priority 2: Docker/Linux standard path
        linux_path = Path("/opt/ODAFileConverter/ODAFileConverter")
        if linux_path.exists():
            return linux_path
        
        # Priority 3: Windows default installation
        windows_paths = [
            Path("C:/Program Files/ODA/ODAFileConverter/ODAFileConverter.exe"),
            Path("C:/Program Files (x86)/ODA/ODAFileConverter/ODAFileConverter.exe"),
        ]
        for win_path in windows_paths:
            if win_path.exists():
                return win_path
        
        return None
    
    # Conversion settings
    output_version: str = "ACAD2018"  # AutoCAD 2018 DXF format
    output_format: str = "DXF"
    timeout_seconds: int = 60  # Max conversion time


ODA_CONVERTER = ODAConverterConfig()


# =============================================================================
# GEOMETRY ENGINE CONFIGURATION
# =============================================================================

@dataclass
class GeometryConfig:
    """
    Geometric processing parameters.
    
    All thresholds are in METERS after unit normalization.
    """
    
    # Unit conversion factors (to meters)
    UNIT_FACTORS: dict = field(default_factory=lambda: {
        "mm": 0.001,
        "cm": 0.01,
        "m": 1.0,
        "inch": 0.0254,
        "feet": 0.3048,
    })
    
    # Gap healing thresholds (in meters)
    GAP_HEAL_MAX: float = 0.15  # < 15cm = drawing error, heal it
    OPENING_MIN: float = 0.70   # 70cm minimum = door/window opening
    OPENING_MAX: float = 2.50   # 250cm maximum = large opening
    
    # DBSCAN clustering parameters for island detection
    # eps: Maximum distance between two samples in a cluster (meters)
    # min_samples: Minimum entities to form a cluster
    DBSCAN_EPS: float = 10.0  # 10 meters between buildings
    DBSCAN_MIN_SAMPLES: int = 2  # Lowered from 5 to support small residential blocks
    
    # Default building parameters
    DEFAULT_FLOOR_HEIGHT_M: float = 2.80  # 280cm kat yüksekliği
    DEFAULT_WALL_THICKNESS_M: float = 0.20  # 20cm duvar kalınlığı
    
    # Polygon processing
    POLYGON_SIMPLIFY_TOLERANCE: float = 0.01  # 1cm simplification
    MIN_ROOM_AREA_M2: float = 1.0  # Ignore areas < 1m²


GEOMETRY = GeometryConfig()


# =============================================================================
# ROOM TYPE CLASSIFICATION
# =============================================================================

class RoomType(Enum):
    """Room categories for material assignment."""
    TYPE_LIVING = "living"      # Salon, Yatak Odası, Çalışma
    TYPE_WET = "wet"            # Banyo, WC, Duş
    TYPE_KITCHEN = "kitchen"    # Mutfak
    TYPE_HALLWAY = "hallway"    # Antre, Hol, Koridor
    TYPE_STAIRS = "stairs"      # Merdiven (v1.2)
    TYPE_ELEVATOR = "elevator"  # Asansör, Şaft (v1.2)
    TYPE_ENTRANCE = "entrance"  # Bina Girişi (v1.2)
    TYPE_OUTDOOR = "outdoor"    # Balkon, Teras
    TYPE_STORAGE = "storage"    # Depo, Kiler
    TYPE_UNKNOWN = "unknown"    # Fallback


# Turkish character normalization map (İ->I, Ş->S, etc.)
TURKISH_CHAR_MAP = str.maketrans({
    'İ': 'I', 'ı': 'i',
    'Ğ': 'G', 'ğ': 'g',
    'Ü': 'U', 'ü': 'u',
    'Ş': 'S', 'ş': 's',
    'Ö': 'O', 'ö': 'o',
    'Ç': 'C', 'ç': 'c',
})


# Room type keyword patterns (normalized, uppercase)
# Using list of keywords instead of regex for better maintainability
ROOM_KEYWORDS: dict[RoomType, list[str]] = {
    RoomType.TYPE_LIVING: [
        "SALON", "OTURMA", "LIVING", "YATAK", "BEDROOM", "EBEVEYN",
        "COCUK", "CHILD", "MISAFIR", "GUEST", "CALISMA", "STUDY",
        "ODA", "ROOM", "SUIT", "SUITE"
    ],
    RoomType.TYPE_WET: [
        "BANYO", "BATHROOM", "WC", "TUVALET", "TOILET", "DUS", "SHOWER",
        "LAVABO", "VESTIYER", "BATH"
    ],
    RoomType.TYPE_KITCHEN: [
        "MUTFAK", "KITCHEN", "ANTRE MUTFAK", "ACIK MUTFAK"
    ],
    RoomType.TYPE_HALLWAY: [
        "ANTRE", "HOL", "HALL", "KORIDOR", "CORRIDOR",
        "VESTIBUL"
    ],
    RoomType.TYPE_STAIRS: [
        "MERDIVEN", "STAIR", "BASAMAK", "SAHANLIK"
    ],
    RoomType.TYPE_ELEVATOR: [
        "ASANSOR", "ELEVATOR", "SAFT", "SHAFT", "LIFT"
    ],
    RoomType.TYPE_ENTRANCE: [
        "BINA GIRISI", "BLOK GIRISI", "ENTRANCE", "LOBBY", "GIRIS", "ENTRY"
    ],
    RoomType.TYPE_OUTDOOR: [
        "BALKON", "BALCONY", "TERAS", "TERRACE", "VERANDA", "SUNDURMA",
        "BAHCE", "GARDEN", "DIS MEKAN"
    ],
    RoomType.TYPE_STORAGE: [
        "DEPO", "STORAGE", "KILER", "PANTRY", "GARDROP", "CLOSET",
        "DOLAP", "BODRUM", "BASEMENT", "CEKMECE"
    ],
}


# =============================================================================
# MATERIAL ASSIGNMENT DEFAULTS
# =============================================================================

@dataclass
class MaterialAssignment:
    """Default materials for a room type."""
    floor_pose: str
    wall_pose: str
    ceiling_pose: str
    additional_poses: list[str] = field(default_factory=list)


# Default materials by room type
ROOM_MATERIALS: dict[RoomType, MaterialAssignment] = {
    RoomType.TYPE_LIVING: MaterialAssignment(
        floor_pose="26.006/1",      # Laminat Parke
        wall_pose="27.581/1",       # Saten Boya
        ceiling_pose="27.535/1",    # Plastik Boya
    ),
    RoomType.TYPE_WET: MaterialAssignment(
        floor_pose="26.011/1",      # Seramik Yer
        wall_pose="26.012/1",       # Seramik Duvar
        ceiling_pose="27.535/1",    # Plastik Boya
        additional_poses=["18.461/1"],  # Su İzolasyonu
    ),
    RoomType.TYPE_KITCHEN: MaterialAssignment(
        floor_pose="26.011/1",      # Seramik Yer
        wall_pose="27.581/1",       # Saten Boya (+ tezgah üstü seramik ayrı)
        ceiling_pose="27.535/1",    # Plastik Boya
    ),
    RoomType.TYPE_HALLWAY: MaterialAssignment(
        floor_pose="26.011/1",      # Seramik Yer
        wall_pose="27.581/1",       # Saten Boya
        ceiling_pose="27.535/1",    # Plastik Boya
    ),
    RoomType.TYPE_STAIRS: MaterialAssignment(
        floor_pose="26.201",        # Mermer (Basamak)
        wall_pose="27.581/1",       # Saten Boya
        ceiling_pose="27.535/1",
        additional_poses=["23.001"] # Demir Korkuluk
    ),
    RoomType.TYPE_ELEVATOR: MaterialAssignment(
        floor_pose="",              # Boşluk
        wall_pose="27.501",         # Kara Sıva
        ceiling_pose="",
        additional_poses=[]
    ),
    RoomType.TYPE_ENTRANCE: MaterialAssignment(
        floor_pose="26.201",        # Granit/Mermer
        wall_pose="27.581/1",       # Saten Boya
        ceiling_pose="27.535/1",
        additional_poses=[]
    ),
    RoomType.TYPE_OUTDOOR: MaterialAssignment(
        floor_pose="26.021/1",      # Granit
        wall_pose="25.034/2",       # Dış Sıva
        ceiling_pose="",            # No ceiling for outdoor
    ),
    RoomType.TYPE_STORAGE: MaterialAssignment(
        floor_pose="26.011/1",      # Seramik Yer
        wall_pose="27.535/1",       # Plastik Boya
        ceiling_pose="27.535/1",    # Plastik Boya
    ),
    RoomType.TYPE_UNKNOWN: MaterialAssignment(
        floor_pose="26.006/1",      # Default: Laminat
        wall_pose="27.581/1",       # Default: Saten Boya
        ceiling_pose="27.535/1",    # Default: Plastik Boya
    ),
}


# =============================================================================
# API CONFIGURATION
# =============================================================================

@dataclass
class APIConfig:
    """FastAPI application settings."""
    title: str = "Construction Quantity Takeoff API"
    version: str = "1.2.0"
    description: str = "İnşaat Metraj ve Maliyet Otomasyonu - Türkiye Pazarı"
    
    # File upload limits
    max_upload_size_mb: int = 100
    allowed_extensions: list[str] = field(default_factory=lambda: [".dwg", ".dxf"])
    
    # CORS settings
    cors_origins: list[str] = field(default_factory=lambda: ["*"])


API = APIConfig()


# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "json": {
            "format": '{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}',
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
    "loggers": {
        "construction_engine": {
            "level": "DEBUG" if CURRENT_ENV == Environment.DEVELOPMENT else "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
    },
}
