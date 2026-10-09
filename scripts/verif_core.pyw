import urllib.request as u,subprocess as s
try: u.urlopen('http://127.0.0.1:8765/',timeout=10)
except Exception: [s.run(['schtasks',a,'/TN','JARVIS - core'],creationflags=0x08000000) for a in ('/End','/Run')]
