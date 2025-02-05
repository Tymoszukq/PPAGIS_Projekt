import arcpy
from arcpy.sa import *

# Ustawienia środowiska
arcpy.env.workspace = r"E:\3rok_zima\PPAGiS\Projekt\Arc\PPAG_Projekt\Geobaza.gdb"  # Dostosuj ścieżkę do geobazy
arcpy.env.overwriteOutput = True
arcpy.env.outputCoordinateSystem = arcpy.SpatialReference(2180)  # Układ współrzędnych: PUWG 1992

# ---------------------------
# 1. Przygotowanie danych wejściowych
# ---------------------------
# Raster nachylenia (w stopniach)
raster_nachylenia = r"Nachylenie2"  # Warstwa rasterowa nachylenia

# Wektorowy pierwszy poziom wodonośny (zawiera pole "numer")
wektor_wodonosny = r"PPW_miendz"

# Wektorowe gleby (pole "klasa")
wektor_gleb = r"gleby_klasyfikacja_zagregowane"

# Warstwa BDOT – Teren leśny i zadrzewiony
wektor_lesny = r"PTLZ"

# Warstwa BDOT – Zabudowa
wektor_zabudowy = r"PTZB"

# ---------------------------
# 2. Przygotowanie pojedynczych kryteriów
# ---------------------------

# 2.1. Reklasyfikacja nachylenia
# Przedziały:
#   0-5°   -> 1 (niskie nachylenie)
#   5-15°  -> 2 (umiarkowane)
#   15-61° -> 3 (wysokie nachylenie)
remap_nachylenia = RemapRange([[0, 5, 1],
                              [5, 15, 2],
                              [15, 61, 3]])
reclass_nachylenia = Reclassify(raster_nachylenia, "Value", remap_nachylenia)
reclass_nachylenia.save("reclass_nachylenia")

# 2.2. Analiza poziomu wodonośnego
# Konwersja wektorowego poziomu wodonośnego do rastra
raster_wodonosny = arcpy.conversion.PolygonToRaster(
    in_features=wektor_wodonosny,
    value_field="numer",
    out_rasterdataset="raster_wodonosny",
    cell_assignment="MAXIMUM_AREA",
    cellsize=5)
raster_wodonosny_obj = arcpy.Raster(raster_wodonosny)
# Jeśli wartość pola "numer" wynosi 1 lub 2 (wysoki poziom wód), to nie nadaje się pod zabudowę.
# Obszary pod zabudowę oznaczamy wartością 1 tam, gdzie poziom wód jest niski (czyli nie ma wartości 1 lub 2).
flag_pod_zabudowe = Con((raster_wodonosny_obj == 1) | (raster_wodonosny_obj == 2), 0, 1)
flag_pod_zabudowe.save("flag_pod_zabudowe")

# 2.3. Analiza gleb
# Dodanie pola numerycznego "klasa_num" do warstwy gleb:
arcpy.management.AddField(wektor_gleb, "klasa_num", "SHORT")
arcpy.management.CalculateField(
    wektor_gleb, "klasa_num",
    "1 if !klasa! == 'Gleby Wysokiej Jakosci' else 2",
    "PYTHON3")
raster_gleb = arcpy.conversion.PolygonToRaster(
    in_features=wektor_gleb,
    value_field="klasa_num",
    out_rasterdataset="raster_gleb",
    cell_assignment="MAXIMUM_AREA",
    cellsize=30)
raster_gleb_obj = arcpy.Raster(raster_gleb)
# Uzupełnienie NoData wartością 2 (gleby niechronione)
raster_gleb_filled = Con(IsNull(raster_gleb_obj), 2, raster_gleb_obj)
# Obszary rolne – gleby wysokiej jakości (wartość = 1)
flag_rolne = Con(raster_gleb_filled == 1, 1, 0)
flag_rolne.save("flag_rolne")

# 2.4. Analiza terenów leśnych
raster_lesny = arcpy.conversion.PolygonToRaster(
    in_features=wektor_lesny,
    value_field="OBJECTID",  # Zakładamy unikalność wartości
    out_rasterdataset="raster_lesny",
    cell_assignment="MAXIMUM_AREA",
    cellsize=30)
# Flagowanie obszarów leśnych: jeśli piksel nie jest NoData, przyjmujemy, że występuje las
flag_lesny = Con(IsNull(raster_lesny), 0, 1)
# Obszar leśny przyjmujemy, jeśli występuje las lub nachylenie jest wysokie (wartość 3)
flag_forest = Con((flag_lesny == 1) | (reclass_nachylenia == 3), 1, 0)
flag_forest.save("flag_forest")

# 2.5. Analiza zabudowy
raster_zabudowy = arcpy.conversion.PolygonToRaster(
    in_features=wektor_zabudowy,
    value_field="OBJECTID",
    out_rasterdataset="raster_zabudowy",
    cell_assignment="MAXIMUM_AREA",
    cellsize=30)
# Jeśli piksel zawiera dane (czyli nie jest NoData), oznaczamy go jako zabudowany
flag_zabudowane = Con(IsNull(raster_zabudowy), 0, 1)
flag_zabudowane.save("flag_zabudowane")

# ---------------------------
# 3. Łączenie wyników klasyfikacji
# ---------------------------
# Priorytety – przy nakładaniu się warunków stosujemy następującą kolejność:
# 1) Obszary zabudowane (wartość 4)
# 2) Obszary leśne (wartość 1)
# 3) Obszary rolne (wartość 2)
# 4) Obszary pod zabudowę (wartość 3)
final_classification = Con(flag_zabudowane == 1, 4,
                           Con(flag_forest == 1, 1,
                              Con(flag_rolne == 1, 2,
                                 Con(flag_pod_zabudowe == 1, 3, 0))))
final_classification.save("Final_Classification")

# ---------------------------
# 4. Dodanie atrybutów opisowych do wynikowego rastra
# ---------------------------
# Budowanie tabeli atrybutów dla rastera (OVERWRITE – zastąpienie istniejącej)
arcpy.BuildRasterAttributeTable_management("Final_Classification", "OVERWRITE")

# Dodanie pola tekstowego "Opis" do tabeli atrybutów
arcpy.AddField_management("Final_Classification", "Opis", "TEXT", field_length=100)

# Aktualizacja tabeli atrybutów – przypisanie opisu dla każdej klasy
with arcpy.da.UpdateCursor("Final_Classification", ["Value", "Opis"]) as cursor:
    for row in cursor:
        if row[0] == 1:
            row[1] = "Obszar leśny (las lub wysoka nachylenie)"
        elif row[0] == 2:
            row[1] = "Obszar rolny (gleby wysokiej jakości)"
        elif row[0] == 3:
            row[1] = "Obszary pod zabudowę (niski poziom wód)"
        elif row[0] == 4:
            row[1] = "Obszary zabudowane"
        else:
            row[1] = "Niezaklasyfikowane"
        cursor.updateRow(row)

print("Proces klasyfikacji zakończony. Wynik zapisany jako 'Final_Classification' z atrybutem 'Opis'.")
