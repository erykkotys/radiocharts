from __future__ import annotations
from radiocharts.db import init_db, upsert_issue

RMF_20260806 = [
("Męskie Granie Orkiestra 2026","Nareszcie"),("ANOTR, 54 Ultra","Talk To You"),("sanah","itepe itede"),("Martin Garrrix, Ed Sheeran","Repeat It"),("Kuba i Kuba","Stygnie lato"),("sombr","My Body Isn't Ready"),("Zalia","tylko kochaj mnie"),("HUGEL, Imael Angel, Ultra Nate","Movin' To The Sun"),("Mrozu","Nie ma miejsca jak dom"),("DJ Goja & Jason Derulo & Melody","Mi Chico"),("Wiktoria Kida, Księga Żywiołów","Co mi tam"),("Shakira, Burna Boy","Dai Dai"),("Dawid Podsiadło","na błysk"),("David Guetta, Alok, Stick Figure","Run Run River (Angels Above Me)"),("Gibbs, Igo, 4Money","Ostatni dzień lata"),("The Bausa","Magnetic"),("Jasiek Piwowarczyk","halo Houston"),("Temper City","Self Aware"),("Marissa","Odkochaj"),("Dubdogz, FEZZO, Zaark","How Does It Feel")]

ZET_20260806 = [
("Kuba i Kuba","Stygnie lato"),("ANOTR, 54 Ultra","Talk To You"),("Męskie Granie Orkiestra 2026","Nareszcie"),("Shakira, Burna Boy","Dai Dai"),("Sarsa","Czy będziemy się pamiętać ?"),("Dubdogz, Fezzo, Zaark","How Does It Feel"),("Alle Farben, Rene Miller","Body Talk"),("sombr","My Body Isn`t Ready"),("Dawid Podsiadło","Na błysk"),("The Bausa","Magnetic"),("David Guetta, Alok, Stick Figure","Run Run River (Angels Above Me)"),("Mrozu","Nie ma miejsca jak dom"),("Temper City","Self Aware"),("Marissa","Odkochaj"),("Jasiek Piwowarczyk","Halo Houston"),("Gibbs, Igo, 4Money","Ostatni dzień lata"),("Sanah","Itepe Itede"),("Martin Garrix, Ed Sheeran","Repeat It"),("Michał Szpak","Maj"),("Wiktoria Kida, Księga Żywiołów","Co mi tam")]

def seed():
    init_db()
    upsert_issue("RMF","2026-08-06","6180",20,[{"position":i,"artist":a,"title":t} for i,(a,t) in enumerate(RMF_20260806,1)],"https://www.rmf.fm/poplista.html")
    upsert_issue("ZET","2026-08-06","ZET-2026-08-06",20,[{"position":i,"artist":a,"title":t} for i,(a,t) in enumerate(ZET_20260806,1)],"manual seed from public chart")
    print("Dodano próbne notowania RMF i ZET z 2026-08-06.")

if __name__ == "__main__": seed()
