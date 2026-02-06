"""
Test DXF Generator for Construction Quantity Takeoff Engine
============================================================

Creates a sample DXF file with multiple rooms for testing purposes.
Simulates a typical Turkish apartment floor plan.

Usage:
    python create_test_dxf.py

Output:
    test_apartment.dxf - A simple apartment floor plan with labeled rooms
"""

import ezdxf
from ezdxf.enums import TextEntityAlignment


def create_test_apartment_dxf():
    """
    Create a test DXF file representing a typical Turkish apartment.
    
    Layout (in cm):
    
    +-------------------+------------------+
    |                   |                  |
    |      SALON        |   YATAK ODASI    |
    |     (5m x 4m)     |    (4m x 3.5m)   |
    |                   |                  |
    +--------+----------+--------+---------+
    |        |                   |         |
    | MUTFAK |       HOL         |  BANYO  |
    | (3x3m) |      (2x4m)       | (2x2.5m)|
    |        |                   |         |
    +--------+-------------------+---------+
             |     BALKON        |
             |    (4m x 1.5m)    |
             +-------------------+
    
    All dimensions in centimeters for realistic CAD simulation.
    """
    
    # Create new DXF document (AutoCAD 2018 format)
    doc = ezdxf.new('R2018')
    msp = doc.modelspace()
    
    # Define layers for organization
    doc.layers.new('WALLS', dxfattribs={'color': 7})  # White
    doc.layers.new('ROOM_LABELS', dxfattribs={'color': 3})  # Green
    doc.layers.new('DIMENSIONS', dxfattribs={'color': 1})  # Red
    
    # =========================================================================
    # ROOM DEFINITIONS (coordinates in cm)
    # =========================================================================
    
    rooms = [
        # (name, [(x1,y1), (x2,y2), ...], is_closed)
        {
            "name": "SALON",
            "coords": [(0, 400), (500, 400), (500, 800), (0, 800)],
            "label_pos": (250, 600),
        },
        {
            "name": "YATAK ODASI",
            "coords": [(500, 450), (900, 450), (900, 800), (500, 800)],
            "label_pos": (700, 625),
        },
        {
            "name": "MUTFAK",
            "coords": [(0, 100), (300, 100), (300, 400), (0, 400)],
            "label_pos": (150, 250),
        },
        {
            "name": "HOL",
            "coords": [(300, 100), (700, 100), (700, 400), (300, 400)],
            "label_pos": (500, 250),
        },
        {
            "name": "BANYO",
            "coords": [(700, 100), (900, 100), (900, 350), (700, 350)],
            "label_pos": (800, 225),
        },
        {
            "name": "BALKON",
            # Intentionally leave a gap (90cm door opening)
            "coords": [(300, 0), (300, 100), (700, 100), (700, 0)],
            "label_pos": (500, 50),
            "is_outdoor": True,
        },
    ]
    
    # =========================================================================
    # DRAW ROOMS
    # =========================================================================
    
    for room in rooms:
        coords = room["coords"]
        name = room["name"]
        label_pos = room["label_pos"]
        
        # Create closed polyline for room boundary
        # Close the polyline by adding the first point at the end
        polyline_coords = coords + [coords[0]]
        
        msp.add_lwpolyline(
            polyline_coords,
            dxfattribs={
                'layer': 'WALLS',
                'closed': True,
            }
        )
        
        # Add room label as TEXT entity (inside the polygon)
        msp.add_text(
            name,
            dxfattribs={
                'layer': 'ROOM_LABELS',
                'height': 30,  # 30cm text height
                'insert': label_pos,
            }
        )
    
    # =========================================================================
    # ADD DOOR OPENINGS (as gaps in walls)
    # Creating separate polylines to simulate doors
    # =========================================================================
    
    # Door from HOL to SALON (90cm opening)
    # This creates a "gap" that the healing algorithm should detect
    msp.add_line(
        (350, 400), (440, 400),  # Door opening
        dxfattribs={'layer': 'WALLS'}
    )
    
    # =========================================================================
    # ADD BLOCK IDENTIFIER (for multi-block test)
    # =========================================================================
    
    msp.add_text(
        "A BLOK",
        dxfattribs={
            'layer': 'ROOM_LABELS',
            'height': 50,
            'insert': (450, 850),
        }
    )
    
    # =========================================================================
    # SAVE FILE
    # =========================================================================
    
    output_path = "test_apartment.dxf"
    doc.saveas(output_path)
    print(f"✅ Test DXF created: {output_path}")
    print(f"   - 6 rooms defined")
    print(f"   - Coordinates in cm (default unit)")
    print(f"   - Includes room labels for automatic detection")
    
    return output_path


def create_multi_block_dxf():
    """
    Create a test DXF with multiple building blocks (islands).
    
    Simulates a "Toplu Konut" (mass housing) site plan with 2 separate blocks.
    """
    
    doc = ezdxf.new('R2018')
    msp = doc.modelspace()
    
    doc.layers.new('WALLS', dxfattribs={'color': 7})
    doc.layers.new('LABELS', dxfattribs={'color': 3})
    
    # =========================================================================
    # BLOCK A (offset: 0, 0)
    # =========================================================================
    
    block_a_rooms = [
        {
            "name": "SALON",
            "coords": [(0, 0), (400, 0), (400, 300), (0, 300)],
            "label_pos": (200, 150),
        },
        {
            "name": "YATAK ODASI",
            "coords": [(400, 0), (700, 0), (700, 300), (400, 300)],
            "label_pos": (550, 150),
        },
    ]
    
    msp.add_text("A BLOK", dxfattribs={'layer': 'LABELS', 'height': 40, 'insert': (350, 350)})
    
    for room in block_a_rooms:
        coords = room["coords"] + [room["coords"][0]]
        msp.add_lwpolyline(coords, dxfattribs={'layer': 'WALLS', 'closed': True})
        msp.add_text(room["name"], dxfattribs={'layer': 'LABELS', 'height': 25, 'insert': room["label_pos"]})
    
    # =========================================================================
    # BLOCK B (offset: 2000, 0) - 20 meters away for DBSCAN clustering
    # =========================================================================
    
    offset_x = 2000  # 20 meters in cm
    
    block_b_rooms = [
        {
            "name": "SALON",
            "coords": [(0 + offset_x, 0), (400 + offset_x, 0), (400 + offset_x, 300), (0 + offset_x, 300)],
            "label_pos": (200 + offset_x, 150),
        },
        {
            "name": "BANYO",
            "coords": [(400 + offset_x, 0), (550 + offset_x, 0), (550 + offset_x, 200), (400 + offset_x, 200)],
            "label_pos": (475 + offset_x, 100),
        },
    ]
    
    msp.add_text("B BLOK", dxfattribs={'layer': 'LABELS', 'height': 40, 'insert': (350 + offset_x, 350)})
    
    for room in block_b_rooms:
        coords = room["coords"] + [room["coords"][0]]
        msp.add_lwpolyline(coords, dxfattribs={'layer': 'WALLS', 'closed': True})
        msp.add_text(room["name"], dxfattribs={'layer': 'LABELS', 'height': 25, 'insert': room["label_pos"]})
    
    # Save
    output_path = "test_multi_block.dxf"
    doc.saveas(output_path)
    print(f"✅ Multi-block test DXF created: {output_path}")
    print(f"   - 2 blocks (A and B) separated by 20m")
    print(f"   - Should be detected as 2 clusters by DBSCAN")
    
    return output_path


if __name__ == "__main__":
    print("🔧 Creating test DXF files...\n")
    
    # Single apartment
    create_test_apartment_dxf()
    print()
    
    # Multi-block site
    create_multi_block_dxf()
    
    print("\n✅ All test files created successfully!")
    print("\nUsage:")
    print("  curl -X POST http://localhost:8000/analyze -F 'file=@test_apartment.dxf'")
