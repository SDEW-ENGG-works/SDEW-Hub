"""SDEW Hub - one app for the TAFE order-to-payment work at Sri Durga Engg. Works.

  config.py / db.py / http.py / auth.py / turso.py / assets.py   shared core
  local_server.py (PC) and wsgi.py (Vercel)                       the two entry points
  handlers/ + services/                                           hub pages: Today, search, trails, drop box
  supp/   Supplementary Bill  (was SupplementaryBill, port 8020)
  chep/   CHEP Transfer       (was CHEPTransfer, port 8030)
  dqms/   DQMS Upload         (was DQMSUpload, port 8040)
"""
