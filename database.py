"""
Database Module for Construction Quantity Takeoff Engine
=========================================================

PostgreSQL + SQLAlchemy 2.0 with JSONB optimization.
Includes complete schema and seeder for 20 Turkish construction poses.

2026 Architecture Notes:
- Async-first design with SQLAlchemy 2.0
- JSONB for flexible metadata (N8N automation ready)
- Recipe Engine for material calculation from poses
- smart_mappings table for ML-ready user correction learning

Author: AI Solutions Architect
Version: 1.0.0 (MVP)
"""

import uuid
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Any

from sqlalchemy import (
    Column, String, Text, Integer, Float, Numeric, Boolean,
    DateTime, ForeignKey, UniqueConstraint, Index, JSON,
    create_engine, text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker
)
from sqlalchemy.orm import (
    DeclarativeBase, relationship, Session, sessionmaker
)

from config import DATABASE


# =============================================================================
# BASE MODEL
# =============================================================================

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


# =============================================================================
# CORE MODELS
# =============================================================================

class Project(Base):
    """
    Projects table - Main entity for construction projects.
    
    JSONB meta_data structure (N8N ready):
    {
        "geo_location": {"sehir": "Istanbul", "ilce": "Kadikoy", "deprem_bolgesi": 1},
        "structural_params": {"yapi_sistemi": "Betonarme", "beton_sinifi": "C30", ...},
        "economic_params": {"fiyat_donemi": "2026-Q1", "para_birimi": "TRY", ...},
        "project_stats": {"blok_sayisi": 0, "toplam_insaat_alani": 0}
    }
    """
    __tablename__ = "projects"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # JSONB metadata - flexible structure for automation
    meta_data = Column(JSONB, nullable=False, default=dict)
    
    # File references
    original_filename = Column(String(255), nullable=True)
    file_hash = Column(String(64), nullable=True)  # SHA256 for deduplication
    
    # Processing status
    status = Column(String(50), default="pending")  # pending, processing, completed, failed
    error_message = Column(Text, nullable=True)
    warnings = Column(JSONB, default=list)  # List of processing warnings
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))
    processed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    quantities = relationship("Quantity", back_populates="project", cascade="all, delete-orphan")
    
    # Indexes for N8N automation queries
    __table_args__ = (
        Index('idx_project_status', 'status'),
        Index('idx_project_meta_city', text("(meta_data->'geo_location'->>'sehir')")),
        Index('idx_project_created', 'created_at'),
    )


class Quantity(Base):
    """
    Quantities table - Bill of Materials results.
    
    Stores calculated quantities for each room/area with full hierarchy:
    Project -> Block -> Floor -> Room -> Pose
    """
    __tablename__ = "quantities"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    
    # Location hierarchy
    block_name = Column(String(100), nullable=False, default="Ana Bina")  # "A Blok", "B Blok"
    floor_name = Column(String(100), nullable=False, default="Zemin Kat")  # "Zemin Kat", "1. Kat"
    room_name = Column(String(100), nullable=False)  # "Salon", "Yatak Odası"
    room_type = Column(String(50), nullable=False)  # "living", "wet", etc.
    
    # Geometry data
    area_m2 = Column(Numeric(12, 4), nullable=False)
    perimeter_m = Column(Numeric(12, 4), nullable=False)
    wall_area_m2 = Column(Numeric(12, 4), nullable=True)  # perimeter * height - openings
    opening_count = Column(Integer, default=0)  # Number of doors/windows detected
    
    # Material assignment
    pose_code = Column(String(50), ForeignKey("ref_poses.code"), nullable=False)
    pose_category = Column(String(50), nullable=False)  # "floor", "wall", "ceiling", "additional"
    quantity = Column(Numeric(12, 4), nullable=False)
    unit = Column(String(20), nullable=False)
    
    # Calculated material breakdown (from recipes)
    recipe_breakdown = Column(JSONB, default=list)  # [{material, qty, unit}, ...]
    
    # Metadata
    calculated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_manual_override = Column(Boolean, default=False)
    
    # Relationships
    project = relationship("Project", back_populates="quantities")
    pose = relationship("RefPose")
    
    __table_args__ = (
        Index('idx_qty_project', 'project_id'),
        Index('idx_qty_pose', 'pose_code'),
        Index('idx_qty_block_floor', 'block_name', 'floor_name'),
    )


class RefPose(Base):
    """
    Reference Poses table - Official ÇŞB construction codes.
    
    Contains standardized construction work items with their units.
    Seeded with 20 essential Turkish construction poses.
    """
    __tablename__ = "ref_poses"
    
    code = Column(String(50), primary_key=True)  # "04.002/1", "16.001/1"
    description = Column(String(500), nullable=False)
    description_en = Column(String(500), nullable=True)  # English translation
    
    # Classification
    category = Column(String(100), nullable=False)  # "Duvar", "Beton", "Boya", etc.
    subcategory = Column(String(100), nullable=True)
    
    # Units
    unit = Column(String(20), nullable=False)  # "m²", "m³", "kg", "adet"
    
    # Default pricing (2026-Q1, optional)
    default_unit_price = Column(JSONB, default=dict)  # {"TRY": 250.00, "USD": 7.50}
    
    # Labor hours per unit (for project planning)
    labor_hours_per_unit = Column(Numeric(8, 4), nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    recipes = relationship("RefRecipe", back_populates="pose", cascade="all, delete-orphan")


class RefRecipe(Base):
    """
    Reference Recipes table - Material breakdown for each pose.
    
    Defines how much raw material is needed per unit of work.
    Example: 1 m² Tuğla Duvar = 28 adet tuğla + 0.025 m³ harç
    """
    __tablename__ = "ref_recipes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pose_code = Column(String(50), ForeignKey("ref_poses.code", ondelete="CASCADE"), nullable=False)
    
    # Material details
    material_name = Column(String(200), nullable=False)
    material_code = Column(String(50), nullable=True)  # Optional: supplier code
    
    # Quantity per unit of pose
    quantity_per_unit = Column(Numeric(12, 6), nullable=False)
    unit = Column(String(20), nullable=False)  # Material unit
    
    # Waste factor (fire kaybı)
    waste_percentage = Column(Numeric(5, 2), default=5.0)  # Default 5%
    
    # Notes
    notes = Column(Text, nullable=True)
    
    # Relationships
    pose = relationship("RefPose", back_populates="recipes")
    
    __table_args__ = (
        Index('idx_recipe_pose', 'pose_code'),
    )


class SmartMapping(Base):
    """
    Smart Mappings table - User correction learning.
    
    Stores user overrides to improve automatic material assignment.
    When a user corrects "KORIDOR" from TYPE_LIVING to TYPE_HALLWAY,
    the system learns for future projects.
    
    ML-ready: Can be used to train a classifier.
    """
    __tablename__ = "smart_mappings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # Null = global
    
    # Mapping type
    mapping_type = Column(String(50), nullable=False)  # "layer", "text", "room_type"
    
    # Source -> Target
    source_value = Column(String(255), nullable=False)  # Original value (normalized)
    target_value = Column(String(255), nullable=False)  # Corrected value
    
    # Confidence and usage
    usage_count = Column(Integer, default=1)
    confidence_score = Column(Numeric(5, 4), default=1.0)  # 0.0 - 1.0
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        UniqueConstraint('user_id', 'mapping_type', 'source_value', name='uq_smart_mapping'),
        Index('idx_mapping_source', 'source_value'),
    )


# =============================================================================
# DATABASE ENGINE & SESSION
# =============================================================================

# Async engine for FastAPI
async_engine = create_async_engine(
    DATABASE.async_url,
    pool_size=DATABASE.pool_size,
    max_overflow=DATABASE.max_overflow,
    pool_timeout=DATABASE.pool_timeout,
    echo=False,  # Set True for SQL debugging
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Sync engine for migrations and seeding
sync_engine = create_engine(
    DATABASE.sync_url,
    pool_size=5,
    echo=False,
)

SyncSessionLocal = sessionmaker(bind=sync_engine)


async def get_db() -> AsyncSession:
    """Dependency for FastAPI endpoints."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# =============================================================================
# RECIPE ENGINE
# =============================================================================

class RecipeEngine:
    """
    Recipe calculation engine.
    
    Calculates material quantities from pose quantities using ref_recipes.
    Includes waste factor (fire kaybı) calculation.
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self._recipe_cache: dict[str, list[dict]] = {}
    
    async def get_recipes_for_pose(self, pose_code: str) -> list[dict]:
        """Fetch recipes for a pose code with caching."""
        if pose_code in self._recipe_cache:
            return self._recipe_cache[pose_code]
        
        result = await self.session.execute(
            text("""
                SELECT material_name, quantity_per_unit, unit, waste_percentage
                FROM ref_recipes
                WHERE pose_code = :pose_code
            """),
            {"pose_code": pose_code}
        )
        
        recipes = [
            {
                "material": row.material_name,
                "quantity_per_unit": float(row.quantity_per_unit),
                "unit": row.unit,
                "waste_pct": float(row.waste_percentage),
            }
            for row in result.fetchall()
        ]
        
        self._recipe_cache[pose_code] = recipes
        return recipes
    
    async def calculate_materials(
        self,
        pose_code: str,
        quantity: float,
        include_waste: bool = True
    ) -> list[dict]:
        """
        Calculate raw materials for a given pose quantity.
        
        Args:
            pose_code: Reference pose code (e.g., "04.002/1")
            quantity: Amount of work (in pose units)
            include_waste: Whether to add waste factor
            
        Returns:
            List of material breakdowns with quantities
        """
        recipes = await self.get_recipes_for_pose(pose_code)
        
        materials = []
        for recipe in recipes:
            base_qty = quantity * recipe["quantity_per_unit"]
            
            if include_waste:
                waste_multiplier = 1 + (recipe["waste_pct"] / 100)
                final_qty = base_qty * waste_multiplier
            else:
                final_qty = base_qty
            
            materials.append({
                "material": recipe["material"],
                "quantity": round(final_qty, 4),
                "unit": recipe["unit"],
                "waste_included": include_waste,
            })
        
        return materials


# =============================================================================
# DATABASE INITIALIZATION & SEEDING
# =============================================================================

def create_all_tables():
    """Create all database tables (sync, for initialization)."""
    Base.metadata.create_all(bind=sync_engine)


def drop_all_tables():
    """Drop all database tables (sync, for reset)."""
    Base.metadata.drop_all(bind=sync_engine)


def seed_reference_data():
    """
    Seed the database with 20 Turkish construction poses and their recipes.
    
    Categories:
    - Kaba İnşaat (Beton, Demir, Kalıp) - 6 poses
    - Duvar İşleri - 3 poses
    - Sıva ve Boya - 4 poses
    - Kaplama - 4 poses
    - Doğrama - 2 poses
    - İzolasyon - 1 pose (added as bonus)
    """
    session = SyncSessionLocal()
    
    try:
        # Check if already seeded
        existing = session.query(RefPose).first()
        if existing:
            print("Database already seeded. Skipping...")
            return
        
        # =================================================================
        # POSES
        # =================================================================
        poses = [
            # --- KABA İNŞAAT ---
            RefPose(
                code="16.001/1",
                description="C25 Beton Dökümü (pompalı)",
                description_en="C25 Concrete Casting (pumped)",
                category="Beton",
                subcategory="Hazır Beton",
                unit="m³",
                default_unit_price={"TRY": 3500.00},
                labor_hours_per_unit=Decimal("0.5"),
            ),
            RefPose(
                code="16.002/1",
                description="C30 Beton Dökümü (pompalı)",
                description_en="C30 Concrete Casting (pumped)",
                category="Beton",
                subcategory="Hazır Beton",
                unit="m³",
                default_unit_price={"TRY": 3800.00},
                labor_hours_per_unit=Decimal("0.5"),
            ),
            RefPose(
                code="16.003/1",
                description="C35 Beton Dökümü (pompalı)",
                description_en="C35 Concrete Casting (pumped)",
                category="Beton",
                subcategory="Hazır Beton",
                unit="m³",
                default_unit_price={"TRY": 4200.00},
                labor_hours_per_unit=Decimal("0.5"),
            ),
            RefPose(
                code="21.011/1",
                description="Nervürlü Çelik Hasır ve Donatı (Ø8-Ø32)",
                description_en="Ribbed Steel Reinforcement (Ø8-Ø32)",
                category="Demir",
                subcategory="İnşaat Demiri",
                unit="kg",
                default_unit_price={"TRY": 42.00},
                labor_hours_per_unit=Decimal("0.015"),
            ),
            RefPose(
                code="23.014/1",
                description="Plywood Kalıp (düz yüzey)",
                description_en="Plywood Formwork (flat surface)",
                category="Kalıp",
                subcategory="Ahşap Kalıp",
                unit="m²",
                default_unit_price={"TRY": 280.00},
                labor_hours_per_unit=Decimal("0.3"),
            ),
            RefPose(
                code="23.015/1",
                description="Çelik Panel Kalıp (düz yüzey)",
                description_en="Steel Panel Formwork (flat surface)",
                category="Kalıp",
                subcategory="Çelik Kalıp",
                unit="m²",
                default_unit_price={"TRY": 180.00},
                labor_hours_per_unit=Decimal("0.2"),
            ),
            
            # --- DUVAR İŞLERİ ---
            RefPose(
                code="04.002/1",
                description="Yatay Delikli Tuğla Duvar (19 cm)",
                description_en="Horizontal Hollow Brick Wall (19 cm)",
                category="Duvar",
                subcategory="Tuğla",
                unit="m²",
                default_unit_price={"TRY": 650.00},
                labor_hours_per_unit=Decimal("0.8"),
            ),
            RefPose(
                code="04.003/1",
                description="Gazbeton Blok Duvar (20 cm)",
                description_en="AAC Block Wall (20 cm)",
                category="Duvar",
                subcategory="Gazbeton",
                unit="m²",
                default_unit_price={"TRY": 480.00},
                labor_hours_per_unit=Decimal("0.5"),
            ),
            RefPose(
                code="04.007/1",
                description="Bims Briket Duvar (20 cm)",
                description_en="Pumice Block Wall (20 cm)",
                category="Duvar",
                subcategory="Briket",
                unit="m²",
                default_unit_price={"TRY": 350.00},
                labor_hours_per_unit=Decimal("0.6"),
            ),
            
            # --- SIVA VE BOYA ---
            RefPose(
                code="25.048/1",
                description="Alçı Sıva (İç Duvar/Tavan)",
                description_en="Gypsum Plaster (Interior Wall/Ceiling)",
                category="Sıva",
                subcategory="Alçı",
                unit="m²",
                default_unit_price={"TRY": 180.00},
                labor_hours_per_unit=Decimal("0.25"),
            ),
            RefPose(
                code="25.034/2",
                description="Kireç-Çimento Esaslı Dış Cephe Sıvası",
                description_en="Lime-Cement Exterior Plaster",
                category="Sıva",
                subcategory="Dış Sıva",
                unit="m²",
                default_unit_price={"TRY": 220.00},
                labor_hours_per_unit=Decimal("0.35"),
            ),
            RefPose(
                code="27.581/1",
                description="Saten Boya (İç Mekan, 2 Kat)",
                description_en="Satin Paint (Interior, 2 Coats)",
                category="Boya",
                subcategory="İç Cephe",
                unit="m²",
                default_unit_price={"TRY": 95.00},
                labor_hours_per_unit=Decimal("0.15"),
            ),
            RefPose(
                code="27.535/1",
                description="Plastik Boya (İç Mekan, 2 Kat)",
                description_en="Plastic Paint (Interior, 2 Coats)",
                category="Boya",
                subcategory="İç Cephe",
                unit="m²",
                default_unit_price={"TRY": 75.00},
                labor_hours_per_unit=Decimal("0.12"),
            ),
            
            # --- KAPLAMA İŞLERİ ---
            RefPose(
                code="26.006/1",
                description="Laminat Parke Döşeme (8 mm, AC4)",
                description_en="Laminate Flooring (8 mm, AC4)",
                category="Kaplama",
                subcategory="Parke",
                unit="m²",
                default_unit_price={"TRY": 450.00},
                labor_hours_per_unit=Decimal("0.2"),
            ),
            RefPose(
                code="26.011/1",
                description="Seramik Yer Kaplaması (30x30 cm)",
                description_en="Ceramic Floor Tile (30x30 cm)",
                category="Kaplama",
                subcategory="Seramik",
                unit="m²",
                default_unit_price={"TRY": 380.00},
                labor_hours_per_unit=Decimal("0.35"),
            ),
            RefPose(
                code="26.012/1",
                description="Seramik Duvar Kaplaması (25x40 cm)",
                description_en="Ceramic Wall Tile (25x40 cm)",
                category="Kaplama",
                subcategory="Seramik",
                unit="m²",
                default_unit_price={"TRY": 420.00},
                labor_hours_per_unit=Decimal("0.4"),
            ),
            RefPose(
                code="26.021/1",
                description="Granit Yer Kaplaması (60x60 cm)",
                description_en="Granite Floor Tile (60x60 cm)",
                category="Kaplama",
                subcategory="Doğal Taş",
                unit="m²",
                default_unit_price={"TRY": 850.00},
                labor_hours_per_unit=Decimal("0.5"),
            ),
            
            # --- DOĞRAMA ---
            RefPose(
                code="28.097/1",
                description="PVC Pencere (Isıcamlı, Beyaz)",
                description_en="PVC Window (Double Glazed, White)",
                category="Doğrama",
                subcategory="PVC",
                unit="m²",
                default_unit_price={"TRY": 3200.00},
                labor_hours_per_unit=Decimal("1.5"),
            ),
            RefPose(
                code="28.153/1",
                description="Çelik Kapı (Daire Giriş, Standart)",
                description_en="Steel Door (Apartment Entry, Standard)",
                category="Doğrama",
                subcategory="Çelik Kapı",
                unit="adet",
                default_unit_price={"TRY": 12000.00},
                labor_hours_per_unit=Decimal("2.0"),
            ),
            
            # --- İZOLASYON ---
            RefPose(
                code="18.461/1",
                description="Su Yalıtımı (Membran, 2 Kat)",
                description_en="Waterproofing (Membrane, 2 Layers)",
                category="İzolasyon",
                subcategory="Su İzolasyonu",
                unit="m²",
                default_unit_price={"TRY": 320.00},
                labor_hours_per_unit=Decimal("0.25"),
            ),
        ]
        
        session.add_all(poses)
        session.flush()  # Get IDs before adding recipes
        
        # =================================================================
        # RECIPES (Material breakdown for each pose)
        # =================================================================
        recipes = [
            # --- C25 Beton ---
            RefRecipe(pose_code="16.001/1", material_name="Çimento (CEM II)", quantity_per_unit=Decimal("300"), unit="kg", waste_percentage=Decimal("3")),
            RefRecipe(pose_code="16.001/1", material_name="Agrega (0-32 mm)", quantity_per_unit=Decimal("0.7"), unit="m³", waste_percentage=Decimal("5")),
            RefRecipe(pose_code="16.001/1", material_name="Su", quantity_per_unit=Decimal("170"), unit="lt", waste_percentage=Decimal("0")),
            RefRecipe(pose_code="16.001/1", material_name="Katkı Maddesi", quantity_per_unit=Decimal("2.5"), unit="kg", waste_percentage=Decimal("5")),
            
            # --- C30 Beton ---
            RefRecipe(pose_code="16.002/1", material_name="Çimento (CEM II)", quantity_per_unit=Decimal("350"), unit="kg", waste_percentage=Decimal("3")),
            RefRecipe(pose_code="16.002/1", material_name="Agrega (0-32 mm)", quantity_per_unit=Decimal("0.7"), unit="m³", waste_percentage=Decimal("5")),
            RefRecipe(pose_code="16.002/1", material_name="Su", quantity_per_unit=Decimal("175"), unit="lt", waste_percentage=Decimal("0")),
            RefRecipe(pose_code="16.002/1", material_name="Katkı Maddesi", quantity_per_unit=Decimal("3.0"), unit="kg", waste_percentage=Decimal("5")),
            
            # --- C35 Beton ---
            RefRecipe(pose_code="16.003/1", material_name="Çimento (CEM I)", quantity_per_unit=Decimal("400"), unit="kg", waste_percentage=Decimal("3")),
            RefRecipe(pose_code="16.003/1", material_name="Agrega (0-22 mm)", quantity_per_unit=Decimal("0.65"), unit="m³", waste_percentage=Decimal("5")),
            RefRecipe(pose_code="16.003/1", material_name="Su", quantity_per_unit=Decimal("165"), unit="lt", waste_percentage=Decimal("0")),
            RefRecipe(pose_code="16.003/1", material_name="Süper Akışkanlaştırıcı", quantity_per_unit=Decimal("4.0"), unit="kg", waste_percentage=Decimal("5")),
            
            # --- Nervürlü Çelik ---
            RefRecipe(pose_code="21.011/1", material_name="Nervürlü Demir", quantity_per_unit=Decimal("1.02"), unit="kg", waste_percentage=Decimal("3")),
            RefRecipe(pose_code="21.011/1", material_name="Bağlama Teli", quantity_per_unit=Decimal("0.015"), unit="kg", waste_percentage=Decimal("10")),
            
            # --- Plywood Kalıp ---
            RefRecipe(pose_code="23.014/1", material_name="Plywood (18 mm)", quantity_per_unit=Decimal("1.1"), unit="m²", waste_percentage=Decimal("8")),
            RefRecipe(pose_code="23.014/1", material_name="Kalıp Çivisi", quantity_per_unit=Decimal("0.5"), unit="kg", waste_percentage=Decimal("15")),
            RefRecipe(pose_code="23.014/1", material_name="Kalıp Yağı", quantity_per_unit=Decimal("0.1"), unit="lt", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="23.014/1", material_name="Kalıp Kereste", quantity_per_unit=Decimal("0.005"), unit="m³", waste_percentage=Decimal("10")),
            
            # --- Çelik Kalıp ---
            RefRecipe(pose_code="23.015/1", material_name="Çelik Kalıp Amortisman", quantity_per_unit=Decimal("0.002"), unit="ton", waste_percentage=Decimal("0")),
            RefRecipe(pose_code="23.015/1", material_name="Kalıp Yağı", quantity_per_unit=Decimal("0.05"), unit="lt", waste_percentage=Decimal("10")),
            
            # --- Tuğla Duvar ---
            RefRecipe(pose_code="04.002/1", material_name="Yatay Delikli Tuğla (19cm)", quantity_per_unit=Decimal("28"), unit="adet", waste_percentage=Decimal("5")),
            RefRecipe(pose_code="04.002/1", material_name="Harç (Hazır)", quantity_per_unit=Decimal("0.025"), unit="m³", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="04.002/1", material_name="İşçilik", quantity_per_unit=Decimal("0.8"), unit="saat", waste_percentage=Decimal("0")),
            
            # --- Gazbeton Duvar ---
            RefRecipe(pose_code="04.003/1", material_name="Gazbeton Blok (20cm)", quantity_per_unit=Decimal("6.5"), unit="adet", waste_percentage=Decimal("3")),
            RefRecipe(pose_code="04.003/1", material_name="Gazbeton Yapıştırıcısı", quantity_per_unit=Decimal("3"), unit="kg", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="04.003/1", material_name="İşçilik", quantity_per_unit=Decimal("0.5"), unit="saat", waste_percentage=Decimal("0")),
            
            # --- Briket Duvar ---
            RefRecipe(pose_code="04.007/1", material_name="Bims Briket (20cm)", quantity_per_unit=Decimal("12.5"), unit="adet", waste_percentage=Decimal("5")),
            RefRecipe(pose_code="04.007/1", material_name="Harç (Hazır)", quantity_per_unit=Decimal("0.02"), unit="m³", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="04.007/1", material_name="İşçilik", quantity_per_unit=Decimal("0.6"), unit="saat", waste_percentage=Decimal("0")),
            
            # --- Alçı Sıva ---
            RefRecipe(pose_code="25.048/1", material_name="Hazır Alçı Sıva", quantity_per_unit=Decimal("8"), unit="kg", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="25.048/1", material_name="Astar", quantity_per_unit=Decimal("0.1"), unit="kg", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="25.048/1", material_name="İşçilik", quantity_per_unit=Decimal("0.25"), unit="saat", waste_percentage=Decimal("0")),
            
            # --- Dış Sıva ---
            RefRecipe(pose_code="25.034/2", material_name="Dış Cephe Sıvası (Hazır)", quantity_per_unit=Decimal("20"), unit="kg", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="25.034/2", material_name="File Donatı", quantity_per_unit=Decimal("1.1"), unit="m²", waste_percentage=Decimal("5")),
            RefRecipe(pose_code="25.034/2", material_name="İskele Kurulum", quantity_per_unit=Decimal("0.1"), unit="m²", waste_percentage=Decimal("0")),
            
            # --- Saten Boya ---
            RefRecipe(pose_code="27.581/1", material_name="Saten Boya", quantity_per_unit=Decimal("0.15"), unit="kg", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="27.581/1", material_name="Astar", quantity_per_unit=Decimal("0.02"), unit="kg", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="27.581/1", material_name="Macun", quantity_per_unit=Decimal("0.3"), unit="kg", waste_percentage=Decimal("15")),
            RefRecipe(pose_code="27.581/1", material_name="Zımpara", quantity_per_unit=Decimal("0.05"), unit="adet", waste_percentage=Decimal("20")),
            
            # --- Plastik Boya ---
            RefRecipe(pose_code="27.535/1", material_name="Plastik Boya", quantity_per_unit=Decimal("0.18"), unit="kg", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="27.535/1", material_name="Astar", quantity_per_unit=Decimal("0.03"), unit="kg", waste_percentage=Decimal("10")),
            
            # --- Laminat Parke ---
            RefRecipe(pose_code="26.006/1", material_name="Laminat Parke (8mm AC4)", quantity_per_unit=Decimal("1.05"), unit="m²", waste_percentage=Decimal("8")),
            RefRecipe(pose_code="26.006/1", material_name="Ses Yalıtım Folyosu", quantity_per_unit=Decimal("1.05"), unit="m²", waste_percentage=Decimal("5")),
            RefRecipe(pose_code="26.006/1", material_name="Süpürgelik", quantity_per_unit=Decimal("0.4"), unit="m", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="26.006/1", material_name="Döşeme Profili", quantity_per_unit=Decimal("0.1"), unit="m", waste_percentage=Decimal("10")),
            
            # --- Seramik Yer ---
            RefRecipe(pose_code="26.011/1", material_name="Seramik (30x30 cm)", quantity_per_unit=Decimal("1.08"), unit="m²", waste_percentage=Decimal("5")),
            RefRecipe(pose_code="26.011/1", material_name="Yapıştırıcı", quantity_per_unit=Decimal("4"), unit="kg", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="26.011/1", material_name="Derz Dolgu", quantity_per_unit=Decimal("0.3"), unit="kg", waste_percentage=Decimal("15")),
            
            # --- Seramik Duvar ---
            RefRecipe(pose_code="26.012/1", material_name="Seramik (25x40 cm)", quantity_per_unit=Decimal("1.08"), unit="m²", waste_percentage=Decimal("5")),
            RefRecipe(pose_code="26.012/1", material_name="Yapıştırıcı (Flex)", quantity_per_unit=Decimal("5"), unit="kg", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="26.012/1", material_name="Derz Dolgu", quantity_per_unit=Decimal("0.25"), unit="kg", waste_percentage=Decimal("15")),
            
            # --- Granit Yer ---
            RefRecipe(pose_code="26.021/1", material_name="Granit (60x60 cm)", quantity_per_unit=Decimal("1.05"), unit="m²", waste_percentage=Decimal("3")),
            RefRecipe(pose_code="26.021/1", material_name="Yapıştırıcı (Granit)", quantity_per_unit=Decimal("5"), unit="kg", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="26.021/1", material_name="Derz Dolgu (Epoksi)", quantity_per_unit=Decimal("0.2"), unit="kg", waste_percentage=Decimal("10")),
            
            # --- PVC Pencere ---
            RefRecipe(pose_code="28.097/1", material_name="PVC Kasa Profili", quantity_per_unit=Decimal("4"), unit="m", waste_percentage=Decimal("5")),
            RefRecipe(pose_code="28.097/1", material_name="Isıcam (4+16+4)", quantity_per_unit=Decimal("1.0"), unit="m²", waste_percentage=Decimal("3")),
            RefRecipe(pose_code="28.097/1", material_name="Aksesuar Takımı", quantity_per_unit=Decimal("1"), unit="takım", waste_percentage=Decimal("2")),
            RefRecipe(pose_code="28.097/1", material_name="Köpük + Silikon", quantity_per_unit=Decimal("0.5"), unit="tüp", waste_percentage=Decimal("20")),
            
            # --- Çelik Kapı ---
            RefRecipe(pose_code="28.153/1", material_name="Çelik Kapı Kasası", quantity_per_unit=Decimal("1"), unit="adet", waste_percentage=Decimal("0")),
            RefRecipe(pose_code="28.153/1", material_name="Çelik Kapı Kanadı", quantity_per_unit=Decimal("1"), unit="adet", waste_percentage=Decimal("0")),
            RefRecipe(pose_code="28.153/1", material_name="Kilit Sistemi", quantity_per_unit=Decimal("1"), unit="takım", waste_percentage=Decimal("2")),
            RefRecipe(pose_code="28.153/1", material_name="Menteşe", quantity_per_unit=Decimal("3"), unit="adet", waste_percentage=Decimal("5")),
            RefRecipe(pose_code="28.153/1", material_name="Montaj Malzemesi", quantity_per_unit=Decimal("1"), unit="takım", waste_percentage=Decimal("10")),
            
            # --- Su Yalıtımı ---
            RefRecipe(pose_code="18.461/1", material_name="Membran (3mm)", quantity_per_unit=Decimal("2.2"), unit="m²", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="18.461/1", material_name="Bitüm Astar", quantity_per_unit=Decimal("0.3"), unit="kg", waste_percentage=Decimal("10")),
            RefRecipe(pose_code="18.461/1", material_name="Mastik", quantity_per_unit=Decimal("0.1"), unit="kg", waste_percentage=Decimal("15")),
        ]
        
        session.add_all(recipes)
        session.commit()
        
        print(f"✅ Seeded {len(poses)} poses and {len(recipes)} recipes successfully!")
        
    except Exception as e:
        session.rollback()
        print(f"❌ Seeding failed: {e}")
        raise
    finally:
        session.close()


# =============================================================================
# BULK UPSERT HELPER (For Admin Excel Import)
# =============================================================================

def bulk_upsert_poses(
    poses_data: list[dict],
    batch_size: int = 100,
    progress_callback: callable = None
) -> dict:
    """
    Bulk upsert poses from Excel import.
    
    Args:
        poses_data: List of dicts with keys: code, description, unit, category, default_unit_price
        batch_size: Commit every N rows
        progress_callback: Optional callback(current, total) for progress updates
        
    Returns:
        dict with inserted, updated, errors counts
    """
    session = SyncSessionLocal()
    
    results = {
        "inserted": 0,
        "updated": 0,
        "errors": [],
        "total": len(poses_data)
    }
    
    try:
        for idx, pose_data in enumerate(poses_data):
            try:
                code = str(pose_data.get("code", "")).strip()
                if not code:
                    results["errors"].append(f"Row {idx+1}: Empty pose code")
                    continue
                
                # Check if exists
                existing = session.query(RefPose).filter_by(code=code).first()
                
                if existing:
                    # Update existing
                    existing.description = str(pose_data.get("description", existing.description))
                    existing.unit = str(pose_data.get("unit", existing.unit))
                    existing.category = str(pose_data.get("category", existing.category))
                    
                    # Update price if provided
                    price = pose_data.get("default_unit_price")
                    if price and price > 0:
                        existing.default_unit_price = {"TRY": float(price)}
                    
                    results["updated"] += 1
                else:
                    # Insert new
                    new_pose = RefPose(
                        code=code,
                        description=str(pose_data.get("description", "Tanımsız")),
                        unit=str(pose_data.get("unit", "m²")),
                        category=str(pose_data.get("category", "Diğer")),
                        default_unit_price={"TRY": float(pose_data.get("default_unit_price", 0))} if pose_data.get("default_unit_price") else {},
                        is_active=True
                    )
                    session.add(new_pose)
                    results["inserted"] += 1
                
                # Batch commit
                if (idx + 1) % batch_size == 0:
                    session.commit()
                    if progress_callback:
                        progress_callback(idx + 1, len(poses_data))
                        
            except Exception as e:
                results["errors"].append(f"Row {idx+1}: {str(e)[:50]}")
        
        # Final commit
        session.commit()
        if progress_callback:
            progress_callback(len(poses_data), len(poses_data))
            
    except Exception as e:
        session.rollback()
        results["errors"].append(f"Database error: {str(e)}")
    finally:
        session.close()
    
    return results


def get_all_poses_for_export() -> list[dict]:
    """Export all poses for template/review."""
    session = SyncSessionLocal()
    try:
        poses = session.query(RefPose).filter_by(is_active=True).all()
        return [
            {
                "Poz No": p.code,
                "Tanım": p.description,
                "Birim": p.unit,
                "Kategori": p.category,
                "Birim Fiyat (TRY)": p.default_unit_price.get("TRY", 0) if p.default_unit_price else 0
            }
            for p in poses
        ]
    finally:
        session.close()


# =============================================================================
# MAIN INITIALIZATION
# =============================================================================

def init_database():
    """Initialize database: create tables and seed reference data."""
    print("🔧 Creating database tables...")
    create_all_tables()
    print("🌱 Seeding reference data...")
    seed_reference_data()
    print("✅ Database initialization complete!")


if __name__ == "__main__":
    # Direct execution for initialization
    init_database()
