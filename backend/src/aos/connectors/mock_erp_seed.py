"""Seed data for the mock ERP, laid out in Oracle Fusion tables (SCM and Procurement).

Everything is deterministic: the same seed builds the same rows, so tests can rely on it. The five
janitorial suppliers and their seven past orders are the fixed demo journey; everything else is
background a mall would plausibly have in its ERP.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from .base import Store

SCHEMA = """
create table if not exists AP_TERMS_TL(TERM_ID integer primary key, NAME text unique not null, DESCRIPTION text,
    LANGUAGE text not null default 'US');
create table if not exists HR_LOCATIONS_ALL(LOCATION_ID integer primary key, LOCATION_CODE text unique not null,
    DESCRIPTION text not null, ADDRESS_LINE_1 text, TOWN_OR_CITY text, COUNTRY text not null default 'SA',
    SHIP_TO_SITE_FLAG text not null default 'Y', RECEIVING_SITE_FLAG text not null default 'Y');
create table if not exists EGP_CATEGORIES_B(CATEGORY_ID integer primary key, CATEGORY_CODE text unique not null,
    CATEGORY_SET_ID integer not null, ENABLED_FLAG text not null default 'Y', START_DATE_ACTIVE text,
    END_DATE_ACTIVE text);
create table if not exists EGP_CATEGORIES_TL(CATEGORY_ID integer not null, LANGUAGE text not null default 'US',
    CATEGORY_NAME text not null, DESCRIPTION text, primary key (CATEGORY_ID, LANGUAGE));
create table if not exists EGP_SYSTEM_ITEMS_B(INVENTORY_ITEM_ID integer primary key, ORGANIZATION_ID integer not null,
    ITEM_NUMBER text unique not null, DESCRIPTION text not null, PRIMARY_UOM_CODE text not null,
    ITEM_TYPE text not null, LIST_PRICE_PER_UNIT text, INVENTORY_ITEM_STATUS_CODE text not null default 'Active',
    PURCHASING_ENABLED_FLAG text not null default 'Y');
create table if not exists EGP_ITEM_CATEGORIES(INVENTORY_ITEM_ID integer not null, ORGANIZATION_ID integer not null,
    CATEGORY_SET_ID integer not null, CATEGORY_ID integer not null, primary key (INVENTORY_ITEM_ID, CATEGORY_SET_ID));
create table if not exists HZ_PARTIES(PARTY_ID integer primary key, PARTY_NUMBER text unique not null,
    PARTY_NAME text not null, PARTY_TYPE text not null, ADDRESS1 text, CITY text, POSTAL_CODE text, COUNTRY text,
    PRIMARY_PHONE_NUMBER text, EMAIL_ADDRESS text, URL text, STATUS text not null default 'A');
create table if not exists POZ_SUPPLIERS(VENDOR_ID integer primary key, PARTY_ID integer not null,
    SEGMENT1 text unique not null, VENDOR_NAME text not null, VENDOR_TYPE_LOOKUP_CODE text,
    BUSINESS_RELATIONSHIP text not null default 'SPEND_AUTHORIZED', TAX_REGISTRATION_NUMBER text, TAXPAYER_ID text,
    ENABLED_FLAG text not null default 'Y', START_DATE_ACTIVE text, END_DATE_ACTIVE text, CREATION_DATE text);
create table if not exists POZ_SUPPLIER_SITES_ALL_M(VENDOR_SITE_ID integer primary key, VENDOR_ID integer not null,
    VENDOR_SITE_CODE text not null, PRC_BU_ID integer not null, ADDRESS_LINE1 text, CITY text, COUNTRY text,
    PHONE text, EMAIL_ADDRESS text not null, PURCHASING_SITE_FLAG text not null default 'Y',
    PAY_SITE_FLAG text not null default 'Y', RFQ_ONLY_SITE_FLAG text not null default 'N', TERMS_ID integer,
    INACTIVE_DATE text, unique (VENDOR_ID, VENDOR_SITE_CODE));
create table if not exists POZ_SUPPLIER_CONTACTS(VENDOR_CONTACT_ID integer primary key, VENDOR_ID integer not null,
    VENDOR_SITE_ID integer, FIRST_NAME text, LAST_NAME text not null, JOB_TITLE text, EMAIL_ADDRESS text,
    PHONE_NUMBER text, PRIMARY_FLAG text not null default 'N', INACTIVE_DATE text);
create table if not exists PO_APPROVED_SUPPLIER_LIST(ASL_ID integer primary key, PRC_BU_ID integer not null,
    VENDOR_ID integer not null, VENDOR_SITE_ID integer, CATEGORY_ID integer, ITEM_ID integer,
    ASL_STATUS text not null default 'Approved', DISABLE_FLAG text not null default 'N');
create table if not exists PO_HEADERS_ALL(PO_HEADER_ID integer primary key, SEGMENT1 text unique not null,
    TYPE_LOOKUP_CODE text not null, PRC_BU_ID integer not null, VENDOR_ID integer not null, VENDOR_SITE_ID integer,
    CURRENCY_CODE text not null, TERMS_ID integer, DOCUMENT_STATUS text not null, APPROVED_FLAG text,
    APPROVED_DATE text, COMMENTS text, ATTRIBUTE_CATEGORY text, ATTRIBUTE1 text unique, ATTRIBUTE2 text unique,
    CREATION_DATE text not null, START_DATE text, END_DATE text);
create table if not exists PO_LINES_ALL(PO_LINE_ID integer primary key, PO_HEADER_ID integer not null,
    LINE_NUM integer not null, LINE_TYPE text not null default 'Goods', ITEM_ID integer, ITEM_DESCRIPTION text not null,
    CATEGORY_ID integer, UOM_CODE text, QUANTITY text, UNIT_PRICE text not null, unique (PO_HEADER_ID, LINE_NUM));
create table if not exists PO_LINE_LOCATIONS_ALL(LINE_LOCATION_ID integer primary key, PO_LINE_ID integer not null,
    PO_HEADER_ID integer not null, SHIPMENT_NUM integer not null, QUANTITY text, NEED_BY_DATE text,
    SHIP_TO_LOCATION_ID integer, NOTE_TO_RECEIVER text);
create table if not exists RCV_TRANSACTIONS(TRANSACTION_ID integer primary key, TRANSACTION_TYPE text not null,
    TRANSACTION_DATE text not null, QUANTITY text, PO_HEADER_ID integer not null, PO_LINE_ID integer,
    PO_LINE_LOCATION_ID integer, VENDOR_ID integer, LOCATION_ID integer);
create index if not exists PO_HEADERS_ALL_N1 on PO_HEADERS_ALL(VENDOR_ID);
create index if not exists PO_LINES_ALL_N1 on PO_LINES_ALL(PO_HEADER_ID);
create index if not exists PO_LINE_LOCATIONS_ALL_N1 on PO_LINE_LOCATIONS_ALL(PO_HEADER_ID);
create index if not exists RCV_TRANSACTIONS_N1 on RCV_TRANSACTIONS(PO_HEADER_ID);
create index if not exists PO_ASL_N1 on PO_APPROVED_SUPPLIER_LIST(CATEGORY_ID);
"""

# Tables the earlier, flat mock ERP used. Dropped once, when the Fusion tables are first seeded.
LEGACY_TABLES = ("category", "supplier", "history", "po")

PURCHASING_CATEGORY_SET = 1
INVENTORY_ORG = 204
PRC_BU = 300000001

TERMS = [
    ("Immediate", "Payment due on receipt of invoice"),
    ("Net 15", "Payment due 15 days after invoice date"),
    ("Net 30", "Payment due 30 days after invoice date"),
    ("Net 45", "Payment due 45 days after invoice date"),
    ("Net 60", "Payment due 60 days after invoice date"),
    ("2/10 Net 30", "2% discount within 10 days, otherwise due in 30 days"),
]

LOCATIONS = [
    ("MALLA-LB", "Mall A loading bay", "Gate 4, service road", "Riyadh"),
    ("MALLA-STORE", "Mall A main store room", "Level B1, store room 12", "Riyadh"),
    ("MALLA-IT", "Mall A IT room", "Level 2, admin block, IT room", "Riyadh"),
    ("MALLA-SEC", "Mall A security control room", "Level G, security office", "Riyadh"),
    ("MALLB-LB", "Mall B loading bay", "Service gate 2", "Jeddah"),
    ("MALLC-LB", "Mall C loading bay", "Service gate 1", "Dammam"),
    ("HO-RUH", "Head office, Riyadh", "King Fahd Road, Al Olaya", "Riyadh"),
]

# (code, name, description, [(item number, description, uom, list price SAR)])
CATEGORIES: list[tuple[str, str, str, list[tuple[str, str, str, int]]]] = [
    ("CAT-JAN-EQ", "Janitorial equipment",
     "Cleaning trolleys and carts, mops, mop buckets and wringers, brooms, dustpans, wet floor signs and other "
     "custodial equipment.",
     [("JAN-1001", "Cleaning trolley, 3-shelf with bag holder", "EA", 960),
      ("JAN-1002", "Mop bucket with wringer, 25 L", "EA", 185),
      ("JAN-1003", "Flat mop kit with microfibre pads", "EA", 140),
      ("JAN-1004", "Wet floor caution sign", "EA", 45),
      ("JAN-1005", "Upright dustpan and broom set", "EA", 60),
      ("JAN-1006", "Telescopic window squeegee kit", "EA", 220),
      ("JAN-1007", "Housekeeping cart with lockable cabinet", "EA", 2350)]),
    ("CAT-FAC-SVC", "Facility services",
     "Cleaning, maintenance and soft facility management service contracts for common areas.",
     [("FAC-2001", "Day cleaning crew, common areas, monthly service", "MTH", 68000),
      ("FAC-2002", "Deep cleaning, food court, per visit", "EA", 9500),
      ("FAC-2003", "Facade and glass cleaning, rope access", "EA", 42000),
      ("FAC-2004", "Planned maintenance contract, soft services, monthly", "MTH", 55000)]),
    ("CAT-FLR-MCH", "Floor care machines",
     "Floor sweepers (ride-on and walk-behind), scrubber dryers, floor polishers, burnishers, carpet extractors "
     "and their spare parts.",
     [("FLR-3001", "Ride-on floor sweeper, battery, 1200 mm path", "EA", 98000),
      ("FLR-3002", "Walk-behind push sweeper, 700 mm", "EA", 3400),
      ("FLR-3003", "Walk-behind scrubber dryer, 50 cm", "EA", 24500),
      ("FLR-3004", "Ride-on scrubber dryer, 85 cm", "EA", 118000),
      ("FLR-3005", "High-speed burnisher, 1500 rpm", "EA", 16800),
      ("FLR-3006", "Carpet extractor, 40 L", "EA", 12900),
      ("FLR-3007", "Escalator cleaning machine", "EA", 46000),
      ("FLR-3008", "Squeegee blade set for scrubber dryer", "SET", 650),
      ("FLR-3009", "Scrubber brush, 51 cm", "EA", 780),
      ("FLR-3010", "Traction battery pack, 24 V, for sweeper", "EA", 6200)]),
    ("CAT-CLN-CHM", "Cleaning chemicals",
     "Floor cleaners, degreasers, disinfectants, glass cleaner, marble and stone care, and dilution-control "
     "chemicals.",
     [("CHM-4001", "Neutral floor cleaner, 5 L", "EA", 48),
      ("CHM-4002", "Heavy-duty kitchen degreaser, 5 L", "EA", 65),
      ("CHM-4003", "Hospital-grade disinfectant, 5 L", "EA", 92),
      ("CHM-4004", "Glass cleaner, 5 L", "EA", 39),
      ("CHM-4005", "Marble crystallizer, 5 kg", "EA", 310),
      ("CHM-4006", "Stainless steel polish, 750 ml", "EA", 34),
      ("CHM-4007", "Dilution-control dispenser station", "EA", 1450)]),
    ("CAT-WSH-HYG", "Washroom hygiene",
     "Soap, hand towel, toilet tissue and sanitiser dispensers and refills, hand dryers, air fresheners and "
     "sanitary bins.",
     [("WSH-5001", "Jumbo toilet roll, case of 12", "CS", 95),
      ("WSH-5002", "Interfold hand towels, case of 20 packs", "CS", 120),
      ("WSH-5003", "Foam hand soap refill, 1 L", "EA", 28),
      ("WSH-5004", "Touch-free soap dispenser", "EA", 210),
      ("WSH-5005", "Jet hand dryer", "EA", 3900),
      ("WSH-5006", "Automatic air freshener dispenser", "EA", 160),
      ("WSH-5007", "Sanitary bin, 23 L", "EA", 240),
      ("WSH-5008", "Baby changing station, wall-mounted", "EA", 2650)]),
    ("CAT-WST-MGT", "Waste management",
     "Waste bins, recycling stations, wheelie bins, bin liners, balers, compactors and waste collection services.",
     [("WST-6001", "Recycling station, 3-stream, stainless steel", "EA", 4800),
      ("WST-6002", "Wheelie bin, 1100 L", "EA", 1450),
      ("WST-6003", "Pedal bin, 50 L", "EA", 230),
      ("WST-6004", "Heavy-duty bin liners, roll of 50", "RL", 38),
      ("WST-6005", "Vertical cardboard baler", "EA", 62000),
      ("WST-6006", "Waste compactor rental, monthly", "MTH", 7800),
      ("WST-6007", "Waste collection, per lift", "EA", 350)]),
    ("CAT-PST-CTL", "Pest control services",
     "Integrated pest management, rodent and insect control, fumigation and bird deterrent services.",
     [("PST-7001", "Integrated pest management, food court, monthly", "MTH", 6500),
      ("PST-7002", "Fumigation, per event", "EA", 12000),
      ("PST-7003", "Bird netting installation, per m2", "M2", 85),
      ("PST-7004", "Insect light trap unit", "EA", 780)]),
    ("CAT-SEC-SVC", "Security services",
     "Manned guarding, mobile patrols, crowd management and event security staffing.",
     [("SEC-8001", "Security guard, 12-hour shift", "EA", 420),
      ("SEC-8002", "Security supervisor, monthly", "MTH", 14500),
      ("SEC-8003", "Event crowd control team, per event", "EA", 18000),
      ("SEC-8004", "K9 detection unit, per shift", "EA", 1900)]),
    ("CAT-CCTV", "Video surveillance",
     "CCTV: IP cameras, network video recorders, video management software licences, people counting, ANPR and "
     "CCTV maintenance.",
     [("CCT-9001", "4 MP dome IP camera", "EA", 1150),
      ("CCT-9002", "8 MP bullet IP camera with IR", "EA", 1980),
      ("CCT-9003", "PTZ camera, 32x zoom", "EA", 9800),
      ("CCT-9004", "Network video recorder, 64-channel", "EA", 21000),
      ("CCT-9005", "Video management software licence, per camera", "EA", 380),
      ("CCT-9006", "3D people counting sensor", "EA", 4600),
      ("CCT-9007", "ANPR camera for parking entry", "EA", 7900)]),
    ("CAT-FIRE", "Fire and life safety",
     "Fire extinguishers, fire alarm devices, sprinkler parts, emergency lighting, exit signs and fire system "
     "maintenance.",
     [("FIR-1101", "CO2 fire extinguisher, 5 kg", "EA", 420),
      ("FIR-1102", "Dry powder fire extinguisher, 6 kg", "EA", 260),
      ("FIR-1103", "Addressable smoke detector", "EA", 310),
      ("FIR-1104", "Sprinkler head, pendent, 68 C", "EA", 45),
      ("FIR-1105", "LED emergency exit sign", "EA", 290),
      ("FIR-1106", "Fire system maintenance, quarterly visit", "EA", 22000)]),
    ("CAT-HVAC", "HVAC equipment and parts",
     "Air handling unit parts, fan coil units, chiller spares, air filters, thermostats, refrigerant and HVAC "
     "maintenance.",
     [("HVC-1201", "Pleated air filter MERV 13, box of 12", "BX", 690),
      ("HVC-1202", "Bag filter F8", "EA", 210),
      ("HVC-1203", "Fan coil unit motor", "EA", 1350),
      ("HVC-1204", "BACnet smart thermostat", "EA", 980),
      ("HVC-1205", "Chiller maintenance, per visit", "EA", 16000),
      ("HVC-1206", "Refrigerant R-134a, 13.6 kg cylinder", "EA", 1250)]),
    ("CAT-ELEC", "Electrical and lighting",
     "LED lamps, downlights, panels, high-bay fittings, drivers, cables, distribution board parts and lighting "
     "controls.",
     [("ELE-1301", "LED downlight, 18 W", "EA", 95),
      ("ELE-1302", "LED panel 600x600, 40 W", "EA", 165),
      ("ELE-1303", "LED tube T8, 18 W", "EA", 22),
      ("ELE-1304", "Linear high-bay light, 150 W", "EA", 690),
      ("ELE-1305", "DALI lighting controller", "EA", 2400),
      ("ELE-1306", "Power cable 4 mm2, 100 m roll", "RL", 520),
      ("ELE-1307", "RGB facade flood light", "EA", 1850)]),
    ("CAT-PLMB", "Plumbing supplies",
     "Taps, sensor faucets, flush valves, pipes and fittings, water heaters and drainage parts.",
     [("PLM-1401", "Sensor faucet, deck-mounted", "EA", 780),
      ("PLM-1402", "Sensor flush valve for urinal", "EA", 1050),
      ("PLM-1403", "PPR pipe 25 mm, 4 m length", "EA", 18),
      ("PLM-1404", "Electric water heater, 80 L", "EA", 1200),
      ("PLM-1405", "Stainless steel floor drain", "EA", 145)]),
    ("CAT-IT-EUD", "End-user computing devices",
     "Laptops and notebooks (Apple MacBook Air, MacBook Pro, Windows laptops), desktops, Mac mini, workstations, "
     "tablets and iPads.",
     [("EUD-2001", "Apple MacBook Air 13-inch, M3, 16 GB, 512 GB", "EA", 5999),
      ("EUD-2002", "Apple MacBook Air 15-inch, M3, 16 GB, 512 GB", "EA", 6999),
      ("EUD-2003", "Apple MacBook Pro 14-inch, M4 Pro, 24 GB, 1 TB", "EA", 10499),
      ("EUD-2004", "Apple MacBook Pro 16-inch, M4 Max, 36 GB, 1 TB", "EA", 15999),
      ("EUD-2005", "Apple Mac mini, M4, 16 GB, 512 GB", "EA", 3199),
      ("EUD-2006", "Dell Latitude 5450 laptop, Core Ultra 7, 32 GB, 512 GB", "EA", 6250),
      ("EUD-2007", "Lenovo ThinkPad T14 Gen 5 laptop, 32 GB, 1 TB", "EA", 5850),
      ("EUD-2008", "HP EliteDesk 800 G9 mini desktop", "EA", 4300),
      ("EUD-2009", "Apple iPad 10.9-inch, Wi-Fi, 64 GB", "EA", 1699),
      ("EUD-2010", "Apple iPad Pro 11-inch, M4, 256 GB", "EA", 4399)]),
    ("CAT-IT-MON", "Monitors and displays",
     "Computer monitors: 24-inch and 27-inch office displays, 4K and 5K monitors, USB-C monitors and monitor arms.",
     [("MON-2101", "Dell P2425H 24-inch FHD monitor", "EA", 790),
      ("MON-2102", "Dell UltraSharp U2724D 27-inch QHD monitor", "EA", 1690),
      ("MON-2103", "LG 27UP850 27-inch 4K USB-C monitor", "EA", 1950),
      ("MON-2104", "Apple Studio Display 27-inch 5K", "EA", 6999),
      ("MON-2105", "Samsung ViewFinity S8 32-inch 4K monitor", "EA", 2300),
      ("MON-2106", "Dual monitor arm, gas spring", "EA", 420)]),
    ("CAT-IT-PER", "Computer peripherals and accessories",
     "Keyboards (Arabic and English), mice, headsets, docking stations, webcams, chargers, adapters and laptop "
     "bags.",
     [("PER-2201", "Apple Magic Keyboard, Arabic", "EA", 549),
      ("PER-2202", "Logitech MX Keys keyboard, Arabic and English", "EA", 449),
      ("PER-2203", "Logitech MX Master 3S mouse", "EA", 399),
      ("PER-2204", "Jabra Evolve2 65 wireless headset", "EA", 1150),
      ("PER-2205", "Dell WD19S USB-C docking station", "EA", 980),
      ("PER-2206", "Apple 96 W USB-C power adapter", "EA", 349),
      ("PER-2207", "Logitech Brio 4K webcam", "EA", 849),
      ("PER-2208", "Laptop backpack, 15-inch", "EA", 220),
      ("PER-2209", "USB-C to HDMI adapter", "EA", 95)]),
    ("CAT-IT-NET", "Networking equipment",
     "Network switches, Wi-Fi access points, firewalls, routers, structured cabling, patch panels, racks and fibre.",
     [("NET-2301", "48-port PoE+ access switch", "EA", 14800),
      ("NET-2302", "Wi-Fi 6E access point", "EA", 3900),
      ("NET-2303", "Next-generation firewall, mid-range", "EA", 68000),
      ("NET-2304", "Cat6A cable, 305 m box", "BX", 1150),
      ("NET-2305", "24-port Cat6A patch panel", "EA", 620),
      ("NET-2306", "SFP+ 10G transceiver", "EA", 310),
      ("NET-2307", "Server rack, 42U", "EA", 4200)]),
    ("CAT-IT-POS", "Point of sale and kiosks",
     "POS terminals, receipt printers, barcode scanners, card payment terminals, self-service kiosks and queue "
     "management.",
     [("POS-2401", "All-in-one POS terminal, 15.6-inch", "EA", 4600),
      ("POS-2402", "Thermal receipt printer", "EA", 1050),
      ("POS-2403", "2D barcode scanner", "EA", 690),
      ("POS-2404", "Contactless card payment terminal", "EA", 1900),
      ("POS-2405", "Self-service kiosk, 32-inch", "EA", 18500),
      ("POS-2406", "Queue ticket dispenser", "EA", 7200)]),
    ("CAT-IT-SIG", "Digital signage",
     "LED video walls, indoor and outdoor digital signage displays, interactive wayfinding screens, media players "
     "and signage CMS licences.",
     [("SIG-2501", "55-inch commercial display, 24/7 rated", "EA", 4950),
      ("SIG-2502", "86-inch interactive touch display", "EA", 17500),
      ("SIG-2503", "LED video wall P2.5, per m2", "M2", 9800),
      ("SIG-2504", "Interactive wayfinding totem, 49-inch", "EA", 32000),
      ("SIG-2505", "Digital signage media player", "EA", 1450),
      ("SIG-2506", "Signage CMS licence, per screen per year", "EA", 450)]),
    ("CAT-IT-PRN", "Printers and consumables",
     "Multifunction printers, laser printers, label printers, toner cartridges, printer paper and managed print.",
     [("PRN-2601", "A3 colour multifunction printer", "EA", 21000),
      ("PRN-2602", "A4 mono laser printer", "EA", 1350),
      ("PRN-2603", "High-yield black toner cartridge", "EA", 520),
      ("PRN-2604", "Desktop label printer", "EA", 890),
      ("PRN-2605", "Copy paper A4 80 gsm, box of 5 reams", "BX", 85)]),
    ("CAT-IT-MSV", "IT managed services",
     "Managed IT support, service desk, on-site engineers, network operations centre (NOC), cybersecurity "
     "monitoring (SOC), device imaging and deployment, and annual maintenance contracts for mall systems.",
     [("MSV-2701", "IT service desk L1/L2, per user per month", "EA", 95),
      ("MSV-2702", "Dedicated on-site IT engineer, monthly", "MTH", 18500),
      ("MSV-2703", "24x7 NOC monitoring, per device per month", "EA", 140),
      ("MSV-2704", "SOC managed detection and response, per endpoint per month", "EA", 38),
      ("MSV-2705", "Device imaging and deployment, per device", "EA", 180),
      ("MSV-2706", "Annual maintenance contract, mall IT systems", "YR", 240000),
      ("MSV-2707", "Managed guest Wi-Fi service, monthly", "MTH", 22000)]),
    ("CAT-IT-SW", "Software licences and subscriptions",
     "Microsoft 365, Adobe Creative Cloud, endpoint security, Apple device management (MDM), ERP user licences "
     "and SaaS subscriptions.",
     [("SWL-2801", "Microsoft 365 E3, per user per year", "EA", 1520),
      ("SWL-2802", "Adobe Creative Cloud All Apps, per user per year", "EA", 3300),
      ("SWL-2803", "Endpoint protection, per device per year", "EA", 120),
      ("SWL-2804", "Apple device management (MDM), per device per year", "EA", 160)]),
    ("CAT-IT-AV", "Audio-visual and public address",
     "PA systems, background music, ceiling speakers, amplifiers, microphones, meeting room AV and projectors.",
     [("AVS-2901", "Ceiling speaker, 6.5-inch", "EA", 260),
      ("AVS-2902", "PA amplifier, 240 W", "EA", 3100),
      ("AVS-2903", "Wireless microphone kit", "EA", 1450),
      ("AVS-2904", "Meeting room video bar", "EA", 4200),
      ("AVS-2905", "Laser projector, 6000 lumens", "EA", 19000)]),
    ("CAT-FURN", "Furniture",
     "Office chairs and desks, mall seating and benches, food court tables and chairs, lounge furniture.",
     [("FRN-3101", "Ergonomic office chair", "EA", 1350),
      ("FRN-3102", "Height-adjustable desk", "EA", 2600),
      ("FRN-3103", "Food court table, 4-seat", "EA", 980),
      ("FRN-3104", "Food court chair, stackable", "EA", 340),
      ("FRN-3105", "Mall bench, stainless steel and teak", "EA", 3800),
      ("FRN-3106", "Lounge sofa, 3-seat", "EA", 5400)]),
    ("CAT-SIGN", "Signage and printing",
     "Directory boards, static wayfinding signs, acrylic and vinyl signage, store fascia, banners and large-format "
     "printing.",
     [("SGN-3201", "Static directory totem", "EA", 7500),
      ("SGN-3202", "Acrylic sign, 60 x 40 cm", "EA", 280),
      ("SGN-3203", "Vinyl window graphics, per m2", "M2", 95),
      ("SGN-3204", "Roll-up banner with print", "EA", 260),
      ("SGN-3205", "Hanging fabric banner, 3 x 1 m", "EA", 690)]),
    ("CAT-PARK", "Parking equipment",
     "Car park barriers, ticket machines, pay stations, parking guidance sensors, wheel stops, bollards, traffic "
     "cones and EV chargers.",
     [("PRK-3301", "Automatic barrier gate", "EA", 9800),
      ("PRK-3302", "Pay-on-foot parking station", "EA", 46000),
      ("PRK-3303", "Ultrasonic parking bay sensor", "EA", 520),
      ("PRK-3304", "LED bay indicator", "EA", 210),
      ("PRK-3305", "Rubber wheel stop", "EA", 120),
      ("PRK-3306", "EV charger, 22 kW", "EA", 11500),
      ("PRK-3307", "Traffic cone, 75 cm", "EA", 45)]),
    ("CAT-LAND", "Landscaping and plants",
     "Landscaping maintenance, indoor plants, planters, irrigation parts, green walls and seasonal flowers.",
     [("LND-3401", "Indoor plant rental, per plant per month", "EA", 65),
      ("LND-3402", "Landscaping maintenance, monthly", "MTH", 24000),
      ("LND-3403", "Large fibreglass planter", "EA", 1250),
      ("LND-3404", "Drip irrigation kit", "EA", 380),
      ("LND-3405", "Artificial green wall, per m2", "M2", 520)]),
    ("CAT-DECOR", "Seasonal decor and events",
     "Ramadan, Eid, National Day and seasonal decorations, event staging and lighting, kids activities.",
     [("DEC-3501", "Ramadan lantern installation, set", "SET", 38000),
      ("DEC-3502", "National Day decor package", "EA", 65000),
      ("DEC-3503", "Event stage 8 x 4 m, rental", "EA", 14000),
      ("DEC-3504", "Giant LED arch", "EA", 9500),
      ("DEC-3505", "Kids zone inflatables, rental per day", "EA", 3200)]),
    ("CAT-UNIF", "Uniforms and PPE",
     "Staff, security and cleaner uniforms, safety shoes, gloves, hi-vis vests, hard hats and other PPE.",
     [("UNF-3601", "Cleaner uniform set", "SET", 140),
      ("UNF-3602", "Security uniform set", "SET", 380),
      ("UNF-3603", "Safety shoes S3", "PR", 260),
      ("UNF-3604", "Nitrile gloves, box of 100", "BX", 28),
      ("UNF-3605", "Hi-vis vest", "EA", 22),
      ("UNF-3606", "Hard hat", "EA", 45)]),
    ("CAT-OFF", "Office and pantry supplies",
     "Stationery, pens, files, notebooks, whiteboards, pantry and breakroom consumables, drinking water.",
     [("OFF-3701", "Lever arch file", "EA", 12),
      ("OFF-3702", "Ballpoint pens, box of 50", "BX", 45),
      ("OFF-3703", "Sticky notes, pack of 12", "PK", 18),
      ("OFF-3704", "Magnetic whiteboard, 120 x 90 cm", "EA", 390),
      ("OFF-3705", "Coffee capsules, box of 100", "BX", 210),
      ("OFF-3706", "Drinking water 330 ml, carton of 40", "CS", 22)]),
    ("CAT-ELV", "Vertical transportation services",
     "Elevator, escalator and travelator maintenance, spare parts and modernisation.",
     [("ELV-3801", "Escalator handrail replacement", "EA", 28000),
      ("ELV-3802", "Elevator comprehensive maintenance, monthly", "MTH", 9500),
      ("ELV-3803", "Escalator step, replacement", "EA", 2100)]),
    ("CAT-PWR", "Power and energy",
     "UPS systems and batteries, generator rental and maintenance, solar and smart energy meters.",
     [("PWR-3901", "Online UPS, 10 kVA", "EA", 18500),
      ("PWR-3902", "UPS battery, 12 V 9 Ah", "EA", 120),
      ("PWR-3903", "Generator rental 500 kVA, per day", "EA", 4800),
      ("PWR-3904", "Smart energy meter", "EA", 1350)]),
    ("CAT-ACC", "Access control",
     "Access control readers, turnstiles, door controllers, staff ID cards, electromagnetic locks and master key "
     "systems.",
     [("ACC-4101", "Access control card reader", "EA", 950),
      ("ACC-4102", "Tripod turnstile", "EA", 14000),
      ("ACC-4103", "Two-door access controller", "EA", 2900),
      ("ACC-4104", "MIFARE staff ID cards, pack of 100", "PK", 450),
      ("ACC-4105", "Electromagnetic door lock", "EA", 380)]),
    ("CAT-MED", "First aid and guest care",
     "First aid kits, AED defibrillators, wheelchairs and guest strollers for customer service desks.",
     [("MED-4201", "First aid kit, 50-person", "EA", 260),
      ("MED-4202", "AED defibrillator", "EA", 7800),
      ("MED-4203", "Foldable wheelchair", "EA", 950),
      ("MED-4204", "Guest stroller", "EA", 1450)]),
]

# The demo journey's suppliers: numbers, names, emails and order history are fixed.
DEMO_SUPPLIERS = [
    ("SUP-10482", "Najd Supplies", "sales@najd.example", "Riyadh", "Net 30",
     ["CAT-JAN-EQ", "CAT-CLN-CHM", "CAT-WSH-HYG"]),
    ("SUP-10217", "Al Noor Trading", "rfq@alnoor.example", "Jeddah", "Net 45", ["CAT-JAN-EQ", "CAT-UNIF"]),
    ("SUP-10355", "Desert Clean", "tenders@desertclean.example", "Riyadh", "Net 30",
     ["CAT-JAN-EQ", "CAT-FLR-MCH", "CAT-CLN-CHM"]),
    ("SUP-10790", "Gulf Janitorial", "info@gulfjanitorial.example", "Dammam", "Net 60",
     ["CAT-JAN-EQ", "CAT-WSH-HYG"]),
    ("SUP-10611", "Riyadh Facility Mart", "orders@rfm.example", "Riyadh", "Net 30",
     ["CAT-JAN-EQ", "CAT-WST-MGT", "CAT-FURN"]),
]
# (supplier, po, on_time) — past janitorial orders that drive the ranking signals.
DEMO_HISTORY = [
    ("SUP-10482", "PO-771204", 1), ("SUP-10482", "PO-772015", 1), ("SUP-10482", "PO-773301", 1),
    ("SUP-10217", "PO-772640", 1),
    ("SUP-10355", "PO-771950", 1), ("SUP-10355", "PO-773012", 0),
    ("SUP-10611", "PO-770880", 0),
]

# (name, email, city, terms, categories). Supplier numbers are assigned in order.
SUPPLIERS = [
    ("Al Faisaliah Cleaning Machines", "sales@faisaliah-machines.example", "Riyadh", "Net 30", ["CAT-FLR-MCH"]),
    ("Tanzif Floorcare Systems", "rfq@tanzif.example", "Jeddah", "Net 45", ["CAT-FLR-MCH", "CAT-CLN-CHM"]),
    ("Gulf Scrubbers Trading", "info@gulfscrubbers.example", "Dammam", "Net 30", ["CAT-FLR-MCH"]),
    ("Arabian Sweepers Co.", "tenders@arabiansweepers.example", "Riyadh", "Net 60", ["CAT-FLR-MCH", "CAT-PARK"]),
    ("Safa Chemicals Industries", "sales@safachem.example", "Dammam", "Net 30", ["CAT-CLN-CHM"]),
    ("Bright Shine Chemical Co.", "orders@brightshine.example", "Riyadh", "Net 15", ["CAT-CLN-CHM"]),
    ("Al Rawdah Hygiene Products", "rfq@rawdah-hygiene.example", "Jeddah", "Net 30",
     ["CAT-CLN-CHM", "CAT-WSH-HYG"]),
    ("Nadeef Hygiene Solutions", "sales@nadeef.example", "Riyadh", "Net 45", ["CAT-WSH-HYG"]),
    ("Hayat Washroom Systems", "info@hayat-washroom.example", "Riyadh", "Net 30", ["CAT-WSH-HYG", "CAT-PLMB"]),
    ("Al Jazeera Paper Products", "orders@jazeerapaper.example", "Dammam", "Net 60", ["CAT-WSH-HYG", "CAT-OFF"]),
    ("Green Cycle Waste Services", "contracts@greencycle.example", "Riyadh", "Net 30", ["CAT-WST-MGT"]),
    ("Riyadh Waste Solutions", "rfq@ruhwaste.example", "Riyadh", "Net 45", ["CAT-WST-MGT"]),
    ("Ecoline Recycling Equipment", "sales@ecoline.example", "Jeddah", "Net 30", ["CAT-WST-MGT"]),
    ("Saudi Pest Shield", "service@pestshield.example", "Riyadh", "Net 30", ["CAT-PST-CTL"]),
    ("Al Ameen Pest Control", "info@alameen-pest.example", "Jeddah", "Net 15", ["CAT-PST-CTL"]),
    ("Bait Pest Management", "ops@baitpest.example", "Dammam", "Net 30", ["CAT-PST-CTL", "CAT-LAND"]),
    ("Al Majal Security Services", "contracts@almajal-security.example", "Riyadh", "Net 30", ["CAT-SEC-SVC"]),
    ("Hemaya Guarding Co.", "bids@hemaya.example", "Jeddah", "Net 45", ["CAT-SEC-SVC"]),
    ("Shield Arabia Event Security", "events@shieldarabia.example", "Riyadh", "Net 30",
     ["CAT-SEC-SVC", "CAT-DECOR"]),
    ("Basar Surveillance Systems", "sales@basar.example", "Riyadh", "Net 45", ["CAT-CCTV", "CAT-ACC"]),
    ("Smart Vision Security Technologies", "rfq@smartvision.example", "Jeddah", "Net 30", ["CAT-CCTV"]),
    ("Hikma Systems Integration", "presales@hikma-si.example", "Riyadh", "Net 45",
     ["CAT-CCTV", "CAT-ACC", "CAT-IT-NET"]),
    ("Al Harbi Fire Protection", "sales@alharbi-fire.example", "Riyadh", "Net 30", ["CAT-FIRE"]),
    ("Safety First Fire Systems", "info@safetyfirst.example", "Dammam", "Net 45", ["CAT-FIRE", "CAT-MED"]),
    ("Rescue Fire and Safety Trading", "orders@rescuefire.example", "Jeddah", "Net 30", ["CAT-FIRE", "CAT-UNIF"]),
    ("Cool Zone HVAC Services", "service@coolzone.example", "Riyadh", "Net 30", ["CAT-HVAC"]),
    ("Arabian Chillers Maintenance", "contracts@arabianchillers.example", "Dammam", "Net 45", ["CAT-HVAC"]),
    ("Filtra Air Filters Trading", "sales@filtra.example", "Riyadh", "Net 30", ["CAT-HVAC"]),
    ("Noor Lighting Solutions", "sales@noorlighting.example", "Riyadh", "Net 30", ["CAT-ELEC"]),
    ("Al Waha Electrical Supplies", "rfq@alwaha-electric.example", "Jeddah", "Net 45", ["CAT-ELEC", "CAT-PWR"]),
    ("Lumina Arabia", "projects@lumina-arabia.example", "Riyadh", "Net 30", ["CAT-ELEC", "CAT-DECOR"]),
    ("Al Masar Plumbing Supplies", "sales@almasar.example", "Riyadh", "Net 30", ["CAT-PLMB"]),
    ("Aqua Flow Trading", "info@aquaflow.example", "Dammam", "Net 30", ["CAT-PLMB"]),
    ("Rawabi Digital Services", "rfq@rawabi-digital.example", "Riyadh", "Net 45",
     ["CAT-IT-MSV", "CAT-IT-EUD", "CAT-IT-MON", "CAT-IT-PER", "CAT-IT-NET", "CAT-IT-SW"]),
    ("Tech Valley Computers", "b2b@techvalley.example", "Riyadh", "Net 30",
     ["CAT-IT-EUD", "CAT-IT-MON", "CAT-IT-PER"]),
    ("iStore Arabia Business", "business@istore-arabia.example", "Jeddah", "Net 30",
     ["CAT-IT-EUD", "CAT-IT-MON", "CAT-IT-PER"]),
    ("Elite IT Trading", "sales@eliteit.example", "Riyadh", "Net 45", ["CAT-IT-EUD", "CAT-IT-MON"]),
    ("Bayan Computer Systems", "rfq@bayan-cs.example", "Dammam", "Net 30",
     ["CAT-IT-EUD", "CAT-IT-PER", "CAT-IT-PRN"]),
    ("Display Hub Trading", "sales@displayhub.example", "Riyadh", "Net 30", ["CAT-IT-MON", "CAT-IT-SIG"]),
    ("Keyline Accessories", "orders@keyline.example", "Jeddah", "Net 15", ["CAT-IT-PER"]),
    ("NetCore Arabia", "presales@netcore.example", "Riyadh", "Net 45", ["CAT-IT-NET"]),
    ("Fibernet Solutions", "projects@fibernet.example", "Dammam", "Net 30", ["CAT-IT-NET"]),
    ("Retail Systems Arabia", "sales@retailsystems.example", "Riyadh", "Net 30", ["CAT-IT-POS"]),
    ("PayPoint Technologies", "merchants@paypoint.example", "Riyadh", "Net 30", ["CAT-IT-POS"]),
    ("Kiosk Pro Middle East", "sales@kioskpro.example", "Jeddah", "Net 45", ["CAT-IT-POS", "CAT-IT-SIG"]),
    ("Lumen Digital Signage", "projects@lumen-signage.example", "Riyadh", "Net 45", ["CAT-IT-SIG", "CAT-IT-AV"]),
    ("Wayfinder Media Tech", "sales@wayfinder.example", "Riyadh", "Net 30", ["CAT-IT-SIG", "CAT-SIGN"]),
    ("Print Pro Office Systems", "sales@printpro.example", "Riyadh", "Net 30", ["CAT-IT-PRN"]),
    ("Al Qalam Office Equipment", "orders@alqalam.example", "Jeddah", "Net 30", ["CAT-IT-PRN", "CAT-OFF"]),
    ("Sahab Cloud and Managed Services", "sales@sahab-cloud.example", "Riyadh", "Net 45",
     ["CAT-IT-MSV", "CAT-IT-SW"]),
    ("CyberNest Security Operations", "soc@cybernest.example", "Riyadh", "Net 30", ["CAT-IT-MSV"]),
    ("Tamkeen IT Outsourcing", "bids@tamkeen-it.example", "Dammam", "Net 60", ["CAT-IT-MSV"]),
    ("LicenseHub Arabia", "renewals@licensehub.example", "Riyadh", "Net 30", ["CAT-IT-SW"]),
    ("SoundWave AV Integration", "projects@soundwave.example", "Riyadh", "Net 45", ["CAT-IT-AV"]),
    ("Majlis Audio Visual", "sales@majlis-av.example", "Jeddah", "Net 30", ["CAT-IT-AV", "CAT-DECOR"]),
    ("Diwan Office Furniture", "sales@diwan-furniture.example", "Riyadh", "Net 30", ["CAT-FURN"]),
    ("Mall Seating Co.", "projects@mallseating.example", "Jeddah", "Net 45", ["CAT-FURN"]),
    ("Teak and Steel Outdoor", "orders@teaksteel.example", "Dammam", "Net 30", ["CAT-FURN", "CAT-LAND"]),
    ("Graphica Signs", "studio@graphica.example", "Riyadh", "Net 15", ["CAT-SIGN"]),
    ("Sign Masters Riyadh", "sales@signmasters.example", "Riyadh", "Net 30", ["CAT-SIGN"]),
    ("ParkTech Arabia", "sales@parktech.example", "Riyadh", "Net 45", ["CAT-PARK"]),
    ("Barrier Systems Trading", "info@barriersystems.example", "Jeddah", "Net 30", ["CAT-PARK", "CAT-ACC"]),
    ("Volt EV Charging", "b2b@volt-ev.example", "Riyadh", "Net 30", ["CAT-PARK", "CAT-PWR"]),
    ("Green Oasis Landscaping", "contracts@greenoasis.example", "Riyadh", "Net 30", ["CAT-LAND"]),
    ("Bloom Interior Plants", "hello@bloomplants.example", "Jeddah", "Net 15", ["CAT-LAND"]),
    ("Festive Arabia Events", "events@festivearabia.example", "Riyadh", "Net 30", ["CAT-DECOR"]),
    ("Fanoos Decor Studio", "studio@fanoos.example", "Jeddah", "Net 30", ["CAT-DECOR"]),
    ("Stagecraft Event Rentals", "rentals@stagecraft.example", "Riyadh", "Immediate", ["CAT-DECOR", "CAT-IT-AV"]),
    ("Uniform House Trading", "sales@uniformhouse.example", "Riyadh", "Net 30", ["CAT-UNIF"]),
    ("Al Sharq Safety and PPE", "orders@alsharq-ppe.example", "Dammam", "Net 30", ["CAT-UNIF"]),
    ("Office Mart Supplies", "orders@officemart.example", "Riyadh", "2/10 Net 30", ["CAT-OFF"]),
    ("Pantry Plus Trading", "sales@pantryplus.example", "Riyadh", "Net 15", ["CAT-OFF"]),
    ("Elevate Lifts and Escalators", "service@elevate-lifts.example", "Riyadh", "Net 45", ["CAT-ELV"]),
    ("Arabian Vertical Transport Services", "contracts@avts.example", "Jeddah", "Net 30", ["CAT-ELV"]),
    ("PowerGuard UPS Systems", "sales@powerguard.example", "Riyadh", "Net 30", ["CAT-PWR"]),
    ("Al Taqa Generators Rental", "rentals@altaqa.example", "Dammam", "Immediate", ["CAT-PWR"]),
    ("SecureGate Access Systems", "sales@securegate.example", "Riyadh", "Net 30", ["CAT-ACC"]),
    ("Medline Gulf First Aid", "orders@medlinegulf.example", "Riyadh", "Net 30", ["CAT-MED"]),
    ("Care Point Medical Supplies", "sales@carepoint.example", "Jeddah", "Net 30", ["CAT-MED"]),
    ("Khidmat Facility Management", "tenders@khidmat-fm.example", "Riyadh", "Net 45", ["CAT-FAC-SVC"]),
    ("Arkan Integrated FM", "bids@arkan-fm.example", "Jeddah", "Net 60", ["CAT-FAC-SVC", "CAT-PST-CTL"]),
    ("Tadbeer Soft Services", "contracts@tadbeer.example", "Riyadh", "Net 30", ["CAT-FAC-SVC"]),
]
# Suspended in the ERP: on the approved list but never offered to buyers.
INACTIVE_SUPPLIERS = [
    ("Old Town Computers", "sales@oldtown-computers.example", "Riyadh", "Net 30", ["CAT-IT-EUD", "CAT-IT-MON"]),
]

RAWABI = "Rawabi Digital Services"
# The IT service vendor carries full master data: several sites, named contacts and a blanket agreement.
RAWABI_SITES = [
    ("RUH-HQ", "King Fahd Road, Al Olaya, Riyadh 12214", "Riyadh", "+966 11 460 2200", "rfq@rawabi-digital.example"),
    ("JED-BR", "Prince Sultan Road, Al Zahra, Jeddah 23425", "Jeddah", "+966 12 610 4400",
     "jeddah@rawabi-digital.example"),
    ("DMM-BR", "King Saud Street, Al Adamah, Dammam 32241", "Dammam", "+966 13 805 3300",
     "eastern@rawabi-digital.example"),
]
RAWABI_CONTACTS = [
    ("Tariq", "Al-Shehri", "Key Account Manager", "tariq.alshehri@rawabi-digital.example", "+966 55 310 4471", "Y"),
    ("Lina", "Haddad", "Service Desk Manager", "servicedesk@rawabi-digital.example", "+966 11 460 2299", "N"),
    ("Omar", "Siddiqui", "Pre-sales Solutions Architect", "omar.siddiqui@rawabi-digital.example",
     "+966 54 772 1930", "N"),
    ("Mariam", "Al-Qahtani", "Accounts Receivable", "ar@rawabi-digital.example", "+966 11 460 2210", "N"),
]
# (agreement number, start, end, [(item number, agreed unit price SAR)])
RAWABI_AGREEMENT = ("BPA-2025-0014", "2025-01-01", "2026-12-31", [
    ("EUD-2001", 5650), ("EUD-2003", 9890), ("MON-2102", 1590), ("PER-2202", 410),
    ("MSV-2701", 89), ("MSV-2702", 17600), ("MSV-2705", 165),
])

FIRST_NAMES = ["Abdullah", "Mohammed", "Fahad", "Sultan", "Turki", "Nasser", "Hassan", "Yousef", "Majed", "Waleed",
               "Sara", "Reem", "Hind", "Lama", "Dana", "Rania", "Amal", "Imran", "Rajesh", "Anil", "George", "Ahmed"]
LAST_NAMES = ["Al-Otaibi", "Al-Ghamdi", "Al-Zahrani", "Al-Mutairi", "Al-Dossary", "Al-Harbi", "Al-Subaie",
              "Al-Anazi", "Haddad", "Khan", "Nair", "Menon", "Fernandes", "Saleh", "Al-Juhani", "Al-Rashidi"]
STREETS = {
    "Riyadh": ["King Abdulaziz Road, Al Wurud", "Al Imam Saud Road, Al Taawun", "Second Industrial City",
               "Prince Turki Road, Al Malqa", "Olaya Street, Al Sulimaniyah"],
    "Jeddah": ["Al Madinah Road, Al Rawdah", "Industrial Area, Phase 4", "Tahlia Street, Al Andalus"],
    "Dammam": ["King Saud Street, Al Adamah", "Second Industrial City", "Prince Mohammed Street, Al Faisaliyah"],
}
CITY_CODES = {"Riyadh": "RUH", "Jeddah": "JED", "Dammam": "DMM"}
CITY_DIAL = {"Riyadh": "11", "Jeddah": "12", "Dammam": "13"}

HISTORY_START = date(2024, 1, 8)
HISTORY_END = date(2026, 9, 30)
OPEN_AFTER = date(2026, 8, 20)
FIRST_HISTORY_PO = 740001
FIRST_SUPPLIER_NUMBER = 11003
SUPPLIER_NUMBER_STEP = 17


def _supplier_numbers() -> list[str]:
    return [f"SUP-{FIRST_SUPPLIER_NUMBER + SUPPLIER_NUMBER_STEP * i}"
            for i in range(len(SUPPLIERS) + len(INACTIVE_SUPPLIERS))]


def _vat(n: int) -> str:
    return f"3{(100000000000 + n * 7919) % 10**13:013d}3"


def seed(store: Store) -> None:
    """Fill the Fusion tables once. A database that already has categories is left alone."""
    if store.one("select 1 as x from EGP_CATEGORIES_B limit 1"):
        return
    rng = random.Random(20251027)
    store.x("begin")
    try:
        _drop_legacy(store)
        terms = {name: store.x("insert into AP_TERMS_TL(NAME, DESCRIPTION) values (?, ?)", (name, desc))
                 for name, desc in TERMS}
        for code, desc, line1, city in LOCATIONS:
            store.x("insert into HR_LOCATIONS_ALL(LOCATION_CODE, DESCRIPTION, ADDRESS_LINE_1, TOWN_OR_CITY)"
                    " values (?, ?, ?, ?)", (code, desc, line1, city))
        categories, items = _seed_catalogue(store)
        vendors = _seed_suppliers(store, rng, terms, categories)
        _seed_demo_history(store, vendors, categories, items)
        _seed_background_history(store, rng, vendors, categories, items)
        _seed_rawabi_agreement(store, vendors, items, terms)
        store.x("commit")
    except BaseException:
        store.x("rollback")
        raise


def _drop_legacy(store: Store) -> None:
    for table in LEGACY_TABLES:
        exists = store.one("select 1 as x from sqlite_master where type = 'table' and name = ?", (table,))
        if not exists:
            continue
        if table == "po" and store.one("select 1 as x from po limit 1"):
            continue  # keep purchase orders an older build created
        store.x(f"drop table {table}")


def _seed_catalogue(store: Store) -> tuple[dict[str, int], dict[str, dict]]:
    categories: dict[str, int] = {}
    items: dict[str, dict] = {}
    for code, name, description, cat_items in CATEGORIES:
        cid = store.x("insert into EGP_CATEGORIES_B(CATEGORY_CODE, CATEGORY_SET_ID, START_DATE_ACTIVE)"
                      " values (?, ?, '2020-01-01')", (code, PURCHASING_CATEGORY_SET))
        store.x("insert into EGP_CATEGORIES_TL(CATEGORY_ID, CATEGORY_NAME, DESCRIPTION) values (?, ?, ?)",
                (cid, name, description))
        categories[code] = cid
        for number, desc, uom, price in cat_items:
            item_type = "Service" if uom in ("MTH", "YR") or "service" in desc.lower() else "Goods"
            iid = store.x("insert into EGP_SYSTEM_ITEMS_B(ORGANIZATION_ID, ITEM_NUMBER, DESCRIPTION,"
                          " PRIMARY_UOM_CODE, ITEM_TYPE, LIST_PRICE_PER_UNIT) values (?, ?, ?, ?, ?, ?)",
                          (INVENTORY_ORG, number, desc, uom, item_type, str(price)))
            store.x("insert into EGP_ITEM_CATEGORIES values (?, ?, ?, ?)",
                    (iid, INVENTORY_ORG, PURCHASING_CATEGORY_SET, cid))
            items[number] = {"id": iid, "description": desc, "uom": uom, "price": price, "category": code}
    return categories, items


def _seed_suppliers(store: Store, rng: random.Random, terms: dict[str, int],
                    categories: dict[str, int]) -> dict[str, dict]:
    rows = [(*s, True) for s in DEMO_SUPPLIERS]
    numbers = _supplier_numbers()
    for i, (name, email, city, term, cats) in enumerate(SUPPLIERS + INACTIVE_SUPPLIERS):
        rows.append((numbers[i], name, email, city, term, cats, i < len(SUPPLIERS)))
    vendors: dict[str, dict] = {}
    for n, (number, name, email, city, term, cats, active) in enumerate(rows):
        domain = email.split("@", 1)[1]
        street = STREETS[city][n % len(STREETS[city])]
        phone = f"+966 {CITY_DIAL[city]} {400 + n * 7 % 500:03d} {1000 + n * 37 % 9000:04d}"
        party = store.x("insert into HZ_PARTIES(PARTY_NUMBER, PARTY_NAME, PARTY_TYPE, ADDRESS1, CITY, COUNTRY,"
                        " PRIMARY_PHONE_NUMBER, EMAIL_ADDRESS, URL) values (?, ?, 'ORGANIZATION', ?, ?, 'SA', ?, ?, ?)",
                        (f"HZ-{50001 + n}", name, street, city, phone, email, f"https://www.{domain}"))
        vid = store.x("insert into POZ_SUPPLIERS(PARTY_ID, SEGMENT1, VENDOR_NAME, VENDOR_TYPE_LOOKUP_CODE,"
                      " TAX_REGISTRATION_NUMBER, TAXPAYER_ID, ENABLED_FLAG, START_DATE_ACTIVE, END_DATE_ACTIVE,"
                      " CREATION_DATE) values (?, ?, ?, 'VENDOR', ?, ?, ?, ?, ?, ?)",
                      (party, number, name, _vat(n), f"{1010000000 + n * 104729 % 89999999}",
                       "Y" if active else "N", "2019-06-01", None if active else "2025-12-31",
                       "2019-06-01T08:00:00"))
        sites = RAWABI_SITES if name == RAWABI else [
            (f"{CITY_CODES[city]}-MAIN", f"{street}, {city}", city, phone, email)]
        site_ids = []
        for code, line1, site_city, site_phone, site_email in sites:
            site_ids.append(store.x(
                "insert into POZ_SUPPLIER_SITES_ALL_M(VENDOR_ID, VENDOR_SITE_CODE, PRC_BU_ID, ADDRESS_LINE1, CITY,"
                " COUNTRY, PHONE, EMAIL_ADDRESS, TERMS_ID, INACTIVE_DATE) values (?, ?, ?, ?, ?, 'SA', ?, ?, ?, ?)",
                (vid, code, PRC_BU, line1, site_city, site_phone, site_email, terms[term],
                 None if active else "2025-12-31")))
        contacts = RAWABI_CONTACTS if name == RAWABI else _contacts(rng, domain, n)
        for first, last, title, c_email, c_phone, primary in contacts:
            store.x("insert into POZ_SUPPLIER_CONTACTS(VENDOR_ID, VENDOR_SITE_ID, FIRST_NAME, LAST_NAME, JOB_TITLE,"
                    " EMAIL_ADDRESS, PHONE_NUMBER, PRIMARY_FLAG) values (?, ?, ?, ?, ?, ?, ?, ?)",
                    (vid, site_ids[0], first, last, title, c_email, c_phone, primary))
        for code in cats:
            store.x("insert into PO_APPROVED_SUPPLIER_LIST(PRC_BU_ID, VENDOR_ID, VENDOR_SITE_ID, CATEGORY_ID)"
                    " values (?, ?, ?, ?)", (PRC_BU, vid, site_ids[0], categories[code]))
        vendors[number] = {"id": vid, "site": site_ids[0], "terms": terms[term], "categories": cats,
                           "name": name, "active": active}
    return vendors


def _contacts(rng: random.Random, domain: str, n: int) -> list[tuple]:
    first = FIRST_NAMES[(n * 5) % len(FIRST_NAMES)]
    last = LAST_NAMES[(n * 3) % len(LAST_NAMES)]
    ar_first = FIRST_NAMES[(n * 7 + 3) % len(FIRST_NAMES)]
    ar_last = LAST_NAMES[(n * 11 + 1) % len(LAST_NAMES)]
    title = rng.choice(["Sales Manager", "Key Account Manager", "Tender Coordinator", "Business Development Manager"])
    handle = f"{first}.{last.replace('Al-', 'al')}".lower()
    return [
        (first, last, title, f"{handle}@{domain}", f"+966 5{n % 10} {100 + n * 13 % 900:03d} {n * 71 % 10000:04d}",
         "Y"),
        (ar_first, ar_last, "Accounts Receivable", f"accounts@{domain}",
         f"+966 5{(n + 4) % 10} {100 + n * 17 % 900:03d} {n * 53 % 10000:04d}", "N"),
    ]


def _insert_po(store: Store, *, number: str, vendor: dict, ordered: date, need_by: date,
               received: date | None, lines: list[tuple[dict | None, str, str, str, str | None]],
               location_id: int, comments: str | None = None) -> int:
    status = "CLOSED" if received else "OPEN"
    hid = store.x("insert into PO_HEADERS_ALL(SEGMENT1, TYPE_LOOKUP_CODE, PRC_BU_ID, VENDOR_ID, VENDOR_SITE_ID,"
                  " CURRENCY_CODE, TERMS_ID, DOCUMENT_STATUS, APPROVED_FLAG, APPROVED_DATE, COMMENTS, CREATION_DATE)"
                  " values (?, 'STANDARD', ?, ?, ?, 'SAR', ?, ?, 'Y', ?, ?, ?)",
                  (number, PRC_BU, vendor["id"], vendor["site"], vendor["terms"], status,
                   f"{ordered.isoformat()}T11:00:00", comments, f"{ordered.isoformat()}T09:00:00"))
    for num, (item, desc, qty, price, category) in enumerate(lines, start=1):
        lid = store.x("insert into PO_LINES_ALL(PO_HEADER_ID, LINE_NUM, LINE_TYPE, ITEM_ID, ITEM_DESCRIPTION,"
                      " CATEGORY_ID, UOM_CODE, QUANTITY, UNIT_PRICE) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (hid, num, "Goods", item["id"] if item else None, desc, category,
                       item["uom"] if item else "EA", qty, price))
        loc = store.x("insert into PO_LINE_LOCATIONS_ALL(PO_LINE_ID, PO_HEADER_ID, SHIPMENT_NUM, QUANTITY,"
                      " NEED_BY_DATE, SHIP_TO_LOCATION_ID) values (?, ?, 1, ?, ?, ?)",
                      (lid, hid, qty, need_by.isoformat(), location_id))
        if received:
            store.x("insert into RCV_TRANSACTIONS(TRANSACTION_TYPE, TRANSACTION_DATE, QUANTITY, PO_HEADER_ID,"
                    " PO_LINE_ID, PO_LINE_LOCATION_ID, VENDOR_ID, LOCATION_ID) values ('RECEIVE', ?, ?, ?, ?, ?, ?, ?)",
                    (f"{received.isoformat()}T10:30:00", qty, hid, lid, loc, vendor["id"], location_id))
    return hid


def _seed_demo_history(store: Store, vendors: dict[str, dict], categories: dict[str, int],
                       items: dict[str, dict]) -> None:
    trolley = items["JAN-1001"]
    bucket = items["JAN-1002"]
    bay = store.one("select LOCATION_ID from HR_LOCATIONS_ALL where LOCATION_CODE = 'MALLA-LB'")["LOCATION_ID"]
    for i, (supplier, po, on_time) in enumerate(DEMO_HISTORY):
        ordered = date(2025, (i % 9) + 1, 15)
        need_by = ordered + timedelta(days=21)
        received = need_by - timedelta(days=2) if on_time else need_by + timedelta(days=5)
        lines = [(trolley, trolley["description"], str(10 + 5 * i), str(940 - 10 * i), categories["CAT-JAN-EQ"]),
                 (bucket, bucket["description"], str(20 + 4 * i), "180", categories["CAT-JAN-EQ"])]
        _insert_po(store, number=po, vendor=vendors[supplier], ordered=ordered, need_by=need_by, received=received,
                   lines=lines, location_id=bay)


def _seed_background_history(store: Store, rng: random.Random, vendors: dict[str, dict],
                             categories: dict[str, int], items: dict[str, dict]) -> None:
    demo = {s[0] for s in DEMO_SUPPLIERS}
    by_category: dict[str, list[dict]] = {}
    for item in items.values():
        by_category.setdefault(item["category"], []).append(item)
    locations = [r["LOCATION_ID"] for r in store.q("select LOCATION_ID from HR_LOCATIONS_ALL order by LOCATION_ID")]
    span = (HISTORY_END - HISTORY_START).days
    planned = []
    for number, vendor in vendors.items():
        if number in demo:
            continue  # the demo suppliers' history is fixed above
        count = 9 if vendor["name"] == RAWABI else rng.randint(0, 8)
        reliability = 0.95 if vendor["name"] == RAWABI else rng.choice([0.55, 0.7, 0.8, 0.9, 0.95, 1.0])
        if not vendor["active"]:
            count = min(count, 3)
        for _ in range(count):
            planned.append((HISTORY_START + timedelta(days=rng.randrange(span)), number, reliability))
    planned.sort()
    for seq, (ordered, number, reliability) in enumerate(planned):
        vendor = vendors[number]
        need_by = ordered + timedelta(days=rng.randint(10, 45))
        received = None
        if ordered < OPEN_AFTER:
            on_time = rng.random() < reliability
            received = (max(ordered + timedelta(days=1), need_by - timedelta(days=rng.randint(0, 5))) if on_time
                        else need_by + timedelta(days=rng.randint(1, 20)))
        lines = []
        for _ in range(rng.randint(1, 3)):
            item = rng.choice(by_category[rng.choice(vendor["categories"])])
            qty = _quantity(rng, item["price"])
            price = max(1, round(item["price"] * rng.uniform(0.88, 1.04)))
            lines.append((item, item["description"], str(qty), str(price), categories[item["category"]]))
        _insert_po(store, number=f"PO-{FIRST_HISTORY_PO + seq}", vendor=vendor, ordered=ordered, need_by=need_by,
                   received=received, lines=lines, location_id=rng.choice(locations))


def _quantity(rng: random.Random, price: int) -> int:
    if price > 50000:
        return 1
    if price > 10000:
        return rng.choice([1, 1, 2])
    if price > 2000:
        return rng.choice([1, 2, 4, 6, 10])
    if price > 300:
        return rng.choice([5, 10, 20, 40])
    return rng.choice([20, 50, 100, 200])


def _seed_rawabi_agreement(store: Store, vendors: dict[str, dict], items: dict[str, dict],
                           terms: dict[str, int]) -> None:
    vendor = next(v for v in vendors.values() if v["name"] == RAWABI)
    number, start, end, lines = RAWABI_AGREEMENT
    hid = store.x("insert into PO_HEADERS_ALL(SEGMENT1, TYPE_LOOKUP_CODE, PRC_BU_ID, VENDOR_ID, VENDOR_SITE_ID,"
                  " CURRENCY_CODE, TERMS_ID, DOCUMENT_STATUS, APPROVED_FLAG, APPROVED_DATE, COMMENTS, CREATION_DATE,"
                  " START_DATE, END_DATE) values (?, 'BLANKET', ?, ?, ?, 'SAR', ?, 'OPEN', 'Y', ?, ?, ?, ?, ?)",
                  (number, PRC_BU, vendor["id"], vendor["site"], terms["Net 45"], f"{start}T10:00:00",
                   "Blanket purchase agreement: end-user devices, monitors and managed IT services at agreed prices.",
                   f"{start}T09:00:00", start, end))
    for num, (item_number, price) in enumerate(lines, start=1):
        item = items[item_number]
        store.x("insert into PO_LINES_ALL(PO_HEADER_ID, LINE_NUM, LINE_TYPE, ITEM_ID, ITEM_DESCRIPTION, CATEGORY_ID,"
                " UOM_CODE, QUANTITY, UNIT_PRICE) values (?, ?, ?, ?, ?,"
                " (select CATEGORY_ID from EGP_CATEGORIES_B where CATEGORY_CODE = ?), ?, null, ?)",
                (hid, num, "Services" if item["uom"] in ("MTH", "YR") else "Goods", item["id"], item["description"],
                 item["category"], item["uom"], str(price)))
