"""
Stress Test DXF Generator for Construction Quantity Takeoff Engine
===================================================================

Creates edge-case scenarios to test:
1. Gap Healing (12cm gap)
2. Door/Window Detection (90cm gap)
3. Warning System (300cm unclosed)
4. Thin Polygon Filter (25cm wall)
5. Z-Axis Flattening (Z=5000)

Usage: python create_stress_test.py
"""

import ezdxf

def create_stress_test_dxf():
    doc = ezdxf.new('R2018')
    msp = doc.modelspace()
    
    # Katmanlar
    doc.layers.new('WALLS', dxfattribs={'color': 7})
    doc.layers.new('TEXT', dxfattribs={'color': 3})
    
    print("🔥 Stres Testi Dosyası Oluşturuluyor...")

    # ---------------------------------------------------------
    # TEST 1: KÜÇÜK BOŞLUK (Gap Healing Testi)
    # ---------------------------------------------------------
    # 12cm açık bırakılmış bir kare. 
    # BEKLENEN: Sistem bunu otomatik kapatmalı ve "ODA" olarak saymalı.
    coords_gap = [(0, 0), (400, 0), (400, 400), (0, 400), (0, 12)] # 12cm açıklık
    msp.add_lwpolyline(coords_gap, dxfattribs={'layer': 'WALLS'})
    msp.add_text("TEST_GAP_12CM", dxfattribs={'height': 30, 'insert': (200, 200), 'layer': 'TEXT'})
    print("1. Tuzak: 12cm Açık Oda eklendi (Otomatik kapanmalı)")

    # ---------------------------------------------------------
    # TEST 2: KAPI BOŞLUĞU (Opening Detection Testi)
    # ---------------------------------------------------------
    # 90cm açık bırakılmış bir dikdörtgen.
    # BEKLENEN: Sistem bunu kapatmalı ama "Kapı" olarak saymalı (Duvar metrajından düşmeli).
    coords_door = [(500, 0), (900, 0), (900, 400), (500, 400), (500, 90)] # 90cm açıklık
    msp.add_lwpolyline(coords_door, dxfattribs={'layer': 'WALLS'})
    msp.add_text("TEST_DOOR_90CM", dxfattribs={'height': 30, 'insert': (700, 200), 'layer': 'TEXT'})
    print("2. Tuzak: 90cm Açık Oda eklendi (Kapı sayılmalı)")

    # ---------------------------------------------------------
    # TEST 3: KRİTİK HATA (Unclosed Polygon Testi)
    # ---------------------------------------------------------
    # 300cm (3 metre) açık bırakılmış bir alan.
    # BEKLENEN: Sistem bunu kapatmamalı ve "Warning" (Uyarı) vermeli.
    coords_fail = [(1000, 0), (1400, 0), (1400, 400), (1000, 400)] # Son kenar yok!
    msp.add_lwpolyline(coords_fail, dxfattribs={'layer': 'WALLS'})
    msp.add_text("TEST_FAIL_300CM", dxfattribs={'height': 30, 'insert': (1200, 200), 'layer': 'TEXT'})
    print("3. Tuzak: 300cm Açık Alan eklendi (Uyarı vermeli)")

    # ---------------------------------------------------------
    # TEST 4: DUVAR FİLTRESİ (Thin Polygon Testi)
    # ---------------------------------------------------------
    # 25cm kalınlığında, 5 metre uzunluğunda ince bir dikdörtgen (Perde Beton).
    # BEKLENEN: Sistem bunu "Küçük Oda" sanmamalı, tamamen yok saymalı.
    coords_wall = [(0, 600), (500, 600), (500, 625), (0, 625), (0, 600)] # 25cm kalınlık
    msp.add_lwpolyline(coords_wall, dxfattribs={'layer': 'WALLS', 'closed': True})
    # İçine yazı koymuyoruz, ama koysak da sistem almamalı.
    print("4. Tuzak: 25cm Perde Beton eklendi (Yok sayılmalı)")

    # ---------------------------------------------------------
    # TEST 5: Z-EKSENİ HATASI (Flattening Testi)
    # ---------------------------------------------------------
    # Çizgileri Z=5000 kotunda (havada) çizilmiş bir oda.
    # BEKLENEN: Sistem Z'yi sıfırlayıp bunu normal bir oda gibi hesaplamalı.
    # Polyline yerine 3D Line kullanıyoruz
    points = [(600, 600, 5000), (1000, 600, 5000), (1000, 1000, 5000), (600, 1000, 5000)]
    for i in range(len(points)):
        p1 = points[i]
        p2 = points[(i+1)%len(points)]
        msp.add_line(p1, p2, dxfattribs={'layer': 'WALLS'})
    
    msp.add_text("TEST_Z_AXIS", dxfattribs={'height': 30, 'insert': (800, 800), 'layer': 'TEXT'})
    print("5. Tuzak: Z=5000 kotunda oda eklendi (Düzeltilmeli)")

    # Dosyayı Kaydet
    filename = "stress_test_project.dxf"
    doc.saveas(filename)
    print(f"\n✅ {filename} oluşturuldu! Şimdi bunu sisteme yükle ve sonuçları izle.")

if __name__ == "__main__":
    create_stress_test_dxf()
